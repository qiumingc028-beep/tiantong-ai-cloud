'use strict';

const crypto = require('node:crypto');

const CLIENT_VERSION = '2.97.0-r297';
const MONEY_KEYS = new Set(['sales_amount', 'month_sales', 'year_sales', 'ad_spend', 'ad_cpm', 'ad_cpc']);
const RATIO_KEYS = new Set(['conversion_rate', 'ad_ctr']);
const INTEGER_KEYS = new Set([
  'sales_orders', 'sales_customers', 'product_units', 'visitors', 'page_views',
  'ad_impressions', 'ad_clicks', 'pending_shipments', 'pending_refunds', 'inventory_risk', 'abnormal_orders'
]);
const ALLOWED_KEYS = new Set([...MONEY_KEYS, ...RATIO_KEYS, ...INTEGER_KEYS]);

function invalidPayload() {
  const error = new Error('SYNC_PAYLOAD_INVALID');
  error.code = 'SYNC_PAYLOAD_INVALID';
  return error;
}

function parseDisplayNumber(rawValue, type) {
  let text = String(rawValue || '').trim();
  if (!text || /^[-—]+$/.test(text)) return null;
  text = text.replace(/[, \s¥￥]/g, '');
  const multiplier = text.includes('亿') ? 100_000_000 : text.includes('万') ? 10_000 : 1;
  text = text.replace(/[%万亿元笔单人次件个]/g, '').replace(/SKU$/i, '');
  if (!/^\d+(?:\.\d+)?$/.test(text)) return null;
  const numeric = Number(text) * multiplier;
  if (!Number.isFinite(numeric) || numeric < 0) return null;
  if (type === 'integer') {
    const rounded = Math.round(numeric);
    return Number.isSafeInteger(rounded) && Math.abs(rounded - numeric) < 1e-8 ? rounded : null;
  }
  if (type === 'money') return Number(numeric.toFixed(2));
  return Number(numeric.toFixed(4));
}

function buildSyncPayload({ store, recognition }) {
  if (
    !store || !Number.isSafeInteger(store.storeId) || store.storeId <= 0 ||
    !Number.isSafeInteger(store.subjectId) || store.subjectId <= 0 ||
    !recognition || recognition.status !== 'RECOGNIZED' ||
    !Array.isArray(recognition.metrics) || !recognition.metrics.length
  ) {
    throw invalidPayload();
  }
  const capturedAt = new Date(recognition.capturedAt);
  if (!Number.isFinite(capturedAt.getTime())) throw invalidPayload();

  const record = Object.create(null);
  for (const metric of recognition.metrics.slice(0, 40)) {
    const key = String((metric && metric.key) || '');
    if (!ALLOWED_KEYS.has(key) || Object.hasOwn(record, key)) continue;
    const type = MONEY_KEYS.has(key) ? 'money' : RATIO_KEYS.has(key) ? 'ratio' : 'integer';
    const value = parseDisplayNumber(metric.value, type);
    if (value !== null) record[key] = value;
  }
  if (!Object.keys(record).length) throw invalidPayload();

  const canonicalMetrics = JSON.stringify(Object.fromEntries(Object.entries(record).sort(([a], [b]) => a.localeCompare(b))));
  const digest = crypto.createHash('sha256').update([
    String(store.storeId), String(store.storeUuid || ''), capturedAt.toISOString(),
    String(recognition.pageType || 'JD_PAGE'), canonicalMetrics
  ].join('\0'), 'utf8').digest('hex');
  record.source_record_key = digest;

  return Object.freeze({
    store_id: store.storeId,
    subject_id: store.subjectId,
    dataset_type: 'operating_metrics',
    source_period: capturedAt.toISOString().slice(0, 10),
    collected_at: capturedAt.toISOString(),
    idempotency_key: `r297-${digest}`,
    client_version: CLIENT_VERSION,
    records: [Object.freeze(record)]
  });
}

module.exports = Object.freeze({
  ALLOWED_KEYS,
  CLIENT_VERSION,
  buildSyncPayload,
  parseDisplayNumber
});
