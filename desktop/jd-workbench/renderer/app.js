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
  formMessage: document.getElementById('formMessage'),
  emptyStage: document.getElementById('emptyStage'),
  activeStore: document.getElementById('activeStore'),
  cloudStatus: document.getElementById('cloudStatus'),
  businessWrites: document.getElementById('businessWrites'),
  blockedWrites: document.getElementById('blockedWrites'),
  humanCard: document.getElementById('humanCard'),
  humanReason: document.getElementById('humanReason')
});

let latest = null;

function statusLabel(store) {
  const labels = {
    NOT_OPENED: '未打开',
    LOADING: '正在打开',
    READY_READ_ONLY: '只读在线',
    SESSION_STOPPED: '会话已停止',
    HUMAN_ACTION_REQUIRED: '需人工处理',
    IDLE: '等待下次同步',
    SYNCING: '正在自动同步',
    ERROR: '同步失败，等待重试',
    PAUSED: '已暂停',
    ONLINE: '客户端在线'
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

function renderStores(snapshot) {
  const query = elements.storeSearch.value.trim().toLowerCase();
  const visible = snapshot.stores.filter((store) => store.storeName.toLowerCase().includes(query));
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
    controls.append(button('打开', 'link-button', async () => run(() => api.selectStore(store.storeUuid))));
    card.append(identity, controls);
    elements.storeList.append(card);
  }
}

function render(snapshot) {
  latest = snapshot;
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
  elements.syncNow.disabled = snapshot.cloudStatus !== 'CONNECTED';
  elements.businessWrites.textContent = `BUSINESS_WRITE_COUNT=${snapshot.businessWriteStatus}`;
  elements.blockedWrites.textContent = String(snapshot.blockedBusinessWriteAttempts);
  elements.emptyStage.classList.toggle('hidden', Boolean(active));

  if (active && active.status === 'HUMAN_ACTION_REQUIRED') {
    elements.humanCard.classList.remove('hidden');
    elements.humanReason.textContent = reasonLabel(active.reason);
  } else {
    elements.humanCard.classList.add('hidden');
  }
}

async function run(operation) {
  elements.formMessage.textContent = '';
  try {
    const result = await operation();
    if (result) render(result);
  } catch (error) {
    const code = String((error && error.message) || '');
    const messages = [
      ['PAIR_REQUEST_INVALID', '请输入本机名称和有效的8位配对码'],
      ['DEVICE_NOT_PAIRED', '请先使用云端一次性配对码完成配对'],
      ['STORE_NOT_AUTHORIZED', '该店铺未由云端授权，已拒绝打开'],
      ['REMOTE_VIEW_PAUSED', '锁屏或系统休眠期间已停止京东会话，解锁后请重新打开店铺'],
      ['AUTHORIZATION_REVOKED', '设备授权已撤销，请重新配对'],
      ['SECURE_STORAGE_BASIC_TEXT_REJECTED', '当前系统只能明文保存密钥，客户端已拒绝配对'],
      ['SECURE_STORAGE_UNAVAILABLE', '系统安全存储不可用，不能保存设备令牌'],
      ['CLOUD_CONNECTION_FAILED', '无法连接天统AI云端，请检查网络'],
      ['CLOUD_REQUEST_REJECTED', '云端拒绝请求，请检查配对码'],
      ['CLOUD_RESPONSE_INVALID', '云端返回数据未通过安全校验']
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

elements.refreshStores.addEventListener('click', () => run(() => api.refreshStores()));
elements.syncNow.addEventListener('click', () => run(() => api.syncNow()));

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
