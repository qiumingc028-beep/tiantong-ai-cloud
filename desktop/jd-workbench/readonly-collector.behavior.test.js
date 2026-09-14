'use strict';

const assert = require('node:assert/strict');
const { normalizeSnapshot } = require('./readonly-collector');

const collectedAt = '2026-09-01T08:00:00.000Z';
const dashboard = normalizeSnapshot('dashboard', {
  title: '京麦商家中心',
  text: '今日成交金额 ¥12,800.50 支付订单数 18 退款金额 ¥688.00 退款订单数 2',
  tables: []
}, collectedAt);
assert.equal(dashboard[0].records[0].sales_amount, '12800.50');
assert.equal(dashboard[0].records[0].orders_count, 18);

const fulfillment = normalizeSnapshot('fulfillment', {
  title: '待出库订单',
  text: '订单列表',
  tables: [{
    headers: ['订单号', '订单状态', '商品信息', '数量', '实付金额', '下单时间', '最迟发货'],
    rows: [['123456789', '待出库', '商务机械表', '1', '¥1280.00', '2026-09-01 07:00:00', '2026-09-02 07:00:00']]
  }]
}, collectedAt)[0];
assert.equal(fulfillment.records[0].paid_amount, '1280.00');
assert.equal(fulfillment.records[0].source_record_key.length, 64);
assert.ok(!JSON.stringify(fulfillment).includes('123456789'));

const aftersales = normalizeSnapshot('aftersales', {
  title: '售后订单',
  text: '售后列表',
  tables: [{
    headers: ['服务单号', '售后状态', '商品', '数量', '退款金额', '申请时间', '原因'],
    rows: [['987654321', '待审核', '女士石英表', '1', '688', '2026-09-01 07:30:00', '商品问题']]
  }]
}, collectedAt)[0];
assert.equal(aftersales.records[0].aftersale_state, '待审核');
assert.ok(!JSON.stringify(aftersales).includes('987654321'));

assert.throws(
  () => normalizeSnapshot('fulfillment', { title: '订单', text: '订单列表', tables: [] }, collectedAt),
  /COLLECTOR_SCHEMA_MISMATCH/
);
console.log('R297_READONLY_COLLECTOR_BEHAVIOR=NORMALIZATION_PRIVACY_PASS');
