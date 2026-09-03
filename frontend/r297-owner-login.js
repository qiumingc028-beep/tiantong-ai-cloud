(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.R297OwnerLogin = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  const STATUS_LABELS = Object.freeze({
    UNKNOWN: '尚未查询',
    OFFLINE: '未登录',
    LOGIN_REQUIRED: '等待扫码',
    QR_REQUIRED: '等待扫码',
    CAPTCHA: '验证码',
    CAPTCHA_REQUIRED: '验证码',
    SMS_REQUIRED: '短信验证',
    RISK_CONTROL: '风控',
    ONLINE: '登录成功',
    LOGIN_SUCCESS: '登录成功',
    LOGIN_EXPIRED: '登录失效',
    TICKET_EXPIRED: 'ticket过期',
    AUTHORIZATION_REVOKED: '授权撤销',
    REVOKED: '授权撤销',
    SESSION_DESTROYED: '会话销毁',
    DESTROYED: '会话销毁',
    RUNTIME_UNAVAILABLE: '云端登录服务暂不可用',
    SYNC_RECOVERED: '自动同步恢复',
    SYNCING: '自动同步恢复',
    ERROR: '同步失败',
    SYNC_FAILED: '同步失败'
  });
  const TERMINAL_STATUSES = new Set([
    'ONLINE', 'LOGIN_SUCCESS', 'LOGIN_EXPIRED', 'TICKET_EXPIRED',
    'AUTHORIZATION_REVOKED', 'REVOKED', 'SESSION_DESTROYED', 'DESTROYED',
    'RUNTIME_UNAVAILABLE', 'SYNC_RECOVERED', 'ERROR', 'SYNC_FAILED'
  ]);

  function storeId(value) {
    const parsed = Number(value);
    if (!Number.isInteger(parsed) || parsed <= 0) throw new Error('店铺标识无效');
    return parsed;
  }

  function sessionPath(value) {
    return `/api/jd-workbench/stores/${storeId(value)}/login-session`;
  }

  function createClient(api) {
    if (typeof api !== 'function') throw new Error('登录接口不可用');
    return Object.freeze({
      create: value => api(sessionPath(value), { method: 'POST' }),
      status: value => api(sessionPath(value)),
      ticket: value => api(`/api/jd-workbench/stores/${storeId(value)}/login-ticket`, { method: 'POST' }),
      close: value => api(sessionPath(value), { method: 'DELETE' })
    });
  }

  function isOwner(user) {
    return Boolean(user && user.role_code === 'owner');
  }

  function statusView(value) {
    const code = String(value || 'UNKNOWN').toUpperCase();
    return Object.freeze({ code, label: STATUS_LABELS[code] || '登录状态未知', terminal: TERMINAL_STATUSES.has(code) });
  }

  function sessionState(expectedStoreId, response) {
    const expected = storeId(expectedStoreId);
    if (!response || Number(response.store_id) !== expected || typeof response.status !== 'string') {
      throw new Error('登录会话店铺作用域不匹配');
    }
    const state = { store_id: expected, status: statusView(response.status).code };
    if (Number.isFinite(Number(response.expires_in)) && Number(response.expires_in) >= 0) state.expires_in = Number(response.expires_in);
    return Object.freeze(state);
  }

  function errorMessage(error) {
    if (error && error.status === 403) return '无权管理该店铺的云端登录会话';
    if (error && error.status === 404) return '店铺或登录会话不存在';
    if (error && error.status === 503) return '云端登录服务暂不可用';
    return error && error.message || '云端登录请求失败，请稍后重试';
  }

  function createPoller({ fetchStatus, onStatus, onError, isAllowed = () => true, setTimer = setTimeout, clearTimer = clearTimeout, intervalMs = 3000 }) {
    let generation = 0;
    let timer = null;
    let running = false;

    function stop() {
      generation += 1;
      running = false;
      if (timer !== null) clearTimer(timer);
      timer = null;
    }

    async function poll(token, id) {
      if (!running || token !== generation || !isAllowed()) return stop();
      try {
        const result = await fetchStatus(id);
        if (!running || token !== generation || !isAllowed()) return stop();
        onStatus(result);
        if (statusView(result && result.status).terminal) return stop();
        timer = setTimer(() => poll(token, id), intervalMs);
      } catch (error) {
        if (!running || token !== generation) return;
        try { onError(error); } finally { stop(); }
      }
    }

    function start(value) {
      stop();
      const id = storeId(value);
      running = true;
      const token = generation;
      return poll(token, id);
    }

    return Object.freeze({ start, stop, active: () => running });
  }

  function createOperationGate() {
    let generation = 0;
    return Object.freeze({ begin: () => ++generation, isCurrent: token => token === generation });
  }

  return Object.freeze({ createClient, createOperationGate, createPoller, errorMessage, isOwner, sessionState, statusView });
});
