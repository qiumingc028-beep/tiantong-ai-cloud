'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const {
  app,
  BrowserWindow,
  WebContentsView,
  ipcMain,
  net,
  powerMonitor,
  protocol,
  safeStorage,
  session
} = require('electron');

const { createCloudClient } = require('./cloud-client');
const { ROUTES, SNAPSHOT_SCRIPT, normalizeSnapshot } = require('./readonly-collector');
const { createSyncScheduler } = require('./sync-scheduler');
const {
  classifyRequest,
  detectHumanActionFromUrl,
  hostnameForStatus,
  isAuditedMainFrameRoute,
  isExactAuthenticationRoute,
  parseAllowedHttpsUrl
} = require('./security-policy');

const APP_SCHEME = 'tiantong-workbench';
const SHELL_URL = `${APP_SCHEME}://app/index.html`;
const JD_HOME_URL = 'https://shop.jd.com/';
const STORE_UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const HUMAN_ACTION_REASONS = new Set(['CAPTCHA', 'RISK_CONTROL', 'LOGIN_EXPIRED']);
const LAYOUT = Object.freeze({ top: 72, left: 300, right: 320, bottom: 36 });
const AUTHORIZATION_REFRESH_MS = 30_000;
const AUTHORIZATION_LEASE_MS = 45_000;

const CHANNELS = Object.freeze({
  snapshot: 'workbench:snapshot',
  pair: 'workbench:pair',
  refreshStores: 'workbench:refresh-stores',
  selectStore: 'workbench:select-store',
  humanAction: 'workbench:human-action',
  syncNow: 'workbench:sync-now',
  status: 'workbench:status'
});

protocol.registerSchemesAsPrivileged([
  {
    scheme: APP_SCHEME,
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      corsEnabled: false,
      bypassCSP: false
    }
  }
]);

const hasSingleInstanceLock = app.requestSingleInstanceLock();
if (!hasSingleInstanceLock) app.quit();

let shellWindow = null;
let activeContext = null;
let collectionContext = null;
let stores = [];
let cloudClient = null;
let cloudStatus = 'NOT_PAIRED';
let blockedBusinessWriteAttempts = 0;
let remoteViewAccessPaused = false;
let viewTransition = Promise.resolve();
let authorizationLeaseExpiresAt = 0;
let authorizationRefreshTimer = null;
let syncScheduler = null;
let appQuitting = false;
const statusByStore = new Map();
const securedPartitions = new Set();
const remoteSessions = new Map();
const reportedSignals = new Set();

function canonicalStoreUuid(value) {
  const candidate = String(value || '').trim().toLowerCase();
  if (!STORE_UUID_PATTERN.test(candidate)) throw new Error('STORE_UUID_INVALID');
  return candidate;
}

function cleanStoreName(value) {
  const cleaned = String(value || '')
    .replace(/[\u0000-\u001f\u007f]/g, '')
    .trim()
    .slice(0, 200);
  if (!cleaned) throw new Error('CLOUD_STORE_INVALID');
  return cleaned;
}

function cleanStoreCode(value) {
  const cleaned = String(value || '')
    .replace(/[\u0000-\u001f\u007f]/g, '')
    .trim()
    .slice(0, 100);
  if (!cleaned) throw new Error('CLOUD_STORE_INVALID');
  return cleaned;
}

function positiveInteger(value) {
  if (!Number.isSafeInteger(value) || value <= 0) throw new Error('CLOUD_STORE_INVALID');
  return value;
}

function partitionForStore(storeUuid) {
  return `persist:jd-${canonicalStoreUuid(storeUuid)}`;
}

function normalizeCloudStore(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    throw new Error('CLOUD_STORE_INVALID');
  }
  const storeUuid = canonicalStoreUuid(raw.store_uuid);
  const partition = partitionForStore(storeUuid);
  if (raw.partition !== partition) throw new Error('CLOUD_STORE_INVALID');
  return Object.freeze({
    storeId: positiveInteger(raw.store_id),
    subjectId: positiveInteger(raw.subject_id),
    storeUuid,
    partition,
    storeCode: cleanStoreCode(raw.store_code),
    storeName: cleanStoreName(raw.store_name),
    cloudStoreStatus: typeof raw.status === 'string' ? raw.status.slice(0, 32) : 'OFFLINE',
    cloudReasonCode: typeof raw.reason_code === 'string' ? raw.reason_code.slice(0, 64) : null,
    lastSyncAt: typeof raw.last_sync_at === 'string' ? raw.last_sync_at.slice(0, 40) : null,
    lastAttemptAt: typeof raw.last_attempt_at === 'string' ? raw.last_attempt_at.slice(0, 40) : null,
    nextSyncAt: typeof raw.next_sync_at === 'string' ? raw.next_sync_at.slice(0, 40) : null,
    retryCount: Number.isInteger(raw.retry_count) ? raw.retry_count : 0,
    syncEnabled: raw.sync_policy ? raw.sync_policy.enabled === true : true,
    intervalSeconds: Number.isInteger(raw.sync_policy && raw.sync_policy.interval_seconds)
      ? raw.sync_policy.interval_seconds
      : 300
  });
}

function safeStoreState(store) {
  const state = statusByStore.get(store.storeUuid) || {};
  return Object.freeze({
    storeUuid: store.storeUuid,
    storeName: store.storeName,
    storeCode: store.storeCode,
    status: state.status || store.cloudStoreStatus || 'NOT_OPENED',
    reason: state.reason || store.cloudReasonCode || null,
    host: state.host || null,
    updatedAt: state.updatedAt || null,
    lastSyncAt: store.lastSyncAt,
    lastAttemptAt: state.lastAttemptAt || store.lastAttemptAt,
    nextSyncAt: state.nextSyncAt || store.nextSyncAt,
    retryCount: Number.isInteger(state.retryCount) ? state.retryCount : store.retryCount,
    syncEnabled: store.syncEnabled,
    intervalSeconds: store.intervalSeconds
  });
}

function snapshot() {
  return Object.freeze({
    stores: stores.map(safeStoreState),
    activeStoreUuid: activeContext ? activeContext.store.storeUuid : null,
    clientStatus: remoteViewAccessPaused ? 'PAUSED' : 'READY',
    cloudStatus,
    readOnly: true,
    collectionEnabled: true,
    businessWriteStatus: 'UNVERIFIED',
    blockedBusinessWriteAttempts
  });
}

function sendSnapshot() {
  if (shellWindow && !shellWindow.isDestroyed()) {
    shellWindow.webContents.send(CHANNELS.status, snapshot());
  }
}

function setStoreStatus(storeUuid, status, reason = null, host = null, details = {}) {
  statusByStore.set(storeUuid, {
    status,
    reason,
    host,
    updatedAt: new Date().toISOString(),
    ...details
  });
  sendSnapshot();
}

function clearReportedSignals(storeUuid) {
  for (const key of reportedSignals) {
    if (key.startsWith(`${storeUuid}:`)) reportedSignals.delete(key);
  }
}

function reportHumanAction(storeUuid, reason, rawUrl) {
  const host = hostnameForStatus(rawUrl);
  const signalKey = `${storeUuid}:${reason}:${host}`;
  if (reportedSignals.has(signalKey)) return;
  reportedSignals.add(signalKey);
  revokeActiveViewForHumanAction(storeUuid);
  setStoreStatus(storeUuid, 'HUMAN_ACTION_REQUIRED', reason, host);
  const store = stores.find((item) => item.storeUuid === storeUuid);
  const reasonCode = cloudHumanActionReason(reason);
  if (store && reasonCode && cloudClient && cloudClient.isPaired()) {
    cloudClient.heartbeat({
      status: 'HUMAN_ACTION_REQUIRED',
      storeId: store.storeId,
      reasonCode
    }).catch(() => undefined);
  }
}

function cloudHumanActionReason(reason) {
  const mapping = Object.freeze({
    CAPTCHA: 'CAPTCHA_REQUIRED',
    RISK_CONTROL: 'RISK_CONTROL',
    RISK_OR_CAPTCHA: 'RISK_CONTROL',
    LOGIN_EXPIRED: 'LOGIN_EXPIRED',
    LOGIN_REQUIRED: 'LOGIN_EXPIRED',
    UNKNOWN_DOMAIN: 'UNKNOWN_DOMAIN',
    AUTHORIZATION_REVOKED: 'AUTHORIZATION_REVOKED',
    STORE_IDENTITY_MISMATCH: 'STORE_IDENTITY_MISMATCH'
  });
  return mapping[reason] || null;
}

function revokeActiveViewForHumanAction(storeUuid) {
  if (!activeContext || activeContext.store.storeUuid !== storeUuid) return;
  const context = activeContext;
  activeContext = null;
  context.disposed = true;
  if (!context.view.webContents.isDestroyed()) context.view.webContents.stop();
  if (shellWindow && !shellWindow.isDestroyed()) {
    try {
      shellWindow.contentView.removeChildView(context.view);
    } catch (_error) {
      // Network authority was already revoked by clearing activeContext.
    }
  }
  Promise.all([
    stopSessionBackground(context.targetSession),
    closeRemoteContents(context.view.webContents)
  ]).catch(() => undefined);
}

function validateShellSender(event) {
  const senderFrame = event.senderFrame;
  if (!senderFrame || senderFrame !== event.sender.mainFrame) {
    throw new Error('IPC_SENDER_REJECTED');
  }
  const parsed = new URL(senderFrame.url);
  if (
    parsed.protocol !== `${APP_SCHEME}:` ||
    parsed.hostname !== 'app' ||
    parsed.pathname !== '/index.html'
  ) {
    throw new Error('IPC_SENDER_REJECTED');
  }
}

function installDownloadBlock(targetSession, storeUuid = null) {
  targetSession.on('will-download', (event) => {
    event.preventDefault();
    if (storeUuid) reportHumanAction(storeUuid, 'DOWNLOAD_BLOCKED', JD_HOME_URL);
  });
}

function isPartitionActive(storeUuid, partition, targetSession) {
  const visibleActive = Boolean(
    activeContext &&
    !activeContext.disposed &&
    activeContext.store.storeUuid === storeUuid &&
    activeContext.partition === partition &&
    activeContext.targetSession === targetSession &&
    !activeContext.view.webContents.isDestroyed() &&
    Date.now() < authorizationLeaseExpiresAt
  );
  const collectorActive = Boolean(
    collectionContext &&
    !collectionContext.disposed &&
    collectionContext.store.storeUuid === storeUuid &&
    collectionContext.partition === partition &&
    collectionContext.targetSession === targetSession &&
    !collectionContext.view.webContents.isDestroyed() &&
    Date.now() < authorizationLeaseExpiresAt
  );
  return visibleActive || collectorActive;
}

function currentUrlForStore(storeUuid) {
  if (
    !activeContext ||
    activeContext.disposed ||
    activeContext.store.storeUuid !== storeUuid ||
    activeContext.view.webContents.isDestroyed()
  ) {
    return '';
  }
  return activeContext.view.webContents.getURL();
}

function isActiveMainFrameSource(details, storeUuid) {
  for (const context of [activeContext, collectionContext]) {
    if (!context || context.disposed || context.store.storeUuid !== storeUuid) continue;
    const contents = context.view.webContents;
    if (details.webContentsId === contents.id && details.frame && details.frame === contents.mainFrame) return true;
  }
  return false;
}

function installRemoteSessionSecurity(targetSession, storeUuid, partition) {
  if (securedPartitions.has(partition)) return;
  securedPartitions.add(partition);
  remoteSessions.set(partition, targetSession);

  targetSession.setPermissionCheckHandler(() => false);
  targetSession.setPermissionRequestHandler((_webContents, _permission, callback) => callback(false));
  targetSession.setDevicePermissionHandler(() => false);
  installDownloadBlock(targetSession, storeUuid);

  // Electron accepts only the last listener for this phase, so each partition
  // has exactly one centralized, fail-closed request firewall.
  targetSession.webRequest.onBeforeRequest({ urls: ['<all_urls>'] }, (details, callback) => {
    const decision = classifyRequest({
      url: details.url,
      method: details.method,
      resourceType: details.resourceType,
      currentMainFrameUrl: currentUrlForStore(storeUuid),
      isActive: isPartitionActive(storeUuid, partition, targetSession),
      isMainFrameSource: isActiveMainFrameSource(details, storeUuid)
    });
    if (decision.allow) {
      callback({ cancel: false });
      return;
    }

    if (decision.code === 'READ_ONLY_WRITE_BLOCKED') {
      blockedBusinessWriteAttempts += 1;
    }
    if (decision.code !== 'INACTIVE_PARTITION') {
      reportHumanAction(storeUuid, decision.code, details.url);
    }
    callback({ cancel: true });
  });
}

function attachRemoteViewSecurity(context) {
  const contents = context.view.webContents;
  const storeUuid = context.store.storeUuid;

  const guardNavigation = (event, targetUrl) => {
    if (!isPartitionActive(storeUuid, context.partition, context.targetSession)) {
      event.preventDefault();
      return;
    }
    const reason = detectHumanActionFromUrl(targetUrl);
    if (reason) {
      event.preventDefault();
      reportHumanAction(storeUuid, reason, targetUrl);
      return;
    }
    if (!isAuditedMainFrameRoute(targetUrl)) {
      event.preventDefault();
      reportHumanAction(storeUuid, 'ENDPOINT_NOT_AUDITED', targetUrl);
    }
  };

  contents.on('will-navigate', guardNavigation);
  contents.on('will-redirect', guardNavigation);
  contents.on('will-frame-navigate', (event) => guardNavigation(event, event.url));
  contents.setWindowOpenHandler(({ url }) => {
    reportHumanAction(storeUuid, 'NEW_WINDOW_BLOCKED', url);
    return { action: 'deny' };
  });

  contents.on('page-title-updated', (_event, title) => {
    if (/验证码|安全验证|风险验证|风控|身份核验/.test(String(title || ''))) {
      reportHumanAction(storeUuid, 'RISK_OR_CAPTCHA', contents.getURL());
    }
  });

  contents.on('did-navigate', (_event, targetUrl) => {
    if (context.disposed) return;
    const reason = detectHumanActionFromUrl(targetUrl);
    if (reason) {
      reportHumanAction(storeUuid, reason, targetUrl);
      return;
    }
    if (isExactAuthenticationRoute(targetUrl)) {
      setStoreStatus(storeUuid, 'HUMAN_ACTION_REQUIRED', 'LOGIN_REQUIRED', hostnameForStatus(targetUrl));
      return;
    }
    const parsed = parseAllowedHttpsUrl(targetUrl);
    if (parsed && (parsed.hostname.includes('passport') || parsed.hostname === 'jshopx.jd.com')) {
      reportHumanAction(storeUuid, 'AUTH_ROUTE_NOT_AUDITED', targetUrl);
      return;
    }
    if (parsed) {
      clearReportedSignals(storeUuid);
      setStoreStatus(storeUuid, 'READY_READ_ONLY', null, parsed.hostname);
    }
  });

  contents.on('did-fail-load', (_event, errorCode, _errorDescription, validatedUrl, isMainFrame) => {
    if (!isMainFrame || context.disposed || errorCode === -3) return;
    reportHumanAction(storeUuid, 'PAGE_LOAD_FAILED', validatedUrl || JD_HOME_URL);
  });

  contents.on('render-process-gone', () => {
    if (!context.disposed) {
      setStoreStatus(storeUuid, 'HUMAN_ACTION_REQUIRED', 'REMOTE_RENDERER_STOPPED', null);
    }
  });

  contents.on('before-input-event', (event, input) => {
    const key = String(input.key || '').toLowerCase();
    const developerShortcut =
      key === 'f12' ||
      ((input.control || input.meta) && input.shift && ['i', 'j', 'c'].includes(key));
    if (developerShortcut) event.preventDefault();
  });
}

function setRemoteBounds() {
  if (!shellWindow || !activeContext || activeContext.disposed) return;
  const [width, height] = shellWindow.getContentSize();
  activeContext.view.setBounds({
    x: LAYOUT.left,
    y: LAYOUT.top,
    width: Math.max(1, width - LAYOUT.left - LAYOUT.right),
    height: Math.max(1, height - LAYOUT.top - LAYOUT.bottom)
  });
}

async function stopSessionBackground(targetSession) {
  try {
    await Promise.resolve(targetSession.serviceWorkers.stopAllRunning());
  } catch (_error) {
    // Continue fail-closed teardown even when Chromium reports no worker scope.
  }
  try {
    await targetSession.clearStorageData({ storages: ['serviceworkers'] });
  } catch (_error) {
    // Network remains disabled through the partition activity gate.
  }
  try {
    await targetSession.closeAllConnections();
  } catch (_error) {
    // The view is still closed below; no request becomes authorized on failure.
  }
}

async function purgeStoreSession(store) {
  const targetSession = session.fromPartition(store.partition, { cache: true });
  await stopSessionBackground(targetSession);
  try {
    await targetSession.clearStorageData();
  } catch (_error) {
    // The authorization lease and partition activity gate remain revoked.
  }
  try {
    await targetSession.clearCache();
  } catch (_error) {
    // Storage clearing above is the primary revocation operation.
  }
}

async function closeRemoteContents(contents) {
  if (contents.isDestroyed()) return;
  contents.stop();
  await new Promise((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      resolve();
    };
    const timeout = setTimeout(finish, 1500);
    contents.once('destroyed', finish);
    contents.close({ waitForBeforeUnload: false });
  });
}

async function destroyActiveView(reason = 'SESSION_STOPPED') {
  if (!activeContext) return;
  const context = activeContext;

  // Revoke network authority synchronously before the first awaited operation.
  activeContext = null;
  context.disposed = true;
  if (!context.view.webContents.isDestroyed()) context.view.webContents.stop();
  if (shellWindow && !shellWindow.isDestroyed()) {
    try {
      shellWindow.contentView.removeChildView(context.view);
    } catch (_error) {
      // The window can already be closing; the content is still revoked above.
    }
  }

  await stopSessionBackground(context.targetSession);
  await closeRemoteContents(context.view.webContents);
  setStoreStatus(context.store.storeUuid, 'SESSION_STOPPED', reason, null);
}

async function quiesceAllRemoteSessions() {
  await Promise.all([...remoteSessions.values()].map((targetSession) => stopSessionBackground(targetSession)));
}

function queueViewTransition(operation) {
  const result = viewTransition.then(operation, operation);
  viewTransition = result.catch(() => undefined);
  return result;
}

function readScheduleState(schedulePath) {
  try {
    const parsed = JSON.parse(fs.readFileSync(schedulePath, 'utf8'));
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch (error) {
    if (error && error.code === 'ENOENT') return {};
    return {};
  }
}

function writeScheduleState(schedulePath, value) {
  const temporaryPath = `${schedulePath}.tmp`;
  fs.writeFileSync(temporaryPath, JSON.stringify(value), { encoding: 'utf8', mode: 0o600 });
  fs.renameSync(temporaryPath, schedulePath);
}

async function closeCollectionView() {
  if (!collectionContext) return;
  const context = collectionContext;
  collectionContext = null;
  context.disposed = true;
  if (!context.view.webContents.isDestroyed()) context.view.webContents.stop();
  await closeRemoteContents(context.view.webContents);
}

async function loadCollectorSnapshot(store, routeUrl) {
  const partition = store.partition;
  const targetSession = session.fromPartition(partition, { cache: true });
  if (!targetSession.isPersistent()) throw new Error('COLLECTOR_PAGE_LOAD_FAILED');
  installRemoteSessionSecurity(targetSession, store.storeUuid, partition);
  const view = new WebContentsView({
    webPreferences: {
      partition,
      nodeIntegration: false,
      nodeIntegrationInWorker: false,
      nodeIntegrationInSubFrames: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false,
      webviewTag: false,
      devTools: false,
      navigateOnDragDrop: false,
      spellcheck: false,
      plugins: false
    }
  });
  collectionContext = { store, partition, targetSession, view, disposed: false };
  view.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  try {
    await view.webContents.loadURL(routeUrl);
    await new Promise((resolve) => setTimeout(resolve, 1500));
    const currentUrl = view.webContents.getURL();
    if (isExactAuthenticationRoute(currentUrl) || /passport\./i.test(currentUrl)) {
      throw Object.assign(new Error('LOGIN_EXPIRED'), { code: 'LOGIN_EXPIRED' });
    }
    if (!isAuditedMainFrameRoute(currentUrl) || detectHumanActionFromUrl(currentUrl)) {
      throw Object.assign(new Error('COLLECTOR_PAGE_LOAD_FAILED'), { code: 'COLLECTOR_PAGE_LOAD_FAILED' });
    }
    return await view.webContents.executeJavaScript(SNAPSHOT_SCRIPT, true);
  } catch (error) {
    if (error && ['LOGIN_EXPIRED', 'RISK_CONTROL', 'CAPTCHA_REQUIRED'].includes(error.code)) throw error;
    throw Object.assign(new Error('COLLECTOR_PAGE_LOAD_FAILED'), { code: 'COLLECTOR_PAGE_LOAD_FAILED' });
  } finally {
    await closeCollectionView();
  }
}

async function runStoreCollection(store) {
  if (remoteViewAccessPaused || cloudStatus !== 'CONNECTED' || Date.now() >= authorizationLeaseExpiresAt) {
    throw Object.assign(new Error('CLOUD_CONNECTION_FAILED'), { code: 'CLOUD_CONNECTION_FAILED' });
  }
  const collectedAt = new Date().toISOString();
  const routeKinds = [
    ['dashboard', ROUTES.dashboard],
    ['fulfillment', ROUTES.fulfillment],
    ['aftersales', ROUTES.aftersales]
  ];
  let uploaded = 0;
  for (const [kind, routeUrl] of routeKinds) {
    const pageSnapshot = await loadCollectorSnapshot(store, routeUrl);
    const datasets = normalizeSnapshot(kind, pageSnapshot, collectedAt);
    for (const dataset of datasets) {
      await cloudClient.syncDataset({
        store,
        datasetType: dataset.datasetType,
        sourcePeriod: dataset.sourcePeriod,
        collectedAt,
        records: dataset.records
      });
      uploaded += 1;
    }
  }
  if (uploaded < 2) throw Object.assign(new Error('COLLECTOR_EMPTY'), { code: 'COLLECTOR_EMPTY' });
}

function initializeSyncScheduler(schedulePath) {
  syncScheduler = createSyncScheduler({
    loadState: () => readScheduleState(schedulePath),
    saveState: (value) => writeScheduleState(schedulePath, value),
    runStore: runStoreCollection,
    reportState: async (store, state) => {
      setStoreStatus(store.storeUuid, state.status, state.reasonCode || null, null, {
        lastAttemptAt: state.lastAttemptAt,
        nextSyncAt: state.nextSyncAt,
        retryCount: state.retryCount
      });
      await cloudClient.heartbeat({
        status: state.status,
        storeId: store.storeId,
        reasonCode: state.reasonCode || null,
        lastAttemptAt: state.lastAttemptAt,
        nextSyncAt: state.nextSyncAt,
        retryCount: state.retryCount
      });
    }
  });
  syncScheduler.start();
}

async function selectStoreInternal(storeUuidInput) {
  if (remoteViewAccessPaused) throw new Error('REMOTE_VIEW_PAUSED');
  if (cloudStatus !== 'CONNECTED' || Date.now() >= authorizationLeaseExpiresAt) {
    throw new Error('CLOUD_AUTHORIZATION_REQUIRED');
  }
  const storeUuid = canonicalStoreUuid(storeUuidInput);
  const store = stores.find((item) => item.storeUuid === storeUuid);
  if (!store) throw new Error('STORE_NOT_AUTHORIZED');
  if (activeContext && activeContext.store.storeUuid === storeUuid) return snapshot();

  await destroyActiveView('STORE_SWITCHED');
  // Lock/suspend can occur while the previous view is being torn down. Do not
  // create a replacement after the system event has revoked remote access.
  if (remoteViewAccessPaused) throw new Error('REMOTE_VIEW_PAUSED');
  const partition = store.partition;
  const targetSession = session.fromPartition(partition, { cache: true });
  if (!targetSession.isPersistent()) throw new Error('STORE_SESSION_NOT_PERSISTENT');
  installRemoteSessionSecurity(targetSession, storeUuid, partition);

  const view = new WebContentsView({
    webPreferences: {
      partition,
      nodeIntegration: false,
      nodeIntegrationInWorker: false,
      nodeIntegrationInSubFrames: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false,
      webviewTag: false,
      devTools: false,
      navigateOnDragDrop: false,
      spellcheck: false,
      plugins: false,
      safeDialogs: true
    }
  });

  const context = { store, partition, targetSession, view, disposed: false };
  activeContext = context;
  attachRemoteViewSecurity(context);
  shellWindow.contentView.addChildView(view);
  setRemoteBounds();
  clearReportedSignals(storeUuid);
  setStoreStatus(storeUuid, 'LOADING', null, 'shop.jd.com');

  try {
    await view.webContents.loadURL(JD_HOME_URL);
  } catch (_error) {
    if (!context.disposed) {
      setStoreStatus(storeUuid, 'HUMAN_ACTION_REQUIRED', 'PAGE_LOAD_FAILED', 'shop.jd.com');
    }
  }
  return snapshot();
}

function cloudErrorCode(error) {
  return String((error && (error.code || error.message)) || 'CLOUD_CONNECTION_FAILED')
    .replace(/^Error:\s*/, '');
}

async function refreshAuthorizedStoresInternal() {
  if (!cloudClient || !cloudClient.isPaired()) throw new Error('DEVICE_NOT_PAIRED');
  cloudStatus = 'CONNECTING';
  sendSnapshot();
  try {
    const rows = await cloudClient.listStores();
    const normalized = rows.map(normalizeCloudStore);
    const uuids = normalized.map((store) => store.storeUuid);
    if (new Set(uuids).size !== uuids.length) throw new Error('CLOUD_STORE_INVALID');

    const revokedStores = stores.filter((store) => !uuids.includes(store.storeUuid));
    if (activeContext && !uuids.includes(activeContext.store.storeUuid)) {
      await destroyActiveView('AUTHORIZATION_REVOKED');
    }
    stores = normalized;
    if (syncScheduler) syncScheduler.replaceStores(stores);
    for (const storeUuid of [...statusByStore.keys()]) {
      if (!uuids.includes(storeUuid)) statusByStore.delete(storeUuid);
    }
    await Promise.all(revokedStores.map((store) => purgeStoreSession(store)));
    await cloudClient.heartbeat({ status: 'ONLINE' });
    authorizationLeaseExpiresAt = Date.now() + AUTHORIZATION_LEASE_MS;
    cloudStatus = 'CONNECTED';
    sendSnapshot();
    return snapshot();
  } catch (error) {
    const code = cloudErrorCode(error);
    authorizationLeaseExpiresAt = 0;
    cloudStatus = code === 'AUTHORIZATION_REVOKED' ? 'AUTHORIZATION_REVOKED' : code;
    await destroyActiveView(code);
    if (code === 'AUTHORIZATION_REVOKED') {
      const revokedStores = stores;
      stores = [];
      if (syncScheduler) syncScheduler.replaceStores([]);
      await Promise.all(revokedStores.map((store) => purgeStoreSession(store)));
    }
    sendSnapshot();
    throw error;
  }
}

async function pairDeviceInternal(payload) {
  cloudStatus = 'PAIRING';
  sendSnapshot();
  await destroyActiveView('DEVICE_REPAIRED');
  try {
    await cloudClient.pair({
      code: payload && payload.code,
      deviceName: payload && payload.deviceName
    });
  } catch (error) {
    cloudStatus = cloudErrorCode(error);
    sendSnapshot();
    throw error;
  }
  return refreshAuthorizedStoresInternal();
}

function reportManualHumanAction(storeUuidInput, reasonInput) {
  const storeUuid = canonicalStoreUuid(storeUuidInput);
  const reason = String(reasonInput || '').trim().toUpperCase();
  if (!HUMAN_ACTION_REASONS.has(reason)) throw new Error('HUMAN_ACTION_REASON_INVALID');
  if (!stores.some((item) => item.storeUuid === storeUuid)) throw new Error('STORE_NOT_AUTHORIZED');
  reportHumanAction(storeUuid, reason, currentUrlForStore(storeUuid) || JD_HOME_URL);
  return snapshot();
}

function registerIpcHandlers() {
  ipcMain.handle(CHANNELS.snapshot, (event) => {
    validateShellSender(event);
    return snapshot();
  });
  ipcMain.handle(CHANNELS.pair, (event, payload) => {
    validateShellSender(event);
    return queueViewTransition(() => pairDeviceInternal(payload));
  });
  ipcMain.handle(CHANNELS.refreshStores, (event) => {
    validateShellSender(event);
    return queueViewTransition(refreshAuthorizedStoresInternal);
  });
  ipcMain.handle(CHANNELS.selectStore, (event, storeUuid) => {
    validateShellSender(event);
    return queueViewTransition(() => selectStoreInternal(storeUuid));
  });
  ipcMain.handle(CHANNELS.humanAction, (event, storeUuid, reason) => {
    validateShellSender(event);
    return reportManualHumanAction(storeUuid, reason);
  });
  ipcMain.handle(CHANNELS.syncNow, async (event, storeUuid = null) => {
    validateShellSender(event);
    if (!syncScheduler) throw new Error('SYNC_SCHEDULER_NOT_READY');
    await syncScheduler.runNow(storeUuid);
    return snapshot();
  });
}

function registerAppProtocol() {
  const rendererRoot = path.join(__dirname, 'renderer');
  const files = new Map([
    ['/index.html', path.join(rendererRoot, 'index.html')],
    ['/app.js', path.join(rendererRoot, 'app.js')],
    ['/styles.css', path.join(rendererRoot, 'styles.css')]
  ]);
  protocol.handle(APP_SCHEME, (request) => {
    const requestUrl = new URL(request.url);
    if (requestUrl.hostname !== 'app' || !files.has(requestUrl.pathname)) {
      return new Response('Not found', { status: 404 });
    }
    return net.fetch(pathToFileURL(files.get(requestUrl.pathname)).toString());
  });
}

function createShellWindow(showOnReady = true) {
  shellWindow = new BrowserWindow({
    width: 1500,
    height: 900,
    minWidth: 1180,
    minHeight: 720,
    show: false,
    title: '天统AI京东多店经营工作台',
    autoHideMenuBar: true,
    backgroundColor: '#f4f7fc',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      nodeIntegrationInWorker: false,
      nodeIntegrationInSubFrames: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false,
      webviewTag: false,
      devTools: false,
      navigateOnDragDrop: false,
      spellcheck: false
    }
  });

  shellWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  shellWindow.on('resize', setRemoteBounds);
  shellWindow.on('close', (event) => {
    if (!appQuitting) {
      event.preventDefault();
      shellWindow.hide();
      shellWindow.setSkipTaskbar(true);
      return;
    }
    if (activeContext) {
      activeContext.disposed = true;
      activeContext.view.webContents.stop();
    }
  });
  shellWindow.on('closed', () => {
    shellWindow = null;
    queueViewTransition(async () => {
      await destroyActiveView('WINDOW_CLOSED');
      await quiesceAllRemoteSessions();
    }).catch(() => undefined);
  });
  shellWindow.once('ready-to-show', () => {
    if (showOnReady) {
      shellWindow.setSkipTaskbar(false);
      shellWindow.show();
    } else {
      shellWindow.setSkipTaskbar(true);
    }
  });
  shellWindow.loadURL(SHELL_URL);
}

function stopForSystemEvent(reason) {
  // This flag and destroyActiveView's activeContext revocation happen before
  // either function reaches an await. A lock cannot sit behind a slow loadURL
  // or another queued transition.
  remoteViewAccessPaused = true;
  sendSnapshot();
  Promise.resolve(destroyActiveView(reason))
    .then(closeCollectionView)
    .then(quiesceAllRemoteSessions)
    .catch(() => undefined);
}

function resumeAfterSystemEvent() {
  if (!cloudClient || !cloudClient.isPaired()) {
    remoteViewAccessPaused = true;
    sendSnapshot();
    return;
  }
  queueViewTransition(refreshAuthorizedStoresInternal)
    .then(() => {
      remoteViewAccessPaused = false;
      sendSnapshot();
    })
    .catch(() => undefined);
  sendSnapshot();
}

app.on('certificate-error', (_event, _webContents, _url, _error, _certificate, callback) => {
  callback(false);
});

app.on('login', (event, _webContents, _details, _authInfo, callback) => {
  event.preventDefault();
  callback();
});

if (hasSingleInstanceLock) {
  app.on('second-instance', () => {
    if (!shellWindow || shellWindow.isDestroyed()) return;
    if (shellWindow.isMinimized()) shellWindow.restore();
    shellWindow.setSkipTaskbar(false);
    shellWindow.show();
    shellWindow.focus();
  });

  app.whenReady().then(() => {
    const userDataPath = app.getPath('userData');
    cloudClient = createCloudClient({
      net,
      safeStorage,
      identityPath: path.join(userDataPath, 'jd-workbench-device.json')
    });
    initializeSyncScheduler(path.join(userDataPath, 'jd-workbench-schedule.json'));
    let wasOpenedAsHidden = false;
    try {
      app.setLoginItemSettings({ openAtLogin: true, openAsHidden: true });
      wasOpenedAsHidden = app.getLoginItemSettings().wasOpenedAsHidden === true;
    } catch (_error) {
      // Linux distributions without an autostart provider continue normally.
    }
    try {
      cloudStatus = cloudClient.readIdentity() ? 'CONNECTING' : 'NOT_PAIRED';
    } catch (error) {
      cloudStatus = cloudErrorCode(error);
    }

    registerAppProtocol();
    installDownloadBlock(session.defaultSession);
    registerIpcHandlers();
    createShellWindow(!wasOpenedAsHidden);

    powerMonitor.on('lock-screen', () => stopForSystemEvent('WORKSTATION_LOCKED'));
    powerMonitor.on('unlock-screen', resumeAfterSystemEvent);
    powerMonitor.on('suspend', () => stopForSystemEvent('SYSTEM_SUSPENDED'));
    powerMonitor.on('resume', resumeAfterSystemEvent);
    powerMonitor.on('shutdown', () => stopForSystemEvent('SYSTEM_SHUTDOWN'));

    if (cloudClient.isPaired()) {
      queueViewTransition(refreshAuthorizedStoresInternal).catch(() => undefined);
    }
    authorizationRefreshTimer = setInterval(() => {
      if (!cloudClient.isPaired()) return;
      queueViewTransition(refreshAuthorizedStoresInternal).catch(() => undefined);
    }, AUTHORIZATION_REFRESH_MS);
    authorizationRefreshTimer.unref?.();
  });
}

app.on('before-quit', () => {
  appQuitting = true;
  if (authorizationRefreshTimer) clearInterval(authorizationRefreshTimer);
  if (syncScheduler) syncScheduler.stop();
  stopForSystemEvent('APPLICATION_QUIT');
});
app.on('window-all-closed', () => {
  // R297 remains in the Electron main process so the five-minute scheduler is
  // independent from the visible management window.
});
