import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_store_view_model_covers_directory_filters_and_eight_business_states():
    script = r"""
const assert = require('node:assert/strict');
const view = require('./frontend/r297-store-view.js');

const directory = [
  {id: 1, platform: 'jd', store_code: 'JD-001', store_name: '京东旗舰店', subject_code: 'SUB-01', subject_name: '天统一号主体', active: true, login_status: 'ONLINE'},
  {id: 2, platform: 'tmall', store_code: 'TM-002', store_name: '天猫二店', subject_id: 902, subject_code: 'SUB-02', subject_name: '天统二号主体', active: false, login_status: 'OFFLINE'}
];
const dashboard = [{store_id: 1, sync_status: 'SYNCING', sync_enabled: true, summary: {pending_shipments: 2}}];
const merged = view.mergeStores(directory, dashboard);
assert.equal(merged.length, 2);
assert.equal(merged[1].store_name, '天猫二店');
assert.equal(merged[1].summary.pending_shipments, undefined);

const calls = [];
const loaded = await view.loadStoreDirectory(async endpoint => {
  calls.push(endpoint);
  return directory;
});
assert.deepEqual(calls, ['/api/stores']);
assert.equal(loaded, directory);
assert.deepEqual(view.mergeStores(directory, [{store_id: 999, store_name: '伪造店铺'}]).map(store => store.id), [1, 2]);
let createRequest;
await view.createStore(async (endpoint, options) => { createRequest = {endpoint, options}; }, {store_name: '真实店铺'});
assert.equal(createRequest.endpoint, '/api/stores');
assert.equal(createRequest.options.method, 'POST');
assert.deepEqual(JSON.parse(createRequest.options.body), {store_name: '真实店铺'});
const operations = [];
await view.assignStore(async (endpoint, options) => operations.push({endpoint, options}), 7, '9');
await view.toggleStore(async (endpoint, options) => operations.push({endpoint, options}), 7);
assert.deepEqual(operations.map(item => item.endpoint), ['/api/stores/7/assign', '/api/stores/7/toggle']);
assert.deepEqual(JSON.parse(operations[0].options.body), {manager_user_id: 9});

assert.equal(view.filterStores(merged, {query: 'sub-02'}).length, 1);
assert.equal(view.filterStores(merged, {query: '902'}).length, 1);
assert.equal(view.filterStores(merged, {query: '天统一号'}).length, 1);
assert.equal(view.filterStores(merged, {query: '自动同步中'}).length, 1);
assert.equal(view.filterStores(merged, {platform: 'tmall'}).length, 1);
assert.equal(view.filterStores(merged, {enabled: 'inactive'}).length, 1);
assert.equal(view.filterStores(merged, {login: 'syncing'}).length, 1);

const states = [
  [{active: true, login_status: 'ONLINE'}, 'online', '已登录'],
  [{active: true, login_status: 'IDLE'}, 'syncing', '自动同步中'],
  [{active: true, login_status: 'ERROR'}, 'error', '同步异常'],
  [{active: true, login_status: 'HUMAN_ACTION_REQUIRED', login_reason: 'LOGIN_EXPIRED'}, 'expired', '登录失效'],
  [{active: true, login_status: 'HUMAN_ACTION_REQUIRED', login_reason: 'CAPTCHA_REQUIRED'}, 'captcha', '需要验证码'],
  [{active: true, login_status: 'HUMAN_ACTION_REQUIRED', login_reason: 'SMS_REQUIRED'}, 'captcha', '需要验证码'],
  [{active: true, login_status: 'HUMAN_ACTION_REQUIRED', login_reason: 'QR_REQUIRED'}, 'captcha', '需要验证码'],
  [{active: true, login_status: 'HUMAN_ACTION_REQUIRED', login_reason: 'RISK_CONTROL'}, 'risk', '风控待处理'],
  [{active: true, login_status: 'HUMAN_ACTION_REQUIRED', login_reason: 'AUTHORIZATION_REVOKED'}, 'expired', '登录失效'],
  [{active: true, login_status: 'OFFLINE'}, 'offline', '未连接'],
  [{active: false, login_status: 'ONLINE'}, 'paused', '已暂停']
];
for (const [store, key, label] of states) assert.deepEqual(view.storeStatus(store), {key, label, tone: view.storeStatus(store).tone});

const gate = view.createLatestRequestGate();
const rendered = [];
async function request(delay, value) {
  const token = gate.begin();
  await new Promise(resolve => setTimeout(resolve, delay));
  if (gate.isCurrent(token)) rendered.push(value);
}
await Promise.all([request(20, 'old'), request(0, 'new')]);
assert.deepEqual(rendered, ['new']);
"""
    subprocess.run(["node", "-e", f"(async()=>{{{script}}})().catch(error=>{{console.error(error);process.exit(1)}})"], cwd=ROOT, check=True)


def test_store_and_dashboard_pages_share_real_store_directory_and_filters():
    stores = (FRONTEND / "stores.html").read_text(encoding="utf-8")
    dashboard = (FRONTEND / "jd-dashboard.html").read_text(encoding="utf-8")

    assert "r297-store-view.js" in stores
    assert "r297-store-view.js" in dashboard
    assert "R297StoreView.loadStoreDirectory(api)" in stores
    assert "R297StoreView.loadStoreDirectory(api)" in dashboard
    assert "/api/stores" not in stores
    assert "/api/stores" not in dashboard
    assert 'id="storeSearch"' in dashboard
    assert 'id="platformFilter"' in dashboard
    assert 'id="enabledFilter"' in dashboard
    assert 'id="loginFilter"' in dashboard
    for label in ("已登录", "自动同步中", "同步异常", "登录失效", "需要验证码", "风控待处理", "未连接", "已暂停"):
        assert label in dashboard
        assert label in stores


def test_dashboard_drilldown_and_empty_state_are_real_read_only_contracts():
    dashboard = (FRONTEND / "jd-dashboard.html").read_text(encoding="utf-8")

    for metric in ("pending_shipments", "pending_refunds", "abnormal_orders"):
        assert f"data-filter=\"{metric}\"" in dashboard
    assert "openDrawer(activeFilter)" in dashboard
    assert 'data-rbac-action="metric-drilldown"' in dashboard
    assert "/api/jd-workbench/dashboard/details/${activeDetailType}" in dashboard
    assert all(field in dashboard for field in ("detailStore", "detailStart", "detailEnd", "detailStatus"))
    assert all(label in dashboard for label in ("订单引用", "商品", "当前状态", "日期"))
    assert "暂无真实数据" in dashboard
    assert "retry_count===null||store.retry_count===undefined" in dashboard
    assert "setInterval(loadData,30000)" in dashboard
    assert "网络连接失败，请稍后重试" in dashboard
    assert "method:'POST'" not in dashboard
    assert "模拟数字" not in dashboard
    assert "mock" not in dashboard.lower()
    assert "onclick=" not in dashboard.lower()
    assert 'data-required-menu="menu.jd_data"' in dashboard
    assert 'data-rbac-protected' in dashboard


def test_no_hardcoded_store_rows_or_test_backend_address():
    payload = "\n".join(
        (FRONTEND / name).read_text(encoding="utf-8")
        for name in ("stores.html", "jd-dashboard.html", "r297-store-view.js")
    )
    assert "127.0.0.1" not in payload
    assert "localhost" not in payload
    assert "demo" not in payload.lower()
    assert "mock" not in payload.lower()
    assert "/api/stores" in payload
