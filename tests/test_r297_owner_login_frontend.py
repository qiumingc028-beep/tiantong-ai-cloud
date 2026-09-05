import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_owner_login_client_uses_only_store_scoped_backend_routes():
    script = r"""
const assert = require('node:assert/strict');
const login = require('./frontend/r297-owner-login.js');

const calls = [];
const responses = [
  [200, {store_id: 7, status: 'LOGIN_REQUIRED', expires_in: 600}],
  [200, {store_id: 7, status: 'ACTIVE'}],
  [200, {ticket: 'one-time-secret', expires_in: 60}],
  [200, {ok: true, store_id: 7, status: 'REVOKED'}]
];
const client = login.createClient(async (path, options = {}) => {
  calls.push({path, options});
  const [status, body] = responses.shift();
  return {status, json: async () => body};
});
assert.deepEqual(await client.create(7), {store_id: 7, status: 'LOGIN_REQUIRED', expires_in: 600});
assert.deepEqual(await client.status(7), {store_id: 7, status: 'ACTIVE'});
assert.deepEqual(await client.ticket(7), {ticket: 'one-time-secret', expires_in: 60});
assert.deepEqual(await client.close(7), {store_id: 7, status: 'REVOKED'});
assert.deepEqual(calls.map(call => [call.path, call.options.method || 'GET']), [
  ['/api/jd-workbench/stores/7/login-session', 'POST'],
  ['/api/jd-workbench/stores/7/login-session', 'GET'],
  ['/api/jd-workbench/stores/7/login-ticket', 'POST'],
  ['/api/jd-workbench/stores/7/login-session', 'DELETE']
]);
assert.deepEqual(calls.filter(call => call.options.method === 'POST').map(call => JSON.parse(call.options.body)), [{}, {}]);
assert.ok(calls.filter(call => !call.options.method || call.options.method === 'DELETE').every(call => !('body' in call.options)));
await assert.rejects(client.create('session-from-user'), /店铺标识无效/);
await assert.rejects(client.create(true), /店铺标识无效/);
assert.equal(login.isOwner({role_code: 'owner'}), true);
assert.equal(login.isOwner({role_code: 'admin'}), false);
assert.equal(login.isOwner({role_code: 'operator'}), false);
assert.deepEqual(login.sessionState(7, {store_id: 7, status: 'LOGIN_REQUIRED', expires_in: 600}), {store_id: 7, status: 'LOGIN_REQUIRED', expires_in: 600});
assert.throws(() => login.sessionState(7, {store_id: 8, status: 'ONLINE'}), /店铺作用域不匹配/);
assert.throws(() => login.sessionState(7, {store_id: '7', status: 'ACTIVE'}), /店铺作用域不匹配/);
assert.throws(() => login.sessionState(7, {store_id: 7, status: 'UNKNOWN_FROM_RUNTIME'}), /登录状态响应无效/);
assert.throws(() => login.sessionState(7, {store_id: 7, status: 'active'}), /登录状态响应无效/);

const requestOnce = (status, body) => async () => ({status, json: async () => body});
await assert.rejects(login.createClient(requestOnce(201, {})).create(7), /HTTP状态无效/);
for (const expires_in of [true, 0, -1, 121, 1.5]) {
  await assert.rejects(login.createClient(requestOnce(200, {ticket: 'x', expires_in})).ticket(7), /登录凭证响应无效/);
}
assert.deepEqual(await login.createClient(requestOnce(200, {ticket: 'x', expires_in: 120})).ticket(7), {ticket: 'x', expires_in: 120});
for (const expires_in of [true, 0, -1, 601, 1.5]) {
  await assert.rejects(login.createClient(requestOnce(200, {store_id: 7, status: 'LOGIN_REQUIRED', expires_in})).create(7), /登录会话响应无效/);
}
await assert.rejects(login.createClient(requestOnce(200, {session_id: 'legacy', store_id: 7, status: 'LOGIN_REQUIRED', expires_in: 600})).create(7), /登录会话响应无效/);
await assert.rejects(login.createClient(requestOnce(200, {ticket: 'x', expires_in: 60, extra: true})).ticket(7), /登录凭证响应无效/);
await assert.rejects(login.createClient(requestOnce(202, {})).close(7), /HTTP状态无效/);
await assert.rejects(login.createClient(requestOnce(200, {ok: false, store_id: 7, status: 'REVOKED'})).close(7), /销毁响应无效/);
assert.deepEqual(await login.createClient(requestOnce(204, null)).close(7), {store_id: 7, status: 'REVOKED'});
await assert.rejects(login.createClient(async () => { throw new TypeError('Failed to fetch'); }).status(7), /网络连接失败，请稍后重试/);

const exchanges = [];
const viewerPath = await login.redeemTicket(async (path, options) => {
  exchanges.push({path, options});
  return {ok: true, status: 204};
}, 7, {ticket: 'one-time-secret', expires_in: 60});
assert.equal(viewerPath, '/jd-browser/novnc/7/vnc.html');
assert.equal(exchanges[0].path, '/jd-browser/novnc/7/exchange');
assert.equal(exchanges[0].options.method, 'POST');
assert.equal(exchanges[0].options.credentials, 'include');
assert.equal(exchanges[0].options.referrerPolicy, 'no-referrer');
assert.deepEqual(JSON.parse(exchanges[0].options.body), {ticket: 'one-time-secret'});
assert.ok(!exchanges[0].path.includes('?'));

for (const status of [400, 401, 403, 409, 410]) {
  await assert.rejects(
    login.redeemTicket(async () => ({ok: false, status}), 7, {ticket: 'rejected', expires_in: 1}),
    /登录凭证|无权|冲突/
  );
}
await assert.rejects(
  login.redeemTicket(async () => ({ok: true, status: 200}), 7, {ticket: 'wrong-status', expires_in: 60}),
  /兑换响应无效/
);
await assert.rejects(
  login.redeemTicket(async () => { throw new TypeError('Failed to fetch'); }, 7, {ticket: 'network', expires_in: 60}),
  /网络连接失败，请稍后重试/
);
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
  OFFLINE: '未登录', ACTIVE: '等待扫码', LOGIN_REQUIRED: '等待扫码', CAPTCHA_REQUIRED: '验证码',
  SMS_REQUIRED: '短信验证', RISK_CONTROL: '风控', ONLINE: '登录成功',
  LOGIN_EXPIRED: '登录失效', TICKET_EXPIRED: 'ticket过期',
  AUTHORIZATION_REVOKED: '授权撤销', REVOKED: '授权撤销',
  SESSION_DESTROYED: '会话销毁', RUNTIME_UNAVAILABLE: '云端登录服务暂不可用',
  SYNC_RECOVERED: '自动同步恢复', ERROR: '同步失败'
};
for (const [status, label] of Object.entries(labels)) assert.equal(login.statusView(status).label, label);
assert.equal(login.statusView('UNKNOWN_FROM_RUNTIME').label, '登录状态异常');
assert.equal(login.statusView('UNKNOWN_FROM_RUNTIME').terminal, true);
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

let focused = 0;
let closed = 0;
const viewer = {closed: false, focus: () => { focused += 1; }, close: () => { closed += 1; viewer.closed = true; }};
const windows = login.createWindowRegistry();
windows.track(7, viewer);
assert.equal(windows.focus(7), true);
assert.equal(focused, 1);
assert.equal(windows.focus(8), false);
let pollerClosed = 0;
const busy = new Set([7]);
const pendingGate = login.createOperationGate();
const pendingToken = pendingGate.begin();
const abortControllers = new Map([[7, new AbortController()]]);
login.closePageResources({
  operationGates: new Map([[7, pendingGate]]),
  abortControllers,
  busy,
  pollers: new Map([[7, {stop: () => { pollerClosed += 1; }}]]),
  windows
});
assert.equal(pendingGate.isCurrent(pendingToken), false);
assert.equal(pollerClosed, 1);
assert.equal(closed, 1);
assert.equal(busy.size, 0);
assert.equal(abortControllers.size, 0);
assert.equal(windows.size(), 0);

let resolveTicket;
let exchangeCalls = 0;
const lateGate = login.createOperationGate();
const lateToken = lateGate.begin();
const lateController = new AbortController();
const lateWindows = login.createWindowRegistry();
lateWindows.track(7, {closed: false, focus() {}, close() { this.closed = true; }});
const lateOpen = login.openViewer({
  client: {ticket: () => new Promise(resolve => { resolveTicket = resolve; })},
  request: async () => { exchangeCalls += 1; return {status: 204}; },
  storeId: 7,
  signal: lateController.signal,
  isActive: () => lateGate.isCurrent(lateToken)
});
login.closePageResources({
  operationGates: new Map([[7, lateGate]]),
  abortControllers: new Map([[7, lateController]]),
  busy: new Set([7]), pollers: new Map(), windows: lateWindows
});
resolveTicket({ticket: 'late-secret', expires_in: 60});
assert.equal(await lateOpen, null);
assert.equal(exchangeCalls, 0);
assert.equal(lateWindows.size(), 0);

const emitted = [];
const reporter = login.createPageCloseReporter({observer: payload => emitted.push(JSON.parse(payload)), now: () => '2026-09-04T00:00:00.000Z'});
assert.equal(reporter.report({type: 'pagehide', isTrusted: false}, [7]), false);
assert.deepEqual(emitted, []);
assert.deepEqual(login.PAGE_CLOSE_OBSERVER_CONTRACT, {
  binding: '__tiantongR297AuthenticatedObserver',
  raw_fields: ['event', 'observed_at', 'store_id', 'release_sha'],
  observer_fields: ['authenticated_observer', 'scheduler_continues']
});
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
    assert "store.platform!=='jd'" in page
    assert "if(!store.active)return" in page
    assert "R297OwnerLogin.openViewer(" in page
    assert "window.open('about:blank'" in page
    assert "viewerWindow.location.replace(viewerPath)" in page
    assert "if(loginWindows.focus(id))return" in page
    assert "loginWindows.track(id,viewerWindow)" in page
    assert page.index("loginWindows.track(id,viewerWindow)") < page.index("R297OwnerLogin.openViewer(")
    assert '<button class="danger"${busy}' in page
    assert page.count("loginBusy.has(id)") == 3
    assert "ownerLoginClient.status(id)" in page
    assert page.count("ownerLoginClient.status(") == 1
    assert "loadOwnerLoginStates" not in page
    assert "isAllowed:()=>R297OwnerLogin.isOwner(currentUser)&&document.getElementById('stores')!==null" in page
    assert "addEventListener('pagehide',stopLoginPolling)" in page
    assert "R297OwnerLogin.closePageResources(" in page
    assert "event instanceof root.PageTransitionEvent" in module
    assert "getReleaseSha:()=>releaseSha" in page
    assert "h.release.commit" in page
    for label in ("京东登录", "重新验证", "打开受控验证窗口", "关闭会话"):
        assert label in page
    assert "R297StoreView.loadStoreDirectory(api)" in page
    assert "/api/stores" not in page
    assert "/api/stores" not in dashboard
    assert "/internal/jd-browser/" not in combined
    assert "session_id" not in combined
    assert "scheduler_continues:true" not in combined
    assert "authenticated_observer:true" not in combined
    assert "localStorage" not in module
    assert "sessionStorage" not in module
    assert "console." not in module
    assert "ticket=" not in combined
    assert "URLSearchParams" not in module
    assert "云端登录服务暂不可用" in page
    assert "mock" not in combined.lower()
