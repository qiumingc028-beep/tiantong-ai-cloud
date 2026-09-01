'use strict';

const assert = require('node:assert/strict');
const { createAutoSyncCoordinator } = require('./auto-sync');

function fixture(overrides = {}) {
  let currentTime = Date.parse('2026-08-31T00:00:00.000Z');
  const timers = [];
  const states = [];
  const synced = [];
  const stores = overrides.stores || [
    { storeUuid: 'store-a', status: 'READY_READ_ONLY', reason: null },
    { storeUuid: 'store-b', status: 'READY_READ_ONLY', reason: null }
  ];
  const coordinator = createAutoSyncCoordinator({
    listStores: () => stores,
    syncStore: async (store) => { synced.push(store.storeUuid); return { status: 'SYNCED' }; },
    canRun: () => true,
    now: () => currentTime,
    setTimer: (callback, delay) => { const timer = { callback, delay, unref() {} }; timers.push(timer); return timer; },
    clearTimer: () => undefined,
    intervalMs: 300_000,
    initialDelayMs: 30_000,
    onStateChange: (state) => states.push(state),
    ...overrides
  });
  return { coordinator, states, synced, timers, advance(ms) { currentTime += ms; } };
}

(async () => {
  {
    const { coordinator, timers } = fixture();
    coordinator.start();
    assert.equal(coordinator.snapshot().status, 'WAITING');
    assert.equal(timers[0].delay, 30_000);
    assert.equal(coordinator.snapshot().nextRunAt, '2026-08-31T00:00:30.000Z');
  }

  {
    const { coordinator, synced } = fixture();
    coordinator.start();
    const result = await coordinator.runNow();
    assert.deepEqual(synced, ['store-a', 'store-b']);
    assert.equal(result.total, 2);
    assert.equal(result.succeeded, 2);
    assert.equal(result.skipped, 0);
    assert.equal(result.failed, 0);
    assert.equal(result.status, 'WAITING');
  }

  {
    const lifecycle = [];
    const { coordinator } = fixture({
      beforeCycle: async () => lifecycle.push('hidden'),
      afterCycle: async () => lifecycle.push('restored')
    });
    coordinator.start();
    await coordinator.runNow();
    assert.deepEqual(lifecycle, ['hidden', 'restored']);
  }

  {
    const { coordinator, synced } = fixture({
      stores: [
        { storeUuid: 'store-a', status: 'HUMAN_ACTION_REQUIRED', reason: 'CAPTCHA_REQUIRED' },
        { storeUuid: 'store-b', status: 'READY_READ_ONLY', reason: null }
      ]
    });
    coordinator.start();
    const result = await coordinator.runNow();
    assert.deepEqual(synced, ['store-b']);
    assert.equal(result.succeeded, 1);
    assert.equal(result.skipped, 1);
    assert.equal(result.results[0].status, 'HUMAN_ACTION_REQUIRED');
  }

  {
    const timers = [];
    const coordinator = createAutoSyncCoordinator({
      listStores: () => [{ storeUuid: 'store-a', status: 'READY_READ_ONLY' }],
      syncStore: async () => { throw new Error('CLOUD_CONNECTION_FAILED'); },
      canRun: () => true,
      now: () => Date.parse('2026-08-31T00:00:00.000Z'),
      setTimer: (callback, delay) => { const timer = { callback, delay, unref() {} }; timers.push(timer); return timer; },
      clearTimer: () => undefined,
      intervalMs: 300_000,
      initialDelayMs: 0
    });
    coordinator.start();
    const result = await coordinator.runNow();
    assert.equal(result.failed, 1);
    assert.equal(timers.at(-1).delay, 60_000);
  }

  {
    const { coordinator } = fixture({ canRun: () => false });
    coordinator.start();
    const result = await coordinator.runNow();
    assert.equal(result.status, 'PAUSED');
    assert.match(result.nextRunAt, /Z$/);
  }

  console.log('auto-sync behavior checks passed');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
