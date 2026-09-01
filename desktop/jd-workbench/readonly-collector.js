'use strict';

const crypto = require('node:crypto');

const ROUTES = Object.freeze({
  dashboard: 'https://shop.jd.com/jdm/home',
  fulfillment: 'https://trade-order-jdm.jd.com/orderList/waitOut',
  aftersales: 'https://shop.jd.com/jdm/trade/after-sale',
  abnormal: 'https://trade-order-jdm.jd.com/orderList'
});

const SNAPSHOT_SCRIPT = `(() => {
  const clean = (value, maximum = 500) => String(value || '').replace(/\\s+/g, ' ').trim().slice(0, maximum);
  const tables = [...document.querySelectorAll('table')].slice(0, 20).map((table) => {
    const headers = [...table.querySelectorAll('thead th')].map((cell) => clean(cell.innerText));
    const rows = [...table.querySelectorAll('tbody tr')].slice(0, 500).map((row) =>
      [...row.querySelectorAll('td')].map((cell) => clean(cell.innerText))
    );
    return { headers, rows };
  }).filter((table) => table.headers.length && table.rows.every((row) => row.length <= 40));
  return {
    url: location.href,
    title: clean(document.title),
    text: clean(document.body && document.body.innerText, 100000),
    tables
  };
})()`;

function collectorError(code) {
  const error = new Error(code);
  error.code = code;
  return error;
}

function cleanText(value, maximum = 200) {
  return String(value || '').replace(/[\u0000-\u001f\u007f]/g, '').replace(/\s+/g, ' ').trim().slice(0, maximum);
}

function opaque(value) {
  return crypto.createHash('sha256').update(cleanText(value, 500), 'utf8').digest('hex');
}

function number(value, integer = false) {
  const normalized = cleanText(value, 80).replace(/[￥¥,，\s]/g, '');
  const match = normalized.match(/-?\d+(?:\.\d+)?/);
  if (!match) return null;
  const parsed = Number(match[0]);
  if (!Number.isFinite(parsed) || parsed < 0) return null;
  return integer ? Math.trunc(parsed) : parsed.toFixed(2);
}

function dateTime(value, fallback) {
  const cleaned = cleanText(value, 80).replace(/[年/.]/g, '-').replace(/月/g, '-').replace(/日/g, ' ');
  const parsed = Date.parse(cleaned);
  return Number.isFinite(parsed) ? new Date(parsed).toISOString() : fallback;
}

function metric(text, labels, integer = false) {
  for (const label of labels) {
    const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const match = text.match(new RegExp(`${escaped}[^0-9]{0,24}([0-9][0-9,.]*)`, 'i'));
    if (match) return number(match[1], integer);
  }
  return null;
}

function todayPeriod(collectedAt) {
  return String(collectedAt).slice(0, 10);
}

function dashboardDatasets(snapshot, collectedAt) {
  const text = cleanText(snapshot && snapshot.text, 100000);
  if (!text) throw collectorError('COLLECTOR_EMPTY');
  const salesAmount = metric(text, ['成交金额', '销售额', '支付金额']);
  const ordersCount = metric(text, ['支付订单数', '成交订单数', '订单量'], true);
  const refundAmount = metric(text, ['退款金额']);
  const refundOrderCount = metric(text, ['退款订单数', '退款单量'], true);
  const datasets = [];
  if (salesAmount !== null && ordersCount !== null) {
    datasets.push({
      datasetType: 'sales_daily',
      sourcePeriod: todayPeriod(collectedAt),
      records: [{ source_record_key: opaque(`sales:${collectedAt}`), sales_amount: salesAmount, orders_count: ordersCount }]
    });
  }
  if (refundAmount !== null && refundOrderCount !== null) {
    datasets.push({
      datasetType: 'refunds',
      sourcePeriod: todayPeriod(collectedAt),
      records: [{ source_record_key: opaque(`refunds:${collectedAt}`), refund_order_count: refundOrderCount, refund_amount: refundAmount }]
    });
  }
  return datasets;
}

function column(headers, patterns) {
  return headers.findIndex((header) => patterns.some((pattern) => pattern.test(cleanText(header, 100))));
}

function matchingTable(snapshot, requiredColumns) {
  for (const table of (snapshot && snapshot.tables) || []) {
    if (!Array.isArray(table.headers) || !Array.isArray(table.rows)) continue;
    const indexes = Object.fromEntries(Object.entries(requiredColumns).map(([key, patterns]) => [key, column(table.headers, patterns)]));
    if (Object.values(indexes).every((index) => index >= 0)) return { table, indexes };
  }
  return null;
}

function fulfillmentDataset(snapshot, collectedAt) {
  const found = matchingTable(snapshot, {
    identity: [/订单号/, /订单编号/],
    state: [/状态/, /订单状态/],
    product: [/商品/, /商品信息/],
    quantity: [/数量/],
    paid: [/实付/, /金额/],
    ordered: [/下单时间/, /订单时间/]
  });
  if (!found) throw collectorError('COLLECTOR_SCHEMA_MISMATCH');
  const deadline = column(found.table.headers, [/最迟发货/, /承诺发货/, /发货时限/]);
  const records = found.table.rows.map((row) => {
    const identity = cleanText(row[found.indexes.identity], 160);
    if (!identity) return null;
    const record = {
      source_record_key: opaque(`fulfillment:${identity}:${collectedAt}`),
      order_state: cleanText(row[found.indexes.state], 64) || '待发货',
      product_name: cleanText(row[found.indexes.product], 200) || '商品信息未展示',
      quantity: number(row[found.indexes.quantity], true) ?? 0,
      paid_amount: number(row[found.indexes.paid]) ?? '0.00',
      ordered_at: dateTime(row[found.indexes.ordered], collectedAt)
    };
    if (deadline >= 0 && cleanText(row[deadline])) record.promised_ship_at = dateTime(row[deadline], collectedAt);
    return record;
  }).filter(Boolean);
  return { datasetType: 'fulfillment_orders', sourcePeriod: todayPeriod(collectedAt), records };
}

function aftersaleDataset(snapshot, collectedAt) {
  const found = matchingTable(snapshot, {
    identity: [/服务单号/, /售后单号/, /订单号/],
    state: [/状态/, /售后状态/],
    product: [/商品/, /商品信息/],
    quantity: [/数量/],
    refund: [/退款金额/, /金额/],
    requested: [/申请时间/, /创建时间/]
  });
  if (!found) throw collectorError('COLLECTOR_SCHEMA_MISMATCH');
  const reason = column(found.table.headers, [/原因/, /问题类型/]);
  const records = found.table.rows.map((row) => {
    const identity = cleanText(row[found.indexes.identity], 160);
    if (!identity) return null;
    const record = {
      source_record_key: opaque(`aftersale:${identity}:${collectedAt}`),
      aftersale_state: cleanText(row[found.indexes.state], 64) || '待处理',
      product_name: cleanText(row[found.indexes.product], 200) || '商品信息未展示',
      quantity: number(row[found.indexes.quantity], true) ?? 0,
      refund_amount: number(row[found.indexes.refund]) ?? '0.00',
      requested_at: dateTime(row[found.indexes.requested], collectedAt)
    };
    if (reason >= 0 && cleanText(row[reason])) record.reason_category = cleanText(row[reason], 120);
    return record;
  }).filter(Boolean);
  return { datasetType: 'aftersale_orders', sourcePeriod: todayPeriod(collectedAt), records };
}

function abnormalDataset(snapshot, collectedAt) {
  const found = matchingTable(snapshot, {
    identity: [/订单号/, /订单编号/],
    state: [/状态/, /订单状态/],
    product: [/商品/, /商品信息/],
    quantity: [/数量/]
  });
  if (!found) throw collectorError('COLLECTOR_SCHEMA_MISMATCH');
  const reason = column(found.table.headers, [/异常原因/, /原因/, /问题类型/]);
  const detected = column(found.table.headers, [/更新时间/, /下单时间/, /订单时间/]);
  const abnormalPattern = /异常|超时|锁定|风控|失败|纠纷|拒收/;
  const records = found.table.rows.map((row) => {
    const identity = cleanText(row[found.indexes.identity], 160);
    const state = cleanText(row[found.indexes.state], 64);
    if (!identity || !abnormalPattern.test(state)) return null;
    const record = {
      source_record_key: opaque(`abnormal:${identity}:${state}:${collectedAt}`),
      abnormal_state: state,
      product_name: cleanText(row[found.indexes.product], 200) || '商品信息未展示',
      quantity: number(row[found.indexes.quantity], true) ?? 0,
      detected_at: detected >= 0 ? dateTime(row[detected], collectedAt) : collectedAt
    };
    if (reason >= 0 && cleanText(row[reason])) record.reason_category = cleanText(row[reason], 120);
    return record;
  }).filter(Boolean);
  return { datasetType: 'abnormal_orders', sourcePeriod: todayPeriod(collectedAt), records };
}

function normalizeSnapshot(kind, snapshot, collectedAt = new Date().toISOString()) {
  if (/验证码|安全验证|风险验证|风控/.test(cleanText(`${snapshot && snapshot.title} ${snapshot && snapshot.text}`, 100000))) {
    throw collectorError('RISK_CONTROL');
  }
  if (kind === 'dashboard') return dashboardDatasets(snapshot, collectedAt);
  if (kind === 'fulfillment') return [fulfillmentDataset(snapshot, collectedAt)];
  if (kind === 'aftersales') return [aftersaleDataset(snapshot, collectedAt)];
  if (kind === 'abnormal') return [abnormalDataset(snapshot, collectedAt)];
  throw collectorError('COLLECTOR_SCHEMA_MISMATCH');
}

module.exports = Object.freeze({ ROUTES, SNAPSHOT_SCRIPT, normalizeSnapshot, opaque });
