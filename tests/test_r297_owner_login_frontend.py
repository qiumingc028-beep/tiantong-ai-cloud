import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_owner_login_client_uses_only_store_scoped_backend_routes():
    script = r"""
const assert = require('node:assert/strict');
const login = require('./frontend/r297-owner-login.js');

const calls = [];
const client = login.createClient(async (path, options = {}) => {
  calls.push({path, options});
  return {store_id: 7, status: 'LOGIN_REQUIRED'};
});
await client.create(7);
await client.status(7);
await client.ticket(7);
await client.close(7);
assert.deepEqual(calls.map(call => [call.path, call.options.method || 'GET']), [
  ['/api/jd-workbench/stores/7/login-session', 'POST'],
  ['/api/jd-workbench/stores/7/login-session', 'GET'],
  ['/api/jd-workbench/stores/7/login-ticket', 'POST'],
  ['/api/jd-workbench/stores/7/login-session', 'DELETE']
]);
assert.ok(calls.every(call => !('body' in call.options)));
assert.throws(() => client.create('session-from-user'), /店铺标识无效/);
assert.equal(login.isOwner({role_code: 'owner'}), true);
assert.equal(login.isOwner({role_code: 'admin'}), false);
assert.equal(login.isOwner({role_code: 'operator'}), false);
assert.deepEqual(login.sessionState(7, {store_id: 7, status: 'LOGIN_REQUIRED', expires_in: 600, ignored: 'not persisted'}), {store_id: 7, status: 'LOGIN_REQUIRED', expires_in: 600});
assert.throws(() => login.sessionState(7, {store_id: 8, status: 'ONLINE'}), /店铺作用域不匹配/);
"""
    subprocess.run(
        ["node", "-e", f"(async()=>{{{script}}})().catch(error=>{{console.error(error);process.exit(1)}})"],
        cwd=ROOT,
        check=True,
    )


def test_owner_login_statuses_errors_and_polling_fail_closed():
    script = r"""
const assert = require('node:assert/strict');
const login = require('./frontend/r297-owner-login.js');

const labels = {
  UNKNOWN: '尚未查询',
  OFFLINE: '未登录', LOGIN_REQUIRED: '等待扫码', CAPTCHA_REQUIRED: '验证码',
  SMS_REQUIRED: '短信验证', RISK_CONTROL: '风控', ONLINE: '登录成功',
  LOGIN_EXPIRED: '登录失效', TICKET_EXPIRED: 'ticket过期',
  AUTHORIZATION_REVOKED: '授权撤销', REVOKED: '授权撤销',
  SESSION_DESTROYED: '会话销毁', RUNTIME_UNAVAILABLE: '云端登录服务暂不可用',
  SYNC_RECOVERED: '自动同步恢复', ERROR: '同步失败'
};
for (const [status, label] of Object.entries(labels)) assert.equal(login.statusView(status).label, label);
assert.equal(login.errorMessage({status: 403}), '无权管理该店铺的云端登录会话');
assert.equal(login.errorMessage({status: 503}), '云端登录服务暂不可用');

const operationGate = login.createOperationGate();
const slowCreate = operationGate.begin();
const fastClose = operationGate.begin();
assert.equal(operationGate.isCurrent(slowCreate), false);
assert.equal(operationGate.isCurrent(fastClose), true);

let forbiddenFetches = 0;
const deniedPoller = login.createPoller({
  fetchStatus: async () => { forbiddenFetches += 1; },
  onStatus: () => { throw new Error('权限失效后不得渲染'); },
  onError: () => { throw new Error('权限失效后不得报业务错误'); },
  isAllowed: () => false
});
await deniedPoller.start(7);
assert.equal(forbiddenFetches, 0);
assert.equal(deniedPoller.active(), false);

const failingPoller = login.createPoller({
  fetchStatus: async () => { throw new Error('失败'); },
  onStatus: () => {},
  onError: () => { throw new Error('错误处理也失败'); }
});
await assert.rejects(failingPoller.start(7), /错误处理也失败/);
assert.equal(failingPoller.active(), false);

const scheduled = [];
const seen = [];
let responses = [{status: 'LOGIN_REQUIRED'}, {status: 'ONLINE'}];
const poller = login.createPoller({
  fetchStatus: async storeId => ({store_id: storeId, ...responses.shift()}),
  onStatus: value => seen.push(value),
  onError: error => { throw error; },
  setTimer: callback => { scheduled.push(callback); return callback; },
  clearTimer: callback => { const index = scheduled.indexOf(callback); if (index >= 0) scheduled.splice(index, 1); },
  intervalMs: 1
});
await poller.start(7);
assert.equal(scheduled.length, 1);
await scheduled.shift()();
assert.deepEqual(seen.map(value => value.status), ['LOGIN_REQUIRED', 'ONLINE']);
assert.equal(poller.active(), false);

let resolveOld;
const crossStore = [];
const crossPoller = login.createPoller({
  fetchStatus: storeId => storeId === 1 ? new Promise(resolve => { resolveOld = resolve; }) : Promise.resolve({store_id: 2, status: 'ONLINE'}),
  onStatus: value => crossStore.push(value.store_id),
  onError: error => { throw error; },
  setTimer: () => 1,
  clearTimer: () => {}
});
const oldRequest = crossPoller.start(1);
await crossPoller.start(2);
resolveOld({store_id: 1, status: 'ONLINE'});
await oldRequest;
assert.deepEqual(crossStore, [2]);
"""
    subprocess.run(
        ["node", "-e", f"(async()=>{{{script}}})().catch(error=>{{console.error(error);process.exit(1)}})"],
        cwd=ROOT,
        check=True,
    )


def test_store_page_exposes_owner_only_controls_without_secret_persistence():
    page = (FRONTEND / "stores.html").read_text(encoding="utf-8")
    module = (FRONTEND / "r297-owner-login.js").read_text(encoding="utf-8")
    dashboard = (FRONTEND / "jd-dashboard.html").read_text(encoding="utf-8")
    combined = page + module

    assert 'src="/r297-owner-login.js"' in page
    assert "R297OwnerLogin.isOwner(currentUser)" in page
    assert "if(!store.active)return" in page
    assert 'class="secondary" disabled' in page
    assert '<button class="danger"${busy}' in page
    assert page.count("if(loginBusy.has(id))return") == 2
    assert "ownerLoginClient.status(id)" in page
    assert "isAllowed:()=>R297OwnerLogin.isOwner(currentUser)&&document.getElementById('stores')!==null" in page
    assert "addEventListener('pagehide',stopLoginPolling)" in page
    for label in ("京东登录", "重新验证", "打开受控验证窗口", "关闭会话"):
        assert label in page
    assert "R297StoreView.loadStoreDirectory(api)" in page
    assert "/api/stores" not in page
    assert "/api/stores" not in dashboard
    assert "/internal/jd-browser/" not in combined
    assert "session_id" not in combined
    assert "localStorage" not in module
    assert "sessionStorage" not in module
    assert "console." not in module
    assert "ticket=" not in combined
    assert "URLSearchParams" not in module
    assert "云端登录服务暂不可用" in page
    assert "mock" not in combined.lower()
