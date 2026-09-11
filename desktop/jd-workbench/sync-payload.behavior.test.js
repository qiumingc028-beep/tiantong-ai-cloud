'use strict';

const assert = require('node:assert/strict');
const { buildSyncPayload, parseDisplayNumber } = require('./sync-payload');

assert.equal(parseDisplayNumber('¥3,457.80', 'money'), 3457.8);
assert.equal(parseDisplayNumber('1.25万', 'integer'), 12500);
assert.equal(parseDisplayNumber('3.65%', 'ratio'), 3.65);
assert.equal(parseDisplayNumber('-', 'money'), null);

const payload = buildSyncPayload({
  store: {
    storeId: 17,
    subjectId: 3,
    storeUuid: 'a7d3456a-2ccb-4a67-85c5-a23528c8d4dd'
  },
  recognition: {
    status: 'RECOGNIZED',
    pageType: 'JDM_HOME',
    capturedAt: '2026-08-30T20:16:26.000Z',
    metrics: [
      { key: 'sales_amount', value: '-' },
      { key: 'visitors', value: '304' },
      { key: 'page_views', value: '583' },
      { key: 'ad_spend', value: '¥345.70' },
      { key: 'ad_impressions', value: '10,547' },
      { key: 'ad_ctr', value: '3.65%' },
      { key: 'password', value: 'secret' }
    ]
  }
});

assert.equal(payload.dataset_type, 'operating_metrics');
assert.equal(payload.source_period, '2026-08-30');
assert.equal(payload.client_version, '2.97.0-r297');
assert.match(payload.idempotency_key, /^r297-[0-9a-f]{64}$/);
assert.deepEqual(Object.keys(payload.records[0]).sort(), [
  'ad_ctr', 'ad_impressions', 'ad_spend', 'page_views', 'source_record_key', 'visitors'
]);
assert.equal(payload.records[0].visitors, 304);
assert.equal(payload.records[0].page_views, 583);
assert.equal(payload.records[0].ad_spend, 345.7);
assert.equal(payload.records[0].ad_impressions, 10547);
assert.equal(payload.records[0].ad_ctr, 3.65);
assert.equal(payload.records[0].password, undefined);

assert.throws(() => buildSyncPayload({
  store: { storeId: 17, subjectId: 3 },
  recognition: {
    status: 'RECOGNIZED',
    capturedAt: '2026-08-30T20:16:26.000Z',
    metrics: [{ key: 'sales_amount', value: '-' }]
  }
}), /SYNC_PAYLOAD_INVALID/);

console.log('R297_SYNC_PAYLOAD=PASS');
