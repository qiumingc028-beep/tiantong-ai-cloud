'use strict';

const RETRY_DELAYS_MS = Object.freeze([30_000, 120_000, 300_000, 900_000, 1_800_000]);
const DEFAULT_INTERVAL_SECONDS = 300;

function iso(milliseconds) {
  return new Date(milliseconds).toISOString();
}

function safeTime(value) {
  const parsed = Date.parse(String(value || ''));
  return Number.isFinite(parsed) ? parsed : null;
}

function normalizeErrorCode(error) {
  const code = String((error && (error.code || error.message)) || 'COLLECTOR_SCHEMA_MISMATCH')
    .replace(/^Error:\s*/, '')
    .trim()
    .toUpperCase();
  const allowed = new Set([
    'CLOUD_CONNECTION_FAILED',
    'COLLECTOR_PAGE_LOAD_FAILED',
    'COLLECTOR_SCHEMA_MISMATCH',
    'COLLECTOR_EMPTY',
    'SYNC_UPLOAD_REJECTED',
    'LOGIN_EXPIRED',
    'RISK_CONTROL',
    'CAPTCHA_REQUIRED'
  ]);
  return allowed.has(code) ? code : 'COLLECTOR_SCHEMA_MISMATCH';
}

function createSyncScheduler({
  now = () => Date.now(),
  setTimer = setTimeout,
  clearTimer = clearTimeout,
  loadState = () => ({}),
  saveState = () => undefined,
  runStore,
  reportState = async () => undefined
}) {
  if (typeof runStore !== 'function') throw new Error('SYNC_RUNNER_REQUIRED');
  let timer = null;
  let stopped = true;
  let running = false;
  let stores = [];
  const persisted = loadState() || {};
  const runtime = new Map();

  function stateFor(store) {
    let state = runtime.get(store.storeUuid);
    if (state) return state;
    const cloudNext = safeTime(store.nextSyncAt);
    const disk = persisted[store.storeUuid] || {};
    const diskNext = safeTime(disk.nextSyncAt);
    state = {
      retryCount: Number.isInteger(store.retryCount) ? store.retryCount : (Number.isInteger(disk.retryCount) ? disk.retryCount : 0),
      nextSyncAt: cloudNext ?? diskNext ?? now(),
      lastAttemptAt: safeTime(store.lastAttemptAt) ?? safeTime(disk.lastAttemptAt),
      running: false
    };
    runtime.set(store.storeUuid, state);
    return state;
  }

  function persist() {
    const payload = Object.create(null);
    for (const store of stores) {
      const state = stateFor(store);
      payload[store.storeUuid] = {
        retryCount: state.retryCount,
        nextSyncAt: state.nextSyncAt === null ? null : iso(state.nextSyncAt),
        lastAttemptAt: state.lastAttemptAt === null ? null : iso(state.lastAttemptAt)
      };
    }
    saveState(payload);
  }

  function publicState(store) {
    const state = stateFor(store);
    return Object.freeze({
      storeUuid: store.storeUuid,
      status: store.syncEnabled === false ? 'PAUSED' : (state.running ? 'SYNCING' : 'IDLE'),
      retryCount: state.retryCount,
      nextSyncAt: state.nextSyncAt === null ? null : iso(state.nextSyncAt),
      lastAttemptAt: state.lastAttemptAt === null ? null : iso(state.lastAttemptAt)
    });
  }

  function scheduleNext() {
    if (stopped || timer) return;
    const enabled = stores.filter((store) => store.syncEnabled !== false);
    if (!enabled.length) return;
    const earliest = Math.min(...enabled.map((store) => stateFor(store).nextSyncAt ?? now()));
    timer = setTimer(() => {
      timer = null;
      tick().catch(() => undefined);
    }, Math.max(0, earliest - now()));
    timer.unref?.();
  }

  async function execute(store, force = false) {
    const state = stateFor(store);
    if (store.syncEnabled === false || state.running || (!force && state.nextSyncAt > now())) return false;
    state.running = true;
    state.lastAttemptAt = now();
    persist();
    await reportState(store, {
      status: 'SYNCING',
      retryCount: state.retryCount,
      lastAttemptAt: iso(state.lastAttemptAt),
      nextSyncAt: null
    });
    try {
      await runStore(store);
      state.retryCount = 0;
      state.nextSyncAt = now() + (store.intervalSeconds || DEFAULT_INTERVAL_SECONDS) * 1000;
      await reportState(store, {
        status: 'IDLE',
        retryCount: 0,
        lastAttemptAt: iso(state.lastAttemptAt),
        nextSyncAt: iso(state.nextSyncAt)
      });
      return true;
    } catch (error) {
      const index = Math.min(state.retryCount, RETRY_DELAYS_MS.length - 1);
      state.retryCount = Math.min(state.retryCount + 1, RETRY_DELAYS_MS.length);
      state.nextSyncAt = now() + RETRY_DELAYS_MS[index];
      await reportState(store, {
        status: 'ERROR',
        reasonCode: normalizeErrorCode(error),
        retryCount: state.retryCount,
        lastAttemptAt: iso(state.lastAttemptAt),
        nextSyncAt: iso(state.nextSyncAt)
      });
      return false;
    } finally {
      state.running = false;
      persist();
    }
  }

  async function tick() {
    if (stopped || running) return;
    running = true;
    try {
      for (const store of stores) await execute(store);
    } finally {
      running = false;
      scheduleNext();
    }
  }

  function replaceStores(nextStores) {
    stores = [...nextStores];
    const authorized = new Set(stores.map((store) => store.storeUuid));
    for (const key of runtime.keys()) if (!authorized.has(key)) runtime.delete(key);
    for (const store of stores) {
      const state = stateFor(store);
      if (store.syncEnabled === false) state.nextSyncAt = null;
      else if (state.nextSyncAt === null) state.nextSyncAt = now();
    }
    persist();
    if (timer) {
      clearTimer(timer);
      timer = null;
    }
    scheduleNext();
  }

  function start() {
    stopped = false;
    scheduleNext();
  }

  function stop() {
    stopped = true;
    if (timer) clearTimer(timer);
    timer = null;
    persist();
  }

  async function runNow(storeUuid = null) {
    const selected = storeUuid === null ? stores : stores.filter((store) => store.storeUuid === storeUuid);
    for (const store of selected) await execute(store, true);
    scheduleNext();
    return snapshot();
  }

  function snapshot() {
    return stores.map(publicState);
  }

  return Object.freeze({ replaceStores, runNow, snapshot, start, stop, tick });
}

module.exports = Object.freeze({
  DEFAULT_INTERVAL_SECONDS,
  RETRY_DELAYS_MS,
  createSyncScheduler,
  normalizeErrorCode
});
