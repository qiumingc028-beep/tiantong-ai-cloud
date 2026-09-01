'use strict';

const path = require('node:path');
const { pathToFileURL } = require('node:url');
const {
  classifyRequest,
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
const { createAutoSyncCoordinator } = require('./auto-sync');
const { METRIC_DEFINITIONS, buildRecognizerScript } = require('./page-recognizer');
const { CLIENT_VERSION, buildSyncPayload } = require('./sync-payload');
const { ROUTES, SNAPSHOT_SCRIPT, normalizeSnapshot } = require('./readonly-collector');
const {
  detectHumanActionFromUrl,
  hostnameForStatus,
  isAuditedMainFrameRoute,
  isAuthenticationPage,
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
const PAGE_RECOGNITION_INTERVAL_MS = 10_000;

const CHANNELS = Object.freeze({
  snapshot: 'workbench:snapshot',
  pair: 'workbench:pair',
  refreshStores: 'workbench:refresh-stores',
  selectStore: 'workbench:select-store',
  setSection: 'workbench:set-section',
  recognizePage: 'workbench:recognize-page',
  syncPage: 'workbench:sync-page',
  syncAllNow: 'workbench:sync-all-now',
  humanAction: 'workbench:human-action',
  status: 'workbench:status'
});

const WORKBENCH_SECTIONS = Object.freeze(new Set(['business', 'stores', 'sync', 'alerts']));

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
let automaticSyncCoordinator = null;
let automaticSyncViewHidden = false;
let automaticSyncRestoreState = null;
let activeSection = 'business';
let lastOpenDiagnostic = Object.freeze({
  stage: 'IDLE',
  code: null,
  host: null,
  updatedAt: null
});
const statusByStore = new Map();
const securedPartitions = new Set();
const remoteSessions = new Map();
const pageRecognitionByStore = new Map();
const cloudSyncByStore = new Map();
const automaticRetryByStore = new Map();
const metricDefinitionByKey = new Map(METRIC_DEFINITIONS.map((item) => [item.key, item]));

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
    lastAttemptAt: typeof raw.last_attempt_at === 'string' ? raw.last_attempt_at.slice(0, 40) : null,
    lastSyncAt: typeof raw.last_sync_at === 'string' ? raw.last_sync_at.slice(0, 40) : null,
    nextSyncAt: typeof raw.next_sync_at === 'string' ? raw.next_sync_at.slice(0, 40) : null,
    retryCount: Number.isSafeInteger(raw.retry_count) ? raw.retry_count : 0,
    syncEnabled: !raw.sync_policy || raw.sync_policy.enabled !== false,
    intervalSeconds: raw.sync_policy && Number.isSafeInteger(raw.sync_policy.interval_seconds)
      ? raw.sync_policy.interval_seconds : 300
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
    lastAttemptAt: state.lastAttemptAt || store.lastAttemptAt,
    lastSyncAt: store.lastSyncAt,
    nextSyncAt: state.nextSyncAt || store.nextSyncAt,
    retryCount: Number.isSafeInteger(state.retryCount) ? state.retryCount : store.retryCount,
    syncEnabled: store.syncEnabled,
    intervalSeconds: store.intervalSeconds
  });
}

function snapshot() {
  const activeStoreUuid = activeContext ? activeContext.store.storeUuid : null;
  return Object.freeze({
    stores: stores.map(safeStoreState),
    activeStoreUuid,
    clientStatus: remoteViewAccessPaused ? 'PAUSED' : 'READY',
    cloudStatus,
    readOnly: true,
    collectionEnabled: true,
    cloudDataSyncEnabled: Boolean(cloudClient && cloudClient.isPaired()),
    pageRecognition: activeStoreUuid
      ? safePageRecognition(activeStoreUuid)
      : Object.freeze({ status: 'NO_ACTIVE_STORE', pageType: null, title: null, host: null, capturedAt: null, metrics: [] }),
    cloudSync: activeStoreUuid
      ? safeCloudSync(activeStoreUuid)
      : Object.freeze({ status: 'NO_ACTIVE_STORE', syncedAt: null, capturedAt: null, accepted: 0, batchId: null, error: null }),
    automaticSync: automaticSyncCoordinator
      ? automaticSyncCoordinator.snapshot()
      : Object.freeze({ enabled: true, status: 'STARTING', intervalMs: 300_000, nextRunAt: null, lastCycleFinishedAt: null, currentStoreUuid: null, total: 0, succeeded: 0, skipped: 0, failed: 0, results: [] }),
    businessWriteStatus: 'UNVERIFIED',
    blockedBusinessWriteAttempts,
    activeSection,
    openDiagnostic: lastOpenDiagnostic
  });
}

function safeCloudSync(storeUuid) {
  return cloudSyncByStore.get(storeUuid) || Object.freeze({
    status: 'READY_TO_SYNC',
    syncedAt: null,
    capturedAt: null,
    accepted: 0,
    batchId: null,
    error: null
  });
}

function safePageRecognition(storeUuid) {
  return pageRecognitionByStore.get(storeUuid) || Object.freeze({
    status: 'WAITING_PAGE',
    pageType: null,
    title: null,
    host: null,
    capturedAt: null,
    metrics: []
  });
}

function sendSnapshot() {
  if (shellWindow && !shellWindow.isDestroyed()) {
    shellWindow.webContents.send(CHANNELS.status, snapshot());
  }
}

function setOpenDiagnostic(stage, code = null, rawUrl = null) {
  lastOpenDiagnostic = Object.freeze({
    stage: String(stage || 'UNKNOWN').slice(0, 64),
    code: code ? String(code).slice(0, 96) : null,
    host: rawUrl ? hostnameForStatus(rawUrl) : null,
    updatedAt: new Date().toISOString()
  });
  sendSnapshot();
}

function setStoreStatus(storeUuid, status, reason = null, host = null) {
  statusByStore.set(storeUuid, {
    status,
    reason,
    host,
    updatedAt: new Date().toISOString()
  });
  sendSnapshot();
}

function sanitizeRecognitionResult(storeUuid, raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('PAGE_RECOGNITION_INVALID');
  const parsed = parseAllowedHttpsUrl(raw.url);
  if (!parsed) throw new Error('PAGE_RECOGNITION_INVALID');
  const allowedPageTypes = new Set([
    'JDM_HOME', 'BUSINESS_INTELLIGENCE', 'ORDERS', 'ORDER_EXPORT',
    'PRODUCTS', 'INVENTORY', 'REFUNDS', 'PROMOTION', 'JD_PAGE'
  ]);
  const pageType = allowedPageTypes.has(raw.pageType) ? raw.pageType : 'JD_PAGE';
  const title = String(raw.title || '')
    .replace(/[\u0000-\u001f\u007f]/g, '')
    .trim()
    .slice(0, 160);
  const seen = new Set();
  const metrics = [];
  for (const candidate of Array.isArray(raw.metrics) ? raw.metrics.slice(0, 40) : []) {
    const definition = candidate && metricDefinitionByKey.get(candidate.key);
    const value = String((candidate && candidate.value) || '').trim().slice(0, 32);
    if (
      !definition ||
      seen.has(definition.key) ||
      !/^(?:[¥￥]\s*)?(?:[-—]+|\d[\d,]*(?:\.\d+)?(?:%|万|亿|元|笔|单|人|次|件|个|SKU)?)$/i.test(value)
    ) {
      continue;
    }
    seen.add(definition.key);
    metrics.push(Object.freeze({
      key: definition.key,
      label: definition.label,
      category: definition.category,
      value
    }));
  }
  return Object.freeze({
    storeUuid,
    status: metrics.length ? 'RECOGNIZED' : 'PAGE_RECOGNIZED_NO_METRICS',
    pageType,
    title: title || null,
    host: parsed.hostname,
    capturedAt: new Date().toISOString(),
    metrics: Object.freeze(metrics)
  });
}

function mergeRecognitionResults(storeUuid, results) {
  const first = results[0];
  const byKey = new Map();
  for (const result of results) {
    for (const metric of result.metrics) {
      const existing = byKey.get(metric.key);
      if (!existing || (/^[-—]+$/.test(existing.value) && !/^[-—]+$/.test(metric.value))) {
        byKey.set(metric.key, metric);
      }
    }
  }
  const metrics = Object.freeze([...byKey.values()]);
  return Object.freeze({
    storeUuid,
    status: metrics.length ? 'RECOGNIZED' : 'PAGE_RECOGNIZED_NO_METRICS',
    pageType: first.pageType,
    title: first.title,
    host: first.host,
    capturedAt: new Date().toISOString(),
    metrics
  });
}

async function runPageRecognition(context) {
  if (
    !context ||
    context.disposed ||
    activeContext !== context ||
    context.view.webContents.isDestroyed()
  ) {
    return null;
  }
  const currentUrl = context.view.webContents.getURL();
  if (!parseAllowedHttpsUrl(currentUrl) || isAuthenticationPage(currentUrl)) {
    pageRecognitionByStore.set(context.store.storeUuid, Object.freeze({
      status: isAuthenticationPage(currentUrl) ? 'WAITING_LOGIN' : 'WAITING_PAGE',
      pageType: null,
      title: null,
      host: hostnameForStatus(currentUrl),
      capturedAt: null,
      metrics: []
    }));
    sendSnapshot();
    return null;
  }
  try {
    const mainFrame = context.view.webContents.mainFrame;
    const frames = [mainFrame, ...mainFrame.framesInSubtree]
      .filter((frame, index, all) => all.indexOf(frame) === index)
      .filter((frame) => parseAllowedHttpsUrl(frame.url))
      .slice(0, 20);
    const rawResults = await Promise.all(frames.map(
      (frame) => frame.executeJavaScript(buildRecognizerScript()).catch(() => null)
    ));
    if (context.disposed || activeContext !== context) return null;
    const sanitized = [];
    for (const raw of rawResults) {
      if (!raw) continue;
      try {
        sanitized.push(sanitizeRecognitionResult(context.store.storeUuid, raw));
      } catch (_error) {
        // Ignore an individual detached or unexpected subframe.
      }
    }
    if (!sanitized.length) throw new Error('PAGE_RECOGNITION_INVALID');
    const result = mergeRecognitionResults(context.store.storeUuid, sanitized);
    pageRecognitionByStore.set(context.store.storeUuid, result);
    sendSnapshot();
    return result;
  } catch (_error) {
    if (!context.disposed && activeContext === context) {
      pageRecognitionByStore.set(context.store.storeUuid, Object.freeze({
        status: 'RECOGNITION_FAILED',
        pageType: null,
        title: null,
        host: hostnameForStatus(currentUrl),
        capturedAt: new Date().toISOString(),
        metrics: []
      }));
      sendSnapshot();
    }
    return null;
  }
}

function startPageRecognition(context) {
  if (context.recognitionTimer) clearInterval(context.recognitionTimer);
  setTimeout(() => runPageRecognition(context), 800);
  context.recognitionTimer = setInterval(
    () => runPageRecognition(context),
    PAGE_RECOGNITION_INTERVAL_MS
  );
  context.recognitionTimer.unref?.();
}

function markHumanActionVisible(storeUuid, reason, rawUrl) {
  const host = hostnameForStatus(rawUrl);
  setOpenDiagnostic('HUMAN_ACTION_READY', reason, rawUrl);
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
    if (storeUuid) setOpenDiagnostic('DOWNLOAD_BLOCKED', 'DOWNLOAD_DISABLED', JD_HOME_URL);
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
    collectionContext.store.partition === partition &&
    collectionContext.targetSession === targetSession &&
    !collectionContext.view.webContents.isDestroyed() &&
    Date.now() < authorizationLeaseExpiresAt
  );
  return visibleActive || collectorActive;
}

function currentUrlForStore(storeUuid) {
  if (
    collectionContext && !collectionContext.disposed &&
    collectionContext.store.storeUuid === storeUuid &&
    !collectionContext.view.webContents.isDestroyed()
  ) return collectionContext.view.webContents.getURL();
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

  targetSession.webRequest.onBeforeRequest({ urls: ['<all_urls>'] }, (details, callback) => {
    const decision = classifyRequest({
      url: details.url,
      method: details.method,
      resourceType: details.resourceType,
      currentMainFrameUrl: currentUrlForStore(storeUuid),
      isActive: isPartitionActive(storeUuid, partition, targetSession),
      isMainFrameSource: isActiveMainFrameSource(details, storeUuid),
      initiator: details.initiator
    });
    if (decision.allow) return callback({ cancel: false });
    if (decision.code === 'READ_ONLY_WRITE_BLOCKED') blockedBusinessWriteAttempts += 1;
    if (decision.code !== 'INACTIVE_PARTITION') {
      setOpenDiagnostic('REQUEST_BLOCKED', decision.code, details.url);
    }
    return callback({ cancel: true });
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
    if (!isAuditedMainFrameRoute(targetUrl)) {
      event.preventDefault();
      setOpenDiagnostic('NAVIGATION_BLOCKED', 'EXTERNAL_NAVIGATION_BLOCKED', targetUrl);
    }
  };

  contents.on('will-navigate', guardNavigation);
  contents.on('will-redirect', guardNavigation);
  contents.on('will-frame-navigate', (event) => {
    // `will-frame-navigate` also fires for JD's nested security frames. Those
    // requests are already governed by the centralized session firewall. Do
    // not treat a subframe navigation as if the visible top-level page left an
    // audited route, otherwise a harmless login-security iframe tears down the
    // entire store view.
    if (event.isMainFrame) guardNavigation(event, event.url);
  });
  contents.setWindowOpenHandler(({ url }) => {
    if (isAuditedMainFrameRoute(url)) {
      setTimeout(() => {
        if (!context.disposed && !contents.isDestroyed()) {
          contents.loadURL(url).catch(() => {
            setOpenDiagnostic('PAGE_LOAD_FAILED', 'NEW_WINDOW_ROUTE_FAILED', url);
          });
        }
      }, 0);
    } else {
      setOpenDiagnostic('NEW_WINDOW_BLOCKED', 'EXTERNAL_NEW_WINDOW_BLOCKED', url);
    }
    return { action: 'deny' };
  });

  contents.on('page-title-updated', (_event, title) => {
    if (/验证码|安全验证|风险验证|风控|身份核验/.test(String(title || ''))) {
      markHumanActionVisible(storeUuid, 'RISK_OR_CAPTCHA', contents.getURL());
    }
  });

  contents.on('did-navigate', (_event, targetUrl) => {
    if (context.disposed) return;
    const reason = detectHumanActionFromUrl(targetUrl);
    if (reason) {
      markHumanActionVisible(storeUuid, reason, targetUrl);
      return;
    }
    if (isAuthenticationPage(targetUrl)) {
      setOpenDiagnostic('LOGIN_PAGE_READY', null, targetUrl);
      setStoreStatus(storeUuid, 'HUMAN_ACTION_REQUIRED', 'LOGIN_REQUIRED', hostnameForStatus(targetUrl));
      return;
    }
    const parsed = parseAllowedHttpsUrl(targetUrl);
    if (parsed) {
      setOpenDiagnostic('STORE_PAGE_READY', null, targetUrl);
      setStoreStatus(storeUuid, 'READY_READ_ONLY', null, parsed.hostname);
    }
  });

  contents.on('did-finish-load', () => {
    if (!context.disposed) {
      setOpenDiagnostic('PAGE_FINISHED', null, contents.getURL());
      setTimeout(() => runPageRecognition(context), 800);
    }
  });

  contents.on('did-fail-load', (_event, errorCode, _errorDescription, validatedUrl, isMainFrame) => {
    if (!isMainFrame || context.disposed || errorCode === -3) return;
    setOpenDiagnostic('PAGE_LOAD_FAILED', String(errorCode), validatedUrl || JD_HOME_URL);
    setStoreStatus(
      storeUuid,
      'HUMAN_ACTION_REQUIRED',
      'PAGE_LOAD_FAILED',
      hostnameForStatus(validatedUrl || JD_HOME_URL)
    );
  });

  contents.on('render-process-gone', () => {
    if (!context.disposed) {
      setOpenDiagnostic('RENDERER_STOPPED', 'REMOTE_RENDERER_STOPPED');
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

function setRemoteViewVisibility() {
  if (!activeContext || activeContext.disposed || activeContext.view.webContents.isDestroyed()) return;
  activeContext.view.setVisible(activeSection === 'business' && !automaticSyncViewHidden);
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
  if (context.recognitionTimer) clearInterval(context.recognitionTimer);
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

async function closeCollectionView() {
  if (!collectionContext) return;
  const context = collectionContext;
  collectionContext = null;
  context.disposed = true;
  if (!context.view.webContents.isDestroyed()) context.view.webContents.stop();
  await closeRemoteContents(context.view.webContents);
}

async function loadCollectorSnapshot(store, routeUrl) {
  const targetSession = session.fromPartition(store.partition, { cache: true });
  if (!targetSession.isPersistent()) throw Object.assign(new Error('COLLECTOR_PAGE_LOAD_FAILED'), { code: 'COLLECTOR_PAGE_LOAD_FAILED' });
  installRemoteSessionSecurity(targetSession, store.storeUuid, store.partition);
  const view = new WebContentsView({
    webPreferences: {
      partition: store.partition,
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
  collectionContext = { store, targetSession, view, disposed: false };
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

async function syncOrderDetailDatasets(store) {
  const collectedAt = new Date().toISOString();
  const routes = [
    ['fulfillment', ROUTES.fulfillment],
    ['aftersales', ROUTES.aftersales],
    ['abnormal', ROUTES.abnormal]
  ];
  for (const [kind, routeUrl] of routes) {
    const pageSnapshot = await loadCollectorSnapshot(store, routeUrl);
    for (const dataset of normalizeSnapshot(kind, pageSnapshot, collectedAt)) {
      const payload = {
        store_id: store.storeId,
        subject_id: store.subjectId,
        dataset_type: dataset.datasetType,
        source_period: dataset.sourcePeriod,
        collected_at: collectedAt,
        idempotency_key: `r297-${dataset.datasetType}-${store.storeId}-${Date.parse(collectedAt)}`,
        client_version: CLIENT_VERSION,
        records: dataset.records
      };
      const result = await cloudClient.sync(payload);
      if (!result || result.ok !== true) throw Object.assign(new Error('SYNC_UPLOAD_REJECTED'), { code: 'SYNC_UPLOAD_REJECTED' });
    }
  }
}

async function selectStoreInternal(storeUuidInput, { activateBusiness = true } = {}) {
  const storeUuid = canonicalStoreUuid(storeUuidInput);
  setOpenDiagnostic('SELECT_RECEIVED');
  if (remoteViewAccessPaused) {
    setOpenDiagnostic('OPEN_FAILED', 'REMOTE_VIEW_PAUSED');
    throw new Error('REMOTE_VIEW_PAUSED');
  }
  if (!cloudClient || !cloudClient.isPaired()) {
    setOpenDiagnostic('OPEN_FAILED', 'DEVICE_NOT_PAIRED');
    throw new Error('DEVICE_NOT_PAIRED');
  }

  // The UI can still show the last successful cloud state while the short
  // authorization lease is approaching expiry. Refresh it inside the queued
  // open operation so a click never races the periodic refresh timer.
  if (cloudStatus !== 'CONNECTED' || Date.now() + 15_000 >= authorizationLeaseExpiresAt) {
    setOpenDiagnostic('REFRESHING_AUTHORIZATION');
    try {
      await refreshAuthorizedStoresInternal();
    } catch (error) {
      setOpenDiagnostic('OPEN_FAILED', cloudErrorCode(error));
      throw error;
    }
  }
  if (cloudStatus !== 'CONNECTED' || Date.now() >= authorizationLeaseExpiresAt) {
    setOpenDiagnostic('OPEN_FAILED', 'CLOUD_AUTHORIZATION_REQUIRED');
    throw new Error('CLOUD_AUTHORIZATION_REQUIRED');
  }
  setOpenDiagnostic('AUTHORIZATION_READY');
  const store = stores.find((item) => item.storeUuid === storeUuid);
  if (!store) {
    setOpenDiagnostic('OPEN_FAILED', 'STORE_NOT_AUTHORIZED');
    throw new Error('STORE_NOT_AUTHORIZED');
  }
  if (activeContext && activeContext.store.storeUuid === storeUuid) {
    if (activateBusiness) activeSection = 'business';
    setRemoteViewVisibility();
    sendSnapshot();
    return snapshot();
  }

  await destroyActiveView('STORE_SWITCHED');
  // Lock/suspend can occur while the previous view is being torn down. Do not
  // create a replacement after the system event has revoked remote access.
  if (remoteViewAccessPaused) {
    setOpenDiagnostic('OPEN_FAILED', 'REMOTE_VIEW_PAUSED');
    throw new Error('REMOTE_VIEW_PAUSED');
  }
  const partition = store.partition;
  const targetSession = session.fromPartition(partition, { cache: true });
  if (!targetSession.isPersistent()) {
    setOpenDiagnostic('OPEN_FAILED', 'STORE_SESSION_NOT_PERSISTENT');
    throw new Error('STORE_SESSION_NOT_PERSISTENT');
  }
  setOpenDiagnostic('SESSION_READY');
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

  const context = { store, partition, targetSession, view, disposed: false, recognitionTimer: null };
  activeContext = context;
  if (activateBusiness) activeSection = 'business';
  setOpenDiagnostic('VIEW_CREATED');
  attachRemoteViewSecurity(context);
  shellWindow.contentView.addChildView(view);
  setOpenDiagnostic('VIEW_ATTACHED');
  setRemoteBounds();
  setRemoteViewVisibility();
  startPageRecognition(context);
  setStoreStatus(storeUuid, 'LOADING', null, 'shop.jd.com');

  try {
    setOpenDiagnostic('LOAD_STARTED', null, JD_HOME_URL);
    await view.webContents.loadURL(JD_HOME_URL);
    if (!context.disposed) setOpenDiagnostic('LOAD_COMPLETE', null, view.webContents.getURL());
  } catch (error) {
    if (!context.disposed) {
      setOpenDiagnostic('PAGE_LOAD_FAILED', cloudErrorCode(error), JD_HOME_URL);
      setStoreStatus(storeUuid, 'HUMAN_ACTION_REQUIRED', 'PAGE_LOAD_FAILED', 'shop.jd.com');
    }
  }
  return snapshot();
}

function setActiveSectionInternal(sectionInput) {
  const section = String(sectionInput || '').trim().toLowerCase();
  if (!WORKBENCH_SECTIONS.has(section)) throw new Error('WORKBENCH_SECTION_INVALID');
  activeSection = section;
  setRemoteViewVisibility();
  sendSnapshot();
  return snapshot();
}

async function recognizeActivePageInternal() {
  if (!activeContext || activeContext.disposed) throw new Error('STORE_NOT_OPEN');
  await runPageRecognition(activeContext);
  activeSection = 'sync';
  setRemoteViewVisibility();
  sendSnapshot();
  return snapshot();
}

async function syncActivePageInternal({ activateSync = true } = {}) {
  if (!activeContext || activeContext.disposed) throw new Error('STORE_NOT_OPEN');
  if (!cloudClient || !cloudClient.isPaired()) throw new Error('DEVICE_NOT_PAIRED');
  const context = activeContext;
  const recognition = await runPageRecognition(context);
  if (!recognition || recognition.status !== 'RECOGNIZED' || !recognition.metrics.length) {
    throw new Error('NO_RECOGNIZED_METRICS');
  }
  if (activateSync) activeSection = 'sync';
  cloudSyncByStore.set(context.store.storeUuid, Object.freeze({
    status: 'SYNCING',
    syncedAt: null,
    capturedAt: recognition.capturedAt,
    accepted: 0,
    batchId: null,
    error: null
  }));
  setRemoteViewVisibility();
  sendSnapshot();
  try {
    const payload = buildSyncPayload({ store: context.store, recognition });
    const result = await cloudClient.sync(payload);
    if (!result || result.ok !== true || typeof result.batch_id !== 'string') {
      throw new Error('CLOUD_RESPONSE_INVALID');
    }
    const syncedAt = new Date().toISOString();
    cloudSyncByStore.set(context.store.storeUuid, Object.freeze({
      status: result.duplicate ? 'ALREADY_SYNCED' : 'SYNCED',
      syncedAt,
      capturedAt: recognition.capturedAt,
      accepted: Number.isSafeInteger(result.accepted) ? result.accepted : 0,
      batchId: result.batch_id.slice(0, 64),
      error: null
    }));
    stores = stores.map((store) => store.storeUuid === context.store.storeUuid
      ? Object.freeze({ ...store, lastSyncAt: syncedAt })
      : store);
    sendSnapshot();
    return snapshot();
  } catch (error) {
    const code = cloudErrorCode(error);
    cloudSyncByStore.set(context.store.storeUuid, Object.freeze({
      status: 'SYNC_FAILED',
      syncedAt: null,
      capturedAt: recognition.capturedAt,
      accepted: 0,
      batchId: null,
      error: code
    }));
    sendSnapshot();
    throw error;
  }
}

function automaticSyncCanRun() {
  return Boolean(
    shellWindow && !shellWindow.isDestroyed() &&
    cloudClient && cloudClient.isPaired() &&
    cloudStatus === 'CONNECTED' &&
    !remoteViewAccessPaused
  );
}

async function syncAuthorizedStoreAutomatically(store) {
  const authorizedStore = stores.find((item) => item.storeUuid === store.storeUuid);
  if (!authorizedStore) throw new Error('STORE_NOT_AUTHORIZED');
  const lastAttemptAt = new Date().toISOString();
  await cloudClient.heartbeat({
    status: 'SYNCING', storeId: authorizedStore.storeId, lastAttemptAt,
    nextSyncAt: null, retryCount: automaticRetryByStore.get(store.storeUuid) || 0
  });
  try {
    const result = await queueViewTransition(async () => {
      await selectStoreInternal(store.storeUuid, { activateBusiness: false });
      await syncActivePageInternal({ activateSync: false });
      await syncOrderDetailDatasets(authorizedStore);
      return safeCloudSync(store.storeUuid);
    });
    automaticRetryByStore.set(store.storeUuid, 0);
    const nextSyncAt = new Date(Date.now() + authorizedStore.intervalSeconds * 1000).toISOString();
    await cloudClient.heartbeat({
      status: 'IDLE', storeId: authorizedStore.storeId, lastAttemptAt,
      nextSyncAt, retryCount: 0
    });
    return Object.freeze({ status: result.status, skipped: false });
  } catch (error) {
    const code = cloudErrorCode(error).toUpperCase();
    const retryCount = Math.min((automaticRetryByStore.get(store.storeUuid) || 0) + 1, 5);
    automaticRetryByStore.set(store.storeUuid, retryCount);
    const human = ['LOGIN_EXPIRED', 'RISK_CONTROL', 'CAPTCHA_REQUIRED'].includes(code);
    const allowedError = [
      'CLOUD_CONNECTION_FAILED', 'COLLECTOR_PAGE_LOAD_FAILED', 'COLLECTOR_SCHEMA_MISMATCH',
      'COLLECTOR_EMPTY', 'SYNC_UPLOAD_REJECTED'
    ].includes(code) ? code : 'COLLECTOR_SCHEMA_MISMATCH';
    await cloudClient.heartbeat({
      status: human ? 'HUMAN_ACTION_REQUIRED' : 'ERROR',
      storeId: authorizedStore.storeId,
      reasonCode: human ? code : allowedError,
      lastAttemptAt,
      nextSyncAt: human ? null : new Date(Date.now() + Math.min(60_000 * (3 ** (retryCount - 1)), 600_000)).toISOString(),
      retryCount
    }).catch(() => undefined);
    throw error;
  }
}

async function beginAutomaticSyncCycle() {
  automaticSyncRestoreState = Object.freeze({
    storeUuid: activeContext && activeContext.store.storeUuid,
    section: activeSection
  });
  automaticSyncViewHidden = true;
  setRemoteViewVisibility();
  sendSnapshot();
}

async function finishAutomaticSyncCycle() {
  const restore = automaticSyncRestoreState;
  automaticSyncRestoreState = null;
  try {
    if (restore && restore.storeUuid && stores.some((store) => store.storeUuid === restore.storeUuid)) {
      await queueViewTransition(() => selectStoreInternal(restore.storeUuid, { activateBusiness: false }));
    } else if (activeContext) {
      await queueViewTransition(() => destroyActiveView('AUTO_SYNC_BACKGROUND_COMPLETE'));
    }
    if (restore && WORKBENCH_SECTIONS.has(restore.section)) activeSection = restore.section;
  } catch (_error) {
    // A best-effort UI restore must never disable the next automatic cycle.
  } finally {
    automaticSyncViewHidden = false;
    setRemoteViewVisibility();
    sendSnapshot();
  }
}

function initializeAutomaticSync() {
  automaticSyncCoordinator = createAutoSyncCoordinator({
    listStores: () => stores.filter((store) => store.syncEnabled).map(safeStoreState),
    syncStore: syncAuthorizedStoreAutomatically,
    canRun: automaticSyncCanRun,
    beforeCycle: beginAutomaticSyncCycle,
    afterCycle: finishAutomaticSyncCycle,
    onStateChange: () => sendSnapshot()
  });
  automaticSyncCoordinator.start();
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
  const result = await refreshAuthorizedStoresInternal();
  automaticSyncCoordinator && automaticSyncCoordinator.wake(5000);
  return result;
}

function reportManualHumanAction(storeUuidInput, reasonInput) {
  const storeUuid = canonicalStoreUuid(storeUuidInput);
  const reason = String(reasonInput || '').trim().toUpperCase();
  if (!HUMAN_ACTION_REASONS.has(reason)) throw new Error('HUMAN_ACTION_REASON_INVALID');
  if (!stores.some((item) => item.storeUuid === storeUuid)) throw new Error('STORE_NOT_AUTHORIZED');
  markHumanActionVisible(storeUuid, reason, currentUrlForStore(storeUuid) || JD_HOME_URL);
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
    if (automaticSyncViewHidden && automaticSyncRestoreState) {
      automaticSyncRestoreState = Object.freeze({
        storeUuid: canonicalStoreUuid(storeUuid),
        section: 'business'
      });
    }
    return queueViewTransition(() => selectStoreInternal(storeUuid));
  });
  ipcMain.handle(CHANNELS.setSection, (event, section) => {
    validateShellSender(event);
    if (automaticSyncViewHidden && automaticSyncRestoreState) {
      automaticSyncRestoreState = Object.freeze({ ...automaticSyncRestoreState, section });
    }
    return setActiveSectionInternal(section);
  });
  ipcMain.handle(CHANNELS.recognizePage, (event) => {
    validateShellSender(event);
    return recognizeActivePageInternal();
  });
  ipcMain.handle(CHANNELS.syncPage, (event) => {
    validateShellSender(event);
    return queueViewTransition(syncActivePageInternal);
  });
  ipcMain.handle(CHANNELS.syncAllNow, (event) => {
    validateShellSender(event);
    if (!automaticSyncCoordinator) throw new Error('AUTO_SYNC_NOT_READY');
    return automaticSyncCoordinator.runNow();
  });
  ipcMain.handle(CHANNELS.humanAction, (event, storeUuid, reason) => {
    validateShellSender(event);
    return reportManualHumanAction(storeUuid, reason);
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

function createShellWindow() {
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
  shellWindow.on('close', () => {
    if (activeContext) {
      activeContext.disposed = true;
      if (activeContext.recognitionTimer) clearInterval(activeContext.recognitionTimer);
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
  shellWindow.once('ready-to-show', () => shellWindow.show());
  shellWindow.loadURL(SHELL_URL);
}

function stopForSystemEvent(reason) {
  // This flag and destroyActiveView's activeContext revocation happen before
  // either function reaches an await. A lock cannot sit behind a slow loadURL
  // or another queued transition.
  remoteViewAccessPaused = true;
  automaticSyncCoordinator && automaticSyncCoordinator.wake(60_000);
  sendSnapshot();
  Promise.all([destroyActiveView(reason), closeCollectionView()])
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
      automaticSyncCoordinator && automaticSyncCoordinator.wake(5000);
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
    shellWindow.show();
    shellWindow.focus();
  });

  app.whenReady().then(() => {
    cloudClient = createCloudClient({
      net,
      safeStorage,
      identityPath: path.join(app.getPath('userData'), 'jd-workbench-device.json')
    });
    try {
      cloudStatus = cloudClient.readIdentity() ? 'CONNECTING' : 'NOT_PAIRED';
    } catch (error) {
      cloudStatus = cloudErrorCode(error);
    }

    registerAppProtocol();
    installDownloadBlock(session.defaultSession);
    registerIpcHandlers();
    createShellWindow();
    initializeAutomaticSync();
    if (app.isPackaged && process.platform === 'win32') {
      app.setLoginItemSettings({ openAtLogin: true });
    }

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
  if (authorizationRefreshTimer) clearInterval(authorizationRefreshTimer);
  automaticSyncCoordinator && automaticSyncCoordinator.stop();
  stopForSystemEvent('APPLICATION_QUIT');
});
app.on('window-all-closed', () => { /* keep local scheduler alive; quit explicitly */ });
