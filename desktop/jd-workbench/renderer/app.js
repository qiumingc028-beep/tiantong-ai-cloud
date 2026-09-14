'use strict';

const api = window.tiantongWorkbench;
const elements = Object.freeze({
  storeCount: document.getElementById('storeCount'),
  storeSearch: document.getElementById('storeSearch'),
  storeList: document.getElementById('storeList'),
  pairingForm: document.getElementById('pairingForm'),
  deviceName: document.getElementById('deviceName'),
  pairingCode: document.getElementById('pairingCode'),
  refreshStores: document.getElementById('refreshStores'),
  syncNow: document.getElementById('syncNow'),
  browseMode: document.getElementById('browseMode'),
  topnav: document.querySelector('.topnav'),
  storeTabs: document.querySelector('.tabs'),
  formMessage: document.getElementById('formMessage'),
  emptyStage: document.getElementById('emptyStage'),
  openDiagnostic: document.getElementById('openDiagnostic'),
  activeStore: document.getElementById('activeStore'),
  cloudStatus: document.getElementById('cloudStatus'),
  automaticSyncStatus: document.getElementById('automaticSyncStatus'),
  businessWrites: document.getElementById('businessWrites'),
  blockedWrites: document.getElementById('blockedWrites'),
  workspacePanels: document.getElementById('workspacePanels'),
  managementSummary: document.getElementById('managementSummary'),
  managementStores: document.getElementById('managementStores'),
  panelRefreshStores: document.getElementById('panelRefreshStores'),
  syncCheck: document.getElementById('syncCheck'),
  autoSyncBanner: document.getElementById('autoSyncBanner'),
  autoSyncHeadline: document.getElementById('autoSyncHeadline'),
  autoSyncDetail: document.getElementById('autoSyncDetail'),
  recognitionBanner: document.getElementById('recognitionBanner'),
  recognitionHeadline: document.getElementById('recognitionHeadline'),
  recognitionDetail: document.getElementById('recognitionDetail'),
  recognitionState: document.getElementById('recognitionState'),
  syncDatasets: document.getElementById('syncDatasets'),
  alertSummary: document.getElementById('alertSummary'),
  alertList: document.getElementById('alertList'),
  appToast: document.getElementById('appToast'),
  humanCard: document.getElementById('humanCard'),
  humanReason: document.getElementById('humanReason')
});

let latest = null;
let storeFilter = 'all';
let toastTimer = null;

const DATASETS = Object.freeze([
  ['sales', '销售数据', '销售额、客户数、访客和浏览量'],
  ['orders', '订单数据', '成交单量与待处理订单'],
  ['inventory', '库存数据', 'SKU库存与缺货预警'],
  ['refunds', '退款数据', '退款金额与待处理售后'],
  ['promotion', '推广费用', '广告消耗、展现、点击和成本']
]);

const PAGE_TYPE_LABELS = Object.freeze({
  JDM_HOME: '京麦经营首页',
  BUSINESS_INTELLIGENCE: '京东商智',
  ORDERS: '订单页面',
  ORDER_EXPORT: '订单导出页面',
  PRODUCTS: '商品页面',
  INVENTORY: '库存页面',
  REFUNDS: '售后退款页面',
  PROMOTION: '推广页面',
  JD_PAGE: '京东页面'
});

function showToast(message, tone = 'info') {
  clearTimeout(toastTimer);
  elements.appToast.textContent = message;
  elements.appToast.dataset.tone = tone;
  elements.appToast.classList.remove('hidden');
  toastTimer = setTimeout(() => elements.appToast.classList.add('hidden'), 3600);
}

function statusLabel(store) {
  const labels = {
    NOT_OPENED: '未打开',
    LOADING: '正在打开',
    READY_READ_ONLY: '只读在线',
    SESSION_STOPPED: '自动轮询中',
    HUMAN_ACTION_REQUIRED: '需人工处理'
  };
  return labels[store.status] || '状态未知';
}

function reasonLabel(reason) {
  const labels = {
    LOGIN_REQUIRED: '请由员工手工登录京东',
    CAPTCHA: '发现验证码，请员工手工完成',
    RISK_CONTROL: '触发京东风控，请员工处理',
    LOGIN_EXPIRED: '登录已失效，请重新登录',
    RISK_OR_CAPTCHA: '检测到验证或风控页面',
    AUTH_ROUTE_NOT_AUDITED: '登录路径尚未通过安全审核，已停止',
    UNKNOWN_DOMAIN: '页面请求了未审核域名，已停止加载',
    READ_ONLY_WRITE_BLOCKED: '只读模式已阻止非登录写请求',
    BACKGROUND_CHANNEL_BLOCKED: '只读模式已阻止后台通道',
    DOWNLOAD_BLOCKED: '只读模式不允许下载',
    NEW_WINDOW_BLOCKED: '未知新窗口已阻止',
    PAGE_LOAD_FAILED: '京东页面加载失败',
    REMOTE_RENDERER_STOPPED: '京东页面进程已停止'
  };
  return labels[reason] || '请在中间京东页面完成人工处理';
}

function button(label, className, onClick) {
  const element = document.createElement('button');
  element.type = 'button';
  element.textContent = label;
  element.className = className;
  element.addEventListener('click', onClick);
  return element;
}

function renderOpenDiagnostic(diagnostic) {
  const labels = {
    IDLE: '等待点击店铺“打开”',
    CLICK_SENT: '已收到点击，正在请求打开',
    SELECT_RECEIVED: '主程序已收到打开请求',
    REFRESHING_AUTHORIZATION: '正在刷新店铺授权',
    AUTHORIZATION_READY: '店铺授权正常',
    SESSION_READY: '店铺安全会话正常',
    VIEW_CREATED: '京东窗口已创建',
    VIEW_ATTACHED: '京东窗口已加入工作台',
    LOAD_STARTED: '正在连接京东商家后台',
    LOGIN_PAGE_READY: '京东登录页面已打开',
    STORE_PAGE_READY: '京东店铺页面已打开',
    PAGE_FINISHED: '京东页面加载完成',
    LOAD_COMPLETE: '京东页面加载完成',
    PAGE_LOAD_FAILED: '京东页面加载失败',
    VIEW_REVOKED: '安全规则关闭了京东窗口',
    RENDERER_STOPPED: '京东页面进程已停止',
    OPEN_FAILED: '打开店铺失败'
  };
  const value = diagnostic || { stage: 'IDLE' };
  const details = [labels[value.stage] || value.stage];
  if (value.code) details.push(`代码：${value.code}`);
  if (value.host && value.host !== 'unknown') details.push(`域名：${value.host}`);
  elements.openDiagnostic.classList.toggle(
    'error',
    ['PAGE_LOAD_FAILED', 'VIEW_REVOKED', 'RENDERER_STOPPED', 'OPEN_FAILED'].includes(value.stage)
  );
  elements.openDiagnostic.querySelector('span').textContent = details.join('｜');
}

function renderStores(snapshot) {
  const query = elements.storeSearch.value.trim().toLowerCase();
  const visible = snapshot.stores.filter((store) => (
    store.storeName.toLowerCase().includes(query) &&
    (storeFilter === 'all' || store.status === 'HUMAN_ACTION_REQUIRED')
  ));
  elements.storeList.replaceChildren();
  elements.storeCount.textContent = `${snapshot.stores.length} 家`;

  if (!visible.length) {
    const empty = document.createElement('p');
    empty.className = 'list-empty';
    empty.textContent = snapshot.stores.length ? '没有符合条件的店铺' : '尚未绑定真实店铺';
    elements.storeList.append(empty);
    return;
  }

  for (const store of visible) {
    const card = document.createElement('article');
    card.className = `store-card${store.storeUuid === snapshot.activeStoreUuid ? ' selected' : ''}`;

    const identity = document.createElement('div');
    identity.className = 'store-identity';
    const icon = document.createElement('span');
    icon.className = 'store-icon';
    icon.textContent = 'M';
    const text = document.createElement('div');
    const name = document.createElement('strong');
    name.textContent = store.storeName;
    const state = document.createElement('small');
    state.textContent = statusLabel(store);
    state.className = store.status === 'HUMAN_ACTION_REQUIRED' ? 'bad' : '';
    text.append(name, state);
    identity.append(icon, text);

    const controls = document.createElement('div');
    controls.className = 'store-controls';
    controls.append(button('打开', 'link-button', async () => {
      renderOpenDiagnostic({ stage: 'CLICK_SENT' });
      await run(() => api.selectStore(store.storeUuid));
    }));
    card.append(identity, controls);
    elements.storeList.append(card);
  }
}

function summaryCard(label, value, detail, tone = 'normal') {
  const card = document.createElement('article');
  card.className = `summary-card ${tone}`;
  const name = document.createElement('span');
  name.textContent = label;
  const number = document.createElement('strong');
  number.textContent = value;
  const note = document.createElement('small');
  note.textContent = detail;
  card.append(name, number, note);
  return card;
}

function renderManagement(snapshot) {
  const online = snapshot.stores.filter((store) => store.status === 'READY_READ_ONLY').length;
  const attention = snapshot.stores.filter((store) => store.status === 'HUMAN_ACTION_REQUIRED').length;
  elements.managementSummary.replaceChildren(
    summaryCard('授权店铺', String(snapshot.stores.length), '由天统AI云端下发'),
    summaryCard('只读在线', String(online), '会话保持且可以打开京麦', 'good'),
    summaryCard('需要处理', String(attention), '登录、验证码或风控', attention ? 'bad' : 'good')
  );
  elements.managementStores.replaceChildren();
  for (const store of snapshot.stores) {
    const row = document.createElement('article');
    row.className = 'management-row';
    const details = document.createElement('div');
    const title = document.createElement('strong');
    title.textContent = store.storeName;
    const meta = document.createElement('span');
    meta.textContent = `${store.storeCode} · ${statusLabel(store)}${store.host ? ` · ${store.host}` : ''}`;
    details.append(title, meta);
    const open = button('打开京麦', 'panel-action compact', async () => {
      await run(() => api.selectStore(store.storeUuid));
      showToast(`已打开：${store.storeName}`, 'success');
    });
    row.append(details, open);
    elements.managementStores.append(row);
  }
  if (!snapshot.stores.length) {
    const empty = document.createElement('p');
    empty.className = 'workspace-empty';
    empty.textContent = '尚未收到云端授权店铺，请先完成设备配对。';
    elements.managementStores.append(empty);
  }
}

function renderSync(snapshot) {
  const automatic = snapshot.automaticSync || { status: 'STARTING', total: 0, succeeded: 0, skipped: 0, failed: 0 };
  const currentAutomaticStore = snapshot.stores.find((store) => store.storeUuid === automatic.currentStoreUuid);
  const nextTime = automatic.nextRunAt ? new Date(automatic.nextRunAt).toLocaleTimeString('zh-CN', { hour12: false }) : null;
  const automaticLabels = {
    STARTING: ['全自动同步正在启动', '设备连接云端后将自动开始。'],
    WAITING: ['全自动同步已开启', `每5分钟自动同步全部授权店铺${nextTime ? ` · 下次 ${nextTime}` : ''}`],
    RUNNING: ['正在自动同步', `${currentAutomaticStore ? currentAutomaticStore.storeName : '授权店铺'} · 已成功 ${automatic.succeeded || 0} 家`],
    RETRY_WAIT: ['部分店铺同步失败，等待重试', `成功 ${automatic.succeeded || 0} · 跳过 ${automatic.skipped || 0} · 失败 ${automatic.failed || 0}${nextTime ? ` · ${nextTime}重试` : ''}`],
    PAUSED: ['全自动同步暂时等待', `等待云端连接、电脑解锁或人工完成登录${nextTime ? ` · ${nextTime}检查` : ''}`],
    STOPPED: ['全自动同步已停止', '重新启动客户端后会自动恢复。']
  };
  const automaticText = automaticLabels[automatic.status] || automaticLabels.STARTING;
  elements.autoSyncHeadline.textContent = automaticText[0];
  elements.autoSyncDetail.textContent = automaticText[1];
  elements.autoSyncBanner.classList.toggle('warning', ['RETRY_WAIT', 'PAUSED', 'STOPPED'].includes(automatic.status));
  elements.autoSyncBanner.classList.toggle('recognized', ['WAITING', 'RUNNING'].includes(automatic.status));
  elements.automaticSyncStatus.textContent = automatic.status === 'RUNNING' ? '正在同步' : automatic.status === 'WAITING' ? '已开启' : automatic.status === 'RETRY_WAIT' ? '等待重试' : automatic.status === 'PAUSED' ? '暂时等待' : '正在启动';
  const recognition = snapshot.pageRecognition || { status: 'NO_ACTIVE_STORE', metrics: [] };
  const cloudSync = snapshot.cloudSync || { status: 'NO_ACTIVE_STORE' };
  const metrics = Array.isArray(recognition.metrics) ? recognition.metrics : [];
  const pageLabel = PAGE_TYPE_LABELS[recognition.pageType] || '等待识别';
  const statusLabels = {
    NO_ACTIVE_STORE: '请先打开店铺',
    WAITING_PAGE: '正在等待京东页面',
    WAITING_LOGIN: '请先完成京东登录',
    RECOGNIZED: `已识别 ${metrics.length} 项经营指标`,
    PAGE_RECOGNIZED_NO_METRICS: '已识别页面，当前没有白名单指标',
    RECOGNITION_FAILED: '本次页面识别失败，请刷新页面重试'
  };
  const recognized = recognition.status === 'RECOGNIZED';
  elements.recognitionHeadline.textContent = statusLabels[recognition.status] || '正在识别页面';
  const cloudLabels = {
    READY_TO_SYNC: '等待点击立即同步',
    SYNCING: '正在加密上传云端',
    SYNCED: `已上传云端${cloudSync.accepted ? `，写入 ${cloudSync.accepted} 条` : ''}`,
    ALREADY_SYNCED: '该批数据已同步，无需重复写入',
    SYNC_FAILED: '云端同步失败，请重试'
  };
  elements.recognitionDetail.textContent = recognized
    ? `${pageLabel} · ${recognition.host || ''} · ${recognition.capturedAt ? new Date(recognition.capturedAt).toLocaleTimeString('zh-CN') : ''} · ${cloudLabels[cloudSync.status] || '等待同步'}`
    : '打开京麦首页或京东商智后，工作台每10秒自动识别一次允许读取的经营指标。';
  elements.recognitionBanner.classList.toggle('warning', !recognized);
  elements.recognitionBanner.classList.toggle('recognized', recognized);
  elements.recognitionState.textContent = recognized ? `已识别${metrics.length}项` : '自动识别中';
  elements.recognitionState.classList.toggle('good', recognized);
  elements.recognitionState.classList.toggle('muted', !recognized);
  elements.syncDatasets.replaceChildren();
  for (const [category, name, description] of DATASETS) {
    const categoryMetrics = metrics.filter((item) => item.category === category);
    const card = document.createElement('article');
    card.className = 'dataset-card';
    const status = document.createElement('span');
    status.className = 'dataset-status';
    status.textContent = categoryMetrics.length ? `已识别 ${categoryMetrics.length} 项` : '当前页面暂无';
    status.classList.toggle('ready', Boolean(categoryMetrics.length));
    const title = document.createElement('strong');
    title.textContent = name;
    const detail = document.createElement('p');
    detail.textContent = description;
    const values = document.createElement('dl');
    values.className = 'recognized-values';
    for (const metric of categoryMetrics) {
      const row = document.createElement('div');
      const label = document.createElement('dt');
      label.textContent = metric.label;
      const value = document.createElement('dd');
      value.textContent = metric.value;
      row.append(label, value);
      values.append(row);
    }
    const time = document.createElement('small');
    time.textContent = recognition.capturedAt
      ? `最后识别：${new Date(recognition.capturedAt).toLocaleTimeString('zh-CN')}`
      : '最后识别：暂无';
    card.append(status, title, detail, values, time);
    elements.syncDatasets.append(card);
  }

  const rightRows = document.querySelectorAll('.datasets li');
  rightRows.forEach((row, index) => {
    const category = DATASETS[index] && DATASETS[index][0];
    const count = metrics.filter((item) => item.category === category).length;
    const value = row.querySelector('em');
    if (value) value.textContent = count ? `已识别 ${count} 项` : '当前页暂无';
  });
}

function renderAlerts(snapshot) {
  const storeAlerts = snapshot.stores.filter((store) => store.status === 'HUMAN_ACTION_REQUIRED');
  const systemAlerts = snapshot.cloudStatus === 'CONNECTED' ? 0 : 1;
  const total = storeAlerts.length + systemAlerts + (snapshot.cloudDataSyncEnabled ? 0 : 1);
  elements.alertSummary.replaceChildren(
    summaryCard('当前预警', String(total), '需要检查的事项', total ? 'bad' : 'good'),
    summaryCard('店铺异常', String(storeAlerts.length), '登录、验证码与风控'),
    summaryCard('拦截请求', String(snapshot.blockedBusinessWriteAttempts), 'R293浏览兼容模式')
  );
  elements.alertList.replaceChildren();
  const alerts = [];
  for (const store of storeAlerts) {
    alerts.push(['店铺需要人工处理', `${store.storeName}：${reasonLabel(store.reason)}`, 'bad']);
  }
  if (snapshot.cloudStatus !== 'CONNECTED') {
    alerts.push(['云端连接异常', '请点击“刷新授权店铺”重新连接。', 'bad']);
  }
  if (!snapshot.cloudDataSyncEnabled) {
    alerts.push(['云端同步尚不可用', '请先使用8位配对码完成设备配对并刷新授权店铺。', 'warning']);
  }
  if (!alerts.length) alerts.push(['运行正常', '当前没有需要处理的异常。', 'good']);
  for (const [title, description, tone] of alerts) {
    const row = document.createElement('article');
    row.className = `alert-row ${tone}`;
    const marker = document.createElement('span');
    marker.className = 'alert-marker';
    const text = document.createElement('div');
    const heading = document.createElement('strong');
    heading.textContent = title;
    const detail = document.createElement('p');
    detail.textContent = description;
    text.append(heading, detail);
    row.append(marker, text);
    elements.alertList.append(row);
  }
}

function renderWorkspace(snapshot) {
  const section = snapshot.activeSection || 'business';
  for (const item of elements.topnav.querySelectorAll('[data-section]')) {
    item.classList.toggle('active', item.dataset.section === section);
  }
  elements.workspacePanels.classList.toggle('hidden', section === 'business');
  for (const panel of elements.workspacePanels.querySelectorAll('[data-panel]')) {
    panel.classList.toggle('active', panel.dataset.panel === section);
  }
  const active = snapshot.stores.find((store) => store.storeUuid === snapshot.activeStoreUuid);
  elements.emptyStage.classList.toggle('hidden', section !== 'business' || Boolean(active));
  renderManagement(snapshot);
  renderSync(snapshot);
  renderAlerts(snapshot);
}

function render(snapshot) {
  latest = snapshot;
  renderOpenDiagnostic(snapshot.openDiagnostic);
  renderStores(snapshot);
  const active = snapshot.stores.find((store) => store.storeUuid === snapshot.activeStoreUuid);
  elements.activeStore.textContent = active ? active.storeName : '未选择';
  const cloudLabels = {
    NOT_PAIRED: '尚未配对',
    PAIRING: '正在配对',
    CONNECTING: '正在连接',
    CONNECTED: '连接正常',
    AUTHORIZATION_REVOKED: '授权已撤销',
    SECURE_STORAGE_UNAVAILABLE: '系统安全存储不可用',
    SECURE_STORAGE_BASIC_TEXT_REJECTED: '拒绝不安全的本地密钥存储'
  };
  elements.cloudStatus.textContent = cloudLabels[snapshot.cloudStatus] || '连接异常';
  elements.businessWrites.textContent = `BUSINESS_WRITE_COUNT=${snapshot.businessWriteStatus}`;
  elements.blockedWrites.textContent = String(snapshot.blockedBusinessWriteAttempts);
  renderWorkspace(snapshot);

  if (active && active.status === 'HUMAN_ACTION_REQUIRED') {
    elements.humanCard.classList.remove('hidden');
    elements.humanReason.textContent = reasonLabel(active.reason);
  } else {
    elements.humanCard.classList.add('hidden');
  }
}

async function activateSection(section) {
  await run(() => api.setSection(section));
}

async function refreshStoresWithFeedback() {
  const result = await api.refreshStores();
  showToast(`授权店铺已刷新：${result.stores.length} 家`, 'success');
  return result;
}

async function showSyncStatus() {
  const result = await api.syncPage();
  render(result);
  const count = result.pageRecognition && result.pageRecognition.metrics
    ? result.pageRecognition.metrics.length
    : 0;
  const accepted = result.cloudSync && Number.isSafeInteger(result.cloudSync.accepted)
    ? result.cloudSync.accepted
    : 0;
  showToast(count ? `已识别 ${count} 项并同步云端，写入 ${accepted} 条` : '当前页面没有可同步的白名单指标', count ? 'success' : 'warning');
}

async function showSyncAllStatus() {
  const result = await api.syncAllNow();
  showToast(`全部店铺同步完成：成功 ${result.succeeded || 0}，跳过 ${result.skipped || 0}，失败 ${result.failed || 0}`, result.failed ? 'warning' : 'success');
  return await api.getSnapshot();
}

async function run(operation) {
  elements.formMessage.textContent = '';
  try {
    const result = await operation();
    if (result) render(result);
  } catch (error) {
    const code = String((error && error.message) || '');
    renderOpenDiagnostic({ stage: 'OPEN_FAILED', code: code.slice(0, 96) });
    const messages = [
      ['PAIR_REQUEST_INVALID', '请输入本机名称和有效的8位配对码'],
      ['DEVICE_NOT_PAIRED', '请先使用云端一次性配对码完成配对'],
      ['STORE_NOT_AUTHORIZED', '该店铺未由云端授权，已拒绝打开'],
      ['STORE_NOT_OPEN', '请先打开一家店铺，再识别当前京东页面'],
      ['NO_RECOGNIZED_METRICS', '当前页面没有可同步的白名单经营指标'],
      ['SYNC_PAYLOAD_INVALID', '识别结果不能转换为安全同步数据，请切换页面后重试'],
      ['REMOTE_VIEW_PAUSED', '锁屏或系统休眠期间已停止京东会话，解锁后请重新打开店铺'],
      ['CLOUD_AUTHORIZATION_REQUIRED', '店铺授权正在刷新，请稍后再次打开'],
      ['STORE_SESSION_NOT_PERSISTENT', '店铺安全会话创建失败，请关闭客户端后重试'],
      ['AUTHORIZATION_REVOKED', '设备授权已撤销，请重新配对'],
      ['SECURE_STORAGE_BASIC_TEXT_REJECTED', '当前系统只能明文保存密钥，客户端已拒绝配对'],
      ['SECURE_STORAGE_UNAVAILABLE', '系统安全存储不可用，不能保存设备令牌'],
      ['CLOUD_CONNECTION_FAILED', '无法连接天统AI云端，请检查网络'],
      ['CLOUD_REQUEST_REJECTED', '云端拒绝请求，请检查配对码'],
      ['CLOUD_RESPONSE_INVALID', '云端返回数据未通过安全校验'],
      ['AUTO_SYNC_NOT_READY', '全自动同步正在启动，请稍后重试']
    ];
    const matched = messages.find(([needle]) => code.includes(needle));
    elements.formMessage.textContent = matched ? matched[1] : '操作失败，请重试';
  }
}

elements.pairingForm.addEventListener('submit', (event) => {
  event.preventDefault();
  run(async () => {
    const result = await api.pair({
      code: elements.pairingCode.value,
      deviceName: elements.deviceName.value
    });
    elements.pairingCode.value = '';
    return result;
  });
});

elements.refreshStores.addEventListener('click', () => run(refreshStoresWithFeedback));
elements.panelRefreshStores.addEventListener('click', () => run(refreshStoresWithFeedback));
elements.syncNow.addEventListener('click', () => run(showSyncAllStatus));
elements.syncCheck.addEventListener('click', () => run(showSyncStatus));
elements.browseMode.addEventListener('click', async () => {
  await activateSection('business');
  showToast('已返回京麦只读浏览页面', 'success');
});

elements.topnav.addEventListener('click', (event) => {
  const target = event.target.closest('[data-section]');
  if (target) activateSection(target.dataset.section);
});

elements.storeTabs.addEventListener('click', (event) => {
  const target = event.target.closest('[data-store-filter]');
  if (!target) return;
  storeFilter = target.dataset.storeFilter;
  for (const tab of elements.storeTabs.querySelectorAll('[data-store-filter]')) {
    tab.classList.toggle('active', tab === target);
  }
  if (latest) renderStores(latest);
});

elements.storeSearch.addEventListener('input', () => {
  if (latest) renderStores(latest);
});

for (const action of document.querySelectorAll('[data-reason]')) {
  action.addEventListener('click', () => {
    if (!latest || !latest.activeStoreUuid) {
      elements.formMessage.textContent = '请先打开一家店铺';
      return;
    }
    run(() => api.reportHumanAction(latest.activeStoreUuid, action.dataset.reason));
  });
}

api.onStatus(render);
run(() => api.getSnapshot());
