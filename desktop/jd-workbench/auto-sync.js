'use strict';

const DEFAULT_INTERVAL_MS = 5 * 60 * 1000;
const DEFAULT_INITIAL_DELAY_MS = 30 * 1000;
const PAUSED_RETRY_MS = 60 * 1000;
const RETRY_DELAYS_MS = Object.freeze([30 * 1000, 2 * 60 * 1000, 5 * 60 * 1000, 15 * 60 * 1000, 30 * 60 * 1000]);
const HUMAN_ACTION_REASONS = new Set([
  'CAPTCHA', 'CAPTCHA_REQUIRED', 'RISK_CONTROL', 'LOGIN_EXPIRED', 'LOGIN_REQUIRED'
]);
const SKIPPED_ERRORS = new Set([
  'NO_RECOGNIZED_METRICS', 'REMOTE_VIEW_PAUSED', 'STORE_NOT_OPEN', 'PAGE_RECOGNITION_INVALID'
]);

function errorCode(error) {
  return String((error && (error.code || error.message)) || 'AUTO_SYNC_FAILED')
    .replace(/^Error:\s*/, '')
    .slice(0, 96);
}

function isoTime(value) {
  return new Date(value).toISOString();
}

function createAutoSyncCoordinator({
  listStores,
  syncStore,
  canRun,
  beforeCycle = async () => undefined,
  afterCycle = async () => undefined,
  onStateChange = () => undefined,
  now = () => Date.now(),
  setTimer = setTimeout,
  clearTimer = clearTimeout,
  intervalMs = DEFAULT_INTERVAL_MS,
  initialDelayMs = DEFAULT_INITIAL_DELAY_MS,
  retryDelaysMs = RETRY_DELAYS_MS
}) {
  if (
    typeof listStores !== 'function' ||
    typeof syncStore !== 'function' ||
    typeof canRun !== 'function' ||
    typeof beforeCycle !== 'function' ||
    typeof afterCycle !== 'function'
  ) {
    throw new Error('AUTO_SYNC_CONFIG_INVALID');
  }
  if (!Number.isSafeInteger(intervalMs) || intervalMs < 1000 || !Number.isSafeInteger(initialDelayMs) || initialDelayMs < 0) {
    throw new Error('AUTO_SYNC_CONFIG_INVALID');
  }

  let started = false;
  let timer = null;
  let inFlight = null;
  let failureStreak = 0;
  let state = Object.freeze({
    enabled: true,
    status: 'STOPPED',
    intervalMs,
    nextRunAt: null,
    lastCycleStartedAt: null,
    lastCycleFinishedAt: null,
    currentStoreUuid: null,
    total: 0,
    succeeded: 0,
    skipped: 0,
    failed: 0,
    results: []
  });

  function snapshot() {
    return state;
  }

  function update(patch) {
    state = Object.freeze({ ...state, ...patch });
    onStateChange(state);
    return state;
  }

  function cancelScheduled() {
    if (timer !== null) clearTimer(timer);
    timer = null;
  }

  function schedule(delayMs, status = 'WAITING') {
    cancelScheduled();
    if (!started) return;
    const delay = Math.max(0, Number(delayMs) || 0);
    update({ status, nextRunAt: isoTime(now() + delay), currentStoreUuid: null });
    timer = setTimer(() => {
      timer = null;
      runNow().catch(() => undefined);
    }, delay);
    timer && timer.unref && timer.unref();
  }

  function storeNeedsHuman(store) {
    return store && (store.status === 'HUMAN_ACTION_REQUIRED' || HUMAN_ACTION_REASONS.has(String(store.reason || '').toUpperCase()));
  }

  async function executeCycle() {
    if (!started) return snapshot();
    if (!canRun()) {
      schedule(PAUSED_RETRY_MS, 'PAUSED');
      return snapshot();
    }

    const stores = (await Promise.resolve(listStores())).filter((store) => store && typeof store.storeUuid === 'string');
    const startedAt = isoTime(now());
    const results = [];
    let succeeded = 0;
    let skipped = 0;
    let failed = 0;
    update({
      status: 'RUNNING', nextRunAt: null, lastCycleStartedAt: startedAt,
      currentStoreUuid: null, total: stores.length, succeeded: 0, skipped: 0, failed: 0, results: []
    });

    await beforeCycle(Object.freeze([...stores]));
    try {
      for (const store of stores) {
        if (!started || !canRun()) {
          skipped += 1;
          results.push(Object.freeze({ storeUuid: store.storeUuid, status: 'SKIPPED', error: 'AUTO_SYNC_PAUSED' }));
          continue;
        }
        if (storeNeedsHuman(store)) {
          skipped += 1;
          results.push(Object.freeze({ storeUuid: store.storeUuid, status: 'HUMAN_ACTION_REQUIRED', error: store.reason || null }));
          continue;
        }
        update({ currentStoreUuid: store.storeUuid, succeeded, skipped, failed, results: Object.freeze([...results]) });
        try {
          const result = await syncStore(Object.freeze({ ...store }));
          if (result && result.skipped) {
            skipped += 1;
            results.push(Object.freeze({ storeUuid: store.storeUuid, status: 'SKIPPED', error: result.error || null }));
          } else {
            succeeded += 1;
            results.push(Object.freeze({ storeUuid: store.storeUuid, status: (result && result.status) || 'SYNCED', error: null }));
          }
        } catch (error) {
          const code = errorCode(error);
          if (SKIPPED_ERRORS.has(code) || HUMAN_ACTION_REASONS.has(code)) {
            skipped += 1;
            results.push(Object.freeze({ storeUuid: store.storeUuid, status: 'SKIPPED', error: code }));
          } else {
            failed += 1;
            results.push(Object.freeze({ storeUuid: store.storeUuid, status: 'FAILED', error: code }));
          }
        }
      }
    } finally {
      await afterCycle(Object.freeze({
        stores: Object.freeze([...stores]),
        results: Object.freeze([...results])
      }));
    }

    const finishedAt = isoTime(now());
    failureStreak = failed ? failureStreak + 1 : 0;
    update({
      status: failed ? 'RETRY_WAIT' : 'WAITING',
      lastCycleFinishedAt: finishedAt,
      currentStoreUuid: null,
      total: stores.length,
      succeeded,
      skipped,
      failed,
      results: Object.freeze(results)
    });
    const retryIndex = Math.min(Math.max(failureStreak - 1, 0), retryDelaysMs.length - 1);
    schedule(failed ? retryDelaysMs[retryIndex] : intervalMs, failed ? 'RETRY_WAIT' : 'WAITING');
    return snapshot();
  }

  function runNow() {
    cancelScheduled();
    if (inFlight) return inFlight;
    inFlight = executeCycle().finally(() => { inFlight = null; });
    return inFlight;
  }

  function start() {
    if (started) return snapshot();
    started = true;
    schedule(initialDelayMs);
    return snapshot();
  }

  function wake(delayMs = 1000) {
    if (!started || inFlight) return snapshot();
    schedule(delayMs);
    return snapshot();
  }

  function stop() {
    started = false;
    cancelScheduled();
    update({ status: 'STOPPED', nextRunAt: null, currentStoreUuid: null });
    return snapshot();
  }

  return Object.freeze({ runNow, snapshot, start, stop, wake });
}

module.exports = Object.freeze({
  DEFAULT_INITIAL_DELAY_MS,
  DEFAULT_INTERVAL_MS,
  PAUSED_RETRY_MS,
  RETRY_DELAYS_MS,
  createAutoSyncCoordinator,
  errorCode
});
