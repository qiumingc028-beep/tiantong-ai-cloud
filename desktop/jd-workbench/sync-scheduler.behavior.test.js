'use strict';

const assert = require('node:assert/strict');
const { createSyncScheduler } = require('./sync-scheduler');

async function main() {
  let clock = Date.parse('2026-09-01T00:00:00Z');
  let disk = Object.create(null);
  const reports = [];
  let attempts = 0;
  const store = {
    storeUuid: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    storeId: 1,
    syncEnabled: true,
    intervalSeconds: 300,
    nextSyncAt: null,
    retryCount: 0
  };
  const scheduler = createSyncScheduler({
    now: () => clock,
    setTimer: () => ({ unref() {} }),
    clearTimer: () => undefined,
    loadState: () => disk,
    saveState: (value) => { disk = JSON.parse(JSON.stringify(value)); },
    reportState: async (_store, state) => reports.push(state),
    runStore: async () => {
      attempts += 1;
      if (attempts === 1) throw Object.assign(new Error('load failed'), { code: 'COLLECTOR_PAGE_LOAD_FAILED' });
    }
  });
  scheduler.replaceStores([store]);
  scheduler.start();
  await scheduler.tick();
  assert.equal(attempts, 1);
  assert.equal(scheduler.snapshot()[0].retryCount, 1);
  assert.equal(scheduler.snapshot()[0].nextSyncAt, '2026-09-01T00:00:30.000Z');
  assert.equal(reports.at(-1).reasonCode, 'COLLECTOR_PAGE_LOAD_FAILED');

  clock += 30_000;
  await scheduler.tick();
  assert.equal(attempts, 2);
  assert.equal(scheduler.snapshot()[0].retryCount, 0);
  assert.equal(scheduler.snapshot()[0].nextSyncAt, '2026-09-01T00:05:30.000Z');

  scheduler.stop();
  const resumed = createSyncScheduler({
    now: () => clock,
    setTimer: () => ({ unref() {} }),
    clearTimer: () => undefined,
    loadState: () => disk,
    saveState: () => undefined,
    runStore: async () => undefined
  });
  resumed.replaceStores([{ ...store, nextSyncAt: null }]);
  assert.equal(resumed.snapshot()[0].nextSyncAt, '2026-09-01T00:05:30.000Z');

  resumed.replaceStores([{ ...store, syncEnabled: false }]);
  assert.equal(resumed.snapshot()[0].status, 'PAUSED');
  assert.equal(resumed.snapshot()[0].nextSyncAt, null);
  console.log('R297_SYNC_SCHEDULER_BEHAVIOR=RETRY_RESTART_PAUSE_PASS');
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
