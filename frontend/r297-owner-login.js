(function (root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.R297OwnerLogin = api;
})(typeof globalThis === 'object' ? globalThis : this, function (root) {
  const STATUS_LABELS = Object.freeze({
    UNKNOWN: '尚未查询',
    OFFLINE: '未登录',
    ACTIVE: '等待扫码',
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
  const SERVER_SESSION_STATUSES = new Set(['LOGIN_REQUIRED', 'ACTIVE', 'REVOKED']);
  const SESSION_TTL_MAX_SECONDS = 600;
  const TICKET_TTL_MAX_SECONDS = 120;
  const PAGE_CLOSE_OBSERVER_CONTRACT = Object.freeze({
    binding: '__tiantongR297AuthenticatedObserver',
    raw_fields: Object.freeze(['event', 'observed_at', 'store_id', 'release_sha']),
    observer_fields: Object.freeze(['authenticated_observer', 'scheduler_continues'])
  });

  function storeId(value) {
    if (typeof value === 'boolean') throw new Error('店铺标识无效');
    const parsed = Number(value);
    if (!Number.isInteger(parsed) || parsed <= 0) throw new Error('店铺标识无效');
    return parsed;
  }

  function sessionPath(value) {
    return `/api/jd-workbench/stores/${storeId(value)}/login-session`;
  }

  function exactKeys(value, keys) {
    return Boolean(value && typeof value === 'object' && !Array.isArray(value) &&
      Object.keys(value).sort().join('\0') === [...keys].sort().join('\0'));
  }

  function strictTtl(value, maximum) {
    return Number.isInteger(value) && value > 0 && value <= maximum;
  }

  async function responseError(response) {
    let detail = '';
    try { detail = (await response.json()).detail; } catch (_error) {}
    const unexpectedSuccess = response && response.status >= 200 && response.status < 300;
    const error = new Error(unexpectedSuccess ? '云端登录HTTP状态无效' : typeof detail === 'string' && detail ? detail : '云端登录请求失败，请稍后重试');
    error.status = response && response.status;
    return error;
  }

  async function requiredJson(response, expectedStatus) {
    if (!response || response.status !== expectedStatus) throw await responseError(response);
    try { return await response.json(); } catch (_error) { throw new Error('云端登录响应无效'); }
  }

  function createClient(request) {
    if (typeof request !== 'function') throw new Error('登录接口不可用');
    const emptyPost = Object.freeze({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    const send = async (path, options) => { try { return await request(path, options); } catch (_error) { throw new Error('网络连接失败，请稍后重试'); } };
    return Object.freeze({
      create: async (value, signal) => {
        const id = storeId(value), data = await requiredJson(await send(sessionPath(id), signal ? { ...emptyPost, signal } : emptyPost), 200);
        if (!exactKeys(data, ['store_id', 'status', 'expires_in']) || data.status !== 'LOGIN_REQUIRED' || !strictTtl(data.expires_in, SESSION_TTL_MAX_SECONDS)) throw new Error('登录会话响应无效');
        return sessionState(id, data);
      },
      status: async (value, signal) => {
        const id = storeId(value), options = signal ? { signal } : undefined;
        const data = await requiredJson(await send(sessionPath(id), options), 200);
        if (!exactKeys(data, ['store_id', 'status'])) throw new Error('登录状态响应无效');
        return sessionState(id, data);
      },
      ticket: async (value, signal) => {
        const id = storeId(value), options = signal ? { ...emptyPost, signal } : emptyPost;
        const data = await requiredJson(await send(`/api/jd-workbench/stores/${id}/login-ticket`, options), 200);
        if (!exactKeys(data, ['ticket', 'expires_in']) || typeof data.ticket !== 'string' || !data.ticket.trim() || !strictTtl(data.expires_in, TICKET_TTL_MAX_SECONDS)) throw new Error('登录凭证响应无效');
        return Object.freeze({ ticket: data.ticket, expires_in: data.expires_in });
      },
      close: async value => {
        const id = storeId(value), response = await send(sessionPath(id), { method: 'DELETE' });
        if (response && response.status === 204) return Object.freeze({ store_id: id, status: 'REVOKED' });
        const data = await requiredJson(response, 200);
        if (!exactKeys(data, ['ok', 'store_id', 'status']) || data.ok !== true || !Number.isInteger(data.store_id) || data.store_id !== id || data.status !== 'REVOKED') throw new Error('登录会话销毁响应无效');
        return Object.freeze({ store_id: id, status: 'REVOKED' });
      }
    });
  }

  async function redeemTicket(request, value, response, signal) {
    if (typeof request !== 'function') throw new Error('受控登录服务不可用');
    const id = storeId(value);
    const ticket = response && response.ticket;
    if (!exactKeys(response, ['ticket', 'expires_in']) || typeof ticket !== 'string' || !ticket.trim() || !strictTtl(response.expires_in, TICKET_TTL_MAX_SECONDS)) {
      throw new Error('登录凭证响应无效');
    }
    let result;
    try {
      result = await request(`/jd-browser/novnc/${id}/exchange`, {
        method: 'POST', credentials: 'include', cache: 'no-store', referrerPolicy: 'no-referrer',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ticket }), signal
      });
    } catch (_error) { throw new Error('网络连接失败，请稍后重试'); }
    if (!result || result.status !== 204) {
      const error = new Error(result && result.status === 403 ? '无权打开该店铺登录窗口' : result && result.status === 409 ? '登录会话状态冲突，请刷新后重试' : result && result.status >= 200 && result.status < 300 ? '登录凭证兑换响应无效' : '登录凭证已失效或不适用于该店铺，请重新申请');
      error.status = result && result.status;
      throw error;
    }
    return `/jd-browser/novnc/${id}/vnc.html`;
  }

  async function openViewer({ client, request, storeId: value, signal, isActive }) {
    const id = storeId(value);
    const ticket = await client.ticket(id, signal);
    if (signal.aborted || !isActive()) return null;
    return redeemTicket(request, id, ticket, signal);
  }

  function isOwner(user) {
    return Boolean(user && user.role_code === 'owner');
  }

  async function runPreflight({ request, user, store, client, signal, location = root.location, secureContext = root.isSecureContext }) {
    if (!location || location.protocol !== 'https:') throw new Error('真实联调必须使用Backend HTTPS地址');
    if (secureContext !== true) throw new Error('TLS证书未受浏览器信任');
    if (!isOwner(user)) { const error = new Error('仅Owner可执行云端登录预检'); error.status = 403; throw error; }
    if (!store || store.platform !== 'jd') throw new Error('仅真实京东店铺可执行云端登录预检');
    if (store.active !== true) throw new Error('停用店铺不能执行云端登录预检');
    const id = storeId(store.id);
    let healthResponse;
    try { healthResponse = await request('/api/health', { credentials: 'include', cache: 'no-store', signal }); }
    catch (_error) { throw new Error('Backend HTTPS连接失败'); }
    if (!healthResponse || healthResponse.status !== 200) throw new Error('Backend健康检查失败');
    let health;
    try { health = await healthResponse.json(); } catch (_error) { throw new Error('Backend健康响应无效'); }
    if (!health || health.status !== 'running' || health.database !== true || health.redis !== true) throw new Error('Backend依赖未就绪');
    try { await client.status(id, signal); }
    catch (error) {
      const failure = new Error(error && error.status === 403 ? '店铺授权预检失败' : 'Runtime健康检查失败');
      failure.status = error && error.status;
      throw failure;
    }
    return Object.freeze({
      backend_https: true, tls_trusted: true, owner_identity: true,
      store_authorized: true, runtime_healthy: true, store_id: id
    });
  }

  function verifyNoVncWebSocket({ WebSocketCtor = root.WebSocket, location = root.location, storeId: value, signal, setTimer = setTimeout, clearTimer = clearTimeout, timeoutMs = 5000 }) {
    const id = storeId(value);
    if (!location || location.protocol !== 'https:' || !location.host || typeof WebSocketCtor !== 'function') {
      return Promise.reject(new Error('noVNC WebSocket安全连接不可用'));
    }
    if (signal && signal.aborted) return Promise.reject(new Error('noVNC WebSocket连接已取消'));
    return new Promise((resolve, reject) => {
      let settled = false;
      const socket = new WebSocketCtor(`wss://${location.host}/jd-browser/novnc/${id}/websockify`, 'binary');
      const timer = setTimer(() => finish(new Error('noVNC WebSocket连接超时')), timeoutMs);
      const abort = () => finish(new Error('noVNC WebSocket连接已取消'));
      function finish(error) {
        if (settled) return;
        settled = true;
        clearTimer(timer);
        if (signal) signal.removeEventListener('abort', abort);
        try { socket.close(); } catch (_error) {}
        if (error) reject(error);
        else resolve(Object.freeze({ store_id: id, websocket: 'connected' }));
      }
      socket.onopen = () => finish();
      socket.onerror = () => finish(new Error('noVNC WebSocket连接失败'));
      socket.onclose = () => finish(new Error('noVNC WebSocket连接提前关闭'));
      if (signal) {
        if (signal.aborted) return abort();
        signal.addEventListener('abort', abort, { once: true });
      }
    });
  }

  function statusView(value) {
    if (value === undefined || value === null || value === '') return Object.freeze({ code: 'UNKNOWN', label: STATUS_LABELS.UNKNOWN, terminal: false });
    const code = String(value).toUpperCase();
    if (!STATUS_LABELS[code]) return Object.freeze({ code: 'INVALID', label: '登录状态异常', terminal: true });
    return Object.freeze({ code, label: STATUS_LABELS[code], terminal: TERMINAL_STATUSES.has(code) });
  }

  function sessionState(expectedStoreId, response) {
    const expected = storeId(expectedStoreId);
    if (!response || !Number.isInteger(response.store_id) || response.store_id !== expected) {
      throw new Error('登录会话店铺作用域不匹配');
    }
    if (typeof response.status !== 'string' || !SERVER_SESSION_STATUSES.has(response.status)) throw new Error('登录状态响应无效');
    const state = { store_id: expected, status: response.status };
    if ('expires_in' in response) {
      if (!strictTtl(response.expires_in, SESSION_TTL_MAX_SECONDS)) throw new Error('登录会话有效期响应无效');
      state.expires_in = response.expires_in;
    }
    return Object.freeze(state);
  }

  function errorMessage(error) {
    if (error && error.status === 403) return '无权管理该店铺的云端登录会话';
    if (error && error.status === 404) return '店铺或登录会话不存在';
    if (error && error.status === 503) return '云端登录服务暂不可用';
    return error && error.message || '云端登录请求失败，请稍后重试';
  }

  function createPoller({ fetchStatus, onStatus, onError, isAllowed = () => true, setTimer = setTimeout, clearTimer = clearTimeout, AbortControllerCtor = root.AbortController, intervalMs = 3000 }) {
    let generation = 0;
    let timer = null;
    let running = false;
    let requestController = null;

    function stop() {
      generation += 1;
      running = false;
      if (timer !== null) clearTimer(timer);
      timer = null;
      if (requestController) requestController.abort();
      requestController = null;
    }

    async function poll(token, id) {
      if (!running || token !== generation || !isAllowed()) return stop();
      const controller = new AbortControllerCtor();
      requestController = controller;
      try {
        const result = await fetchStatus(id, controller.signal);
        if (!running || token !== generation || !isAllowed()) return stop();
        onStatus(result);
        if (statusView(result && result.status).terminal) return stop();
        timer = setTimer(() => poll(token, id), intervalMs);
      } catch (error) {
        if (!running || token !== generation) return;
        try { onError(error); } finally { stop(); }
      } finally {
        if (requestController === controller) requestController = null;
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

  function createWindowRegistry() {
    const windows = new Map();
    return Object.freeze({
      track: (value, viewer) => { const id = storeId(value); windows.set(id, viewer); },
      focus: value => { const viewer = windows.get(storeId(value)); if (!viewer || viewer.closed) { windows.delete(storeId(value)); return false; } viewer.focus(); return true; },
      close: value => { const id = storeId(value), viewer = windows.get(id); if (viewer && !viewer.closed) viewer.close(); windows.delete(id); },
      closeAll: () => { windows.forEach(viewer => { if (viewer && !viewer.closed) viewer.close(); }); windows.clear(); },
      ids: () => Object.freeze([...windows.keys()]),
      size: () => windows.size
    });
  }

  function createPageCloseReporter({ observer = root[PAGE_CLOSE_OBSERVER_CONTRACT.binding], now = () => new Date().toISOString(), getReleaseSha = () => '' } = {}) {
    return Object.freeze({
      report: (event, storeIds) => {
        if (typeof root.PageTransitionEvent !== 'function' || !(event instanceof root.PageTransitionEvent) || event.type !== 'pagehide' || event.isTrusted !== true || typeof observer !== 'function') return false;
        let releaseSha;
        try { releaseSha = String(getReleaseSha() || '').trim().toLowerCase(); } catch (_) { return false; }
        if (!/^[0-9a-f]{40}$/.test(releaseSha)) return false;
        const ids = [...new Set((storeIds || []).map(storeId))];
        ids.forEach(id => {
          try {
            const result = observer(JSON.stringify({ event: 'web_page_close', observed_at: now(), store_id: id, release_sha: releaseSha }));
            if (result && typeof result.catch === 'function') result.catch(() => {});
          } catch (_) {}
        });
        return ids.length > 0;
      }
    });
  }

  function closePageResources({ operationGates, abortControllers, busy, pollers, windows }) {
    operationGates.forEach(gate => gate.begin());
    abortControllers.forEach(controller => controller.abort());
    abortControllers.clear();
    busy.clear();
    pollers.forEach(poller => poller.stop());
    windows.closeAll();
  }

  return Object.freeze({ PAGE_CLOSE_OBSERVER_CONTRACT, closePageResources, createClient, createOperationGate, createPageCloseReporter, createPoller, createWindowRegistry, errorMessage, isOwner, openViewer, redeemTicket, runPreflight, sessionState, statusView, verifyNoVncWebSocket });
});
