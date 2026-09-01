(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.R297StoreView = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  const PLATFORM_LABELS = Object.freeze({
    jd: '京东', tmall: '天猫', taobao: '淘宝', pdd: '拼多多', douyin: '抖音', tiktok: 'TikTok'
  });

  function storeStatus(store) {
    const status = String(store.sync_status || store.login_status || 'OFFLINE').toUpperCase();
    const reason = String(store.reason_code || store.login_reason || '').toUpperCase();
    if (store.active === false || store.sync_enabled === false || status === 'PAUSED') return { key: 'paused', label: '已暂停', tone: 'muted' };
    if (['LOGIN_EXPIRED', 'LOGIN_REQUIRED', 'AUTHORIZATION_REVOKED'].some(value => reason.includes(value))) return { key: 'expired', label: '登录失效', tone: 'bad' };
    if (['CAPTCHA', 'SMS_REQUIRED', 'QR_REQUIRED'].some(value => reason.includes(value))) return { key: 'captcha', label: '需要验证码', tone: 'warn' };
    if (reason.includes('RISK')) return { key: 'risk', label: '风控待处理', tone: 'warn' };
    if (status === 'ERROR' || status === 'HUMAN_ACTION_REQUIRED') return { key: 'error', label: '同步异常', tone: 'bad' };
    if (['IDLE', 'SYNCING', 'SESSION_STOPPED'].includes(status)) return { key: 'syncing', label: '自动同步中', tone: 'good' };
    if (status === 'ONLINE') return { key: 'online', label: '已登录', tone: 'good' };
    return { key: 'offline', label: '未连接', tone: 'muted' };
  }

  function mergeStores(directory, dashboardStores) {
    const metrics = new Map((dashboardStores || []).map(store => [String(store.store_id), store]));
    return (directory || []).map(store => {
      const runtime = metrics.get(String(store.id)) || {};
      return {
        ...store,
        ...runtime,
        id: store.id,
        store_id: store.id,
        platform: store.platform,
        active: store.active,
        subject_id: store.subject_id,
        subject_code: store.subject_code,
        subject_name: store.subject_name,
        login_status: store.login_status,
        login_reason: store.login_reason || runtime.reason_code,
        sync_status: runtime.sync_status || store.login_status,
        summary: runtime.summary || {},
        datasets: runtime.datasets || {}
      };
    });
  }

  function filterStores(stores, filters = {}) {
    const query = String(filters.query || '').trim().toLowerCase();
    return (stores || []).filter(store => {
      const status = storeStatus(store);
      const haystack = [
        store.store_name, store.store_code, store.subject_name, store.subject_code, store.subject_id,
        store.login_status, store.login_reason, store.sync_status, store.reason_code, status.label
      ].join(' ').toLowerCase();
      return (!filters.platform || store.platform === filters.platform)
        && (!filters.enabled || (filters.enabled === 'active' ? store.active !== false : store.active === false))
        && (!filters.login || status.key === filters.login)
        && (!query || haystack.includes(query));
    });
  }

  function createLatestRequestGate() {
    let latest = 0;
    return Object.freeze({ begin: () => ++latest, isCurrent: token => token === latest });
  }

  return Object.freeze({ PLATFORM_LABELS, storeStatus, mergeStores, filterStores, createLatestRequestGate });
});
