'use strict';

const assert = require('node:assert/strict');
const vm = require('node:vm');
const {
  buildRecognizerScript,
  detectPageType,
  extractMetricsFromLines
} = require('./page-recognizer');

const metrics = extractMetricsFromLines([
  '经营数据',
  '成交金额', '-', '较昨日', '-',
  '成交单量', '-', '较昨日', '-',
  '成交客户数', '-', '较昨日', '-',
  '店铺访客数', '300', '较昨日', '+177.78%',
  '店铺浏览量', '577', '较昨日', '+155.31%',
  '推广数据',
  '快车花费', '¥345.70',
  '快车展现数', '10,547',
  '快车点击数', '385',
  '快车点击率', '3.65%',
  '快车千次展现成本', '¥32.78',
  '快车平均点击成本', '¥0.90',
  '收货人手机号', '13800138000'
]);

const values = Object.fromEntries(metrics.map((item) => [item.key, item.value]));
assert.equal(values.visitors, '300');
assert.equal(values.page_views, '577');
assert.equal(values.ad_spend, '¥345.70');
assert.equal(values.ad_impressions, '10,547');
assert.equal(values.ad_clicks, '385');
assert.equal(values.ad_ctr, '3.65%');
assert.equal(values.ad_cpm, '¥32.78');
assert.equal(values.ad_cpc, '¥0.90');
assert.equal(metrics.some((item) => item.value === '13800138000'), false, 'PII must never enter the allowlisted output');

assert.equal(detectPageType('https://shop.jd.com/jdm/home', '京麦', '经营数据'), 'JDM_HOME');
assert.equal(detectPageType('https://sz.jd.com/home', '京东商智', '经营概览'), 'BUSINESS_INTELLIGENCE');
assert.equal(detectPageType('https://trade-order-jdm.jd.com/export', '订单导出', ''), 'ORDER_EXPORT');
assert.equal(buildRecognizerScript().includes('document.body.innerText'), true);
assert.equal(buildRecognizerScript().includes('document.cookie'), false);
assert.equal(buildRecognizerScript().includes('input'), false);

const browserResult = vm.runInNewContext(buildRecognizerScript(), {
  document: {
    title: '京麦商家后台',
    body: { innerText: '经营数据\n店铺访客数\n300\n店铺浏览量\n577\n快车花费\n¥345.70' }
  },
  location: {
    href: 'https://shop.jd.com/jdm/home',
    hostname: 'shop.jd.com',
    pathname: '/jdm/home'
  }
});
assert.equal(browserResult.pageType, 'JDM_HOME');
assert.deepEqual(
  Array.from(browserResult.metrics, (item) => [item.key, item.value]),
  [['visitors', '300'], ['page_views', '577'], ['ad_spend', '¥345.70']]
);

console.log('R294_PAGE_RECOGNIZER=PASS');
