#!/usr/bin/env node
'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync, spawn, spawnSync } = require('node:child_process');
const { EventEmitter } = require('node:events');

const REPOSITORY_ROOT = path.resolve(__dirname, '..');
const SHA_RE = /^[0-9a-f]{40}$/;
const RUN_RE = /^[A-Za-z0-9._:-]{16,128}$/;
const SIGNATURE_RE = /^[A-Za-z0-9_-]{342}$/;
const RAW_FIELDS = ['event', 'observed_at', 'release_sha', 'store_id'];
const SESSION_STATUSES = new Set(['ACTIVE', 'LOGIN_REQUIRED', 'REVOKED', 'EXPIRED', 'HUMAN_ACTION_REQUIRED']);
const SIGNED_EVENT_FIELDS = [
  'namespace', 'tenant_id', 'company_id', 'store_id', 'platform', 'release_sha',
  'run_id', 'run_attempt', 'challenge', 'event_type', 'issuer', 'observed_at',
  'sequence', 'nonce', 'key_id', 'payload', 'signature'
];
const REQUIRED_INPUTS = [
  'R297_WINDOWS_CANARY_BACKEND_HTTPS_URL', 'R297_EXPECTED_RELEASE_SHA',
  'R297_ACCEPTANCE_RUN_ID',
  'R297_OWNER_STORAGE_STATE_PATH', 'R297_LIVE_OUTPUT_DIR',
  'R297_EVIDENCE_NAMESPACE', 'R297_EVIDENCE_TENANT_ID', 'R297_EVIDENCE_COMPANY_ID',
  'R297_EVIDENCE_STORE_ID', 'R297_EVIDENCE_CROSS_STORE_ID', 'R297_EVIDENCE_CROSS_TENANT_STORE_ID',
  'R297_PAGE_EVENT_RECEIVER_ACK_PATH', 'R297_AUTHENTICATED_OBSERVER_ACK_PATH'
];

function required(name) {
  const value = String(process.env[name] || '').trim();
  if (!value) throw new Error(`缺少受控配置：${name}`);
  return value;
}

function positiveInteger(name) {
  const raw = required(name);
  if (!/^[1-9][0-9]*$/.test(raw)) throw new Error(`受控配置无效：${name}`);
  return Number(raw);
}

function loadConfig() {
  const missing = REQUIRED_INPUTS.filter(name => !String(process.env[name] || '').trim());
  if (missing.length) throw new Error(`缺少受控配置：${missing.join(',')}`);
  const originUrl = new URL(required('R297_WINDOWS_CANARY_BACKEND_HTTPS_URL'));
  if (originUrl.protocol !== 'https:' || originUrl.username || originUrl.password || originUrl.search || originUrl.hash) {
    throw new Error('受控入口必须是无凭据、无查询参数的HTTPS地址');
  }
  if (originUrl.pathname !== '/' && originUrl.pathname !== '') throw new Error('受控入口必须是HTTPS站点根地址');
  const releaseSha = required('R297_EXPECTED_RELEASE_SHA').toLowerCase();
  if (!SHA_RE.test(releaseSha)) throw new Error('R297_EXPECTED_RELEASE_SHA无效');
  const runId = required('R297_ACCEPTANCE_RUN_ID');
  if (!RUN_RE.test(runId)) throw new Error('R297_ACCEPTANCE_RUN_ID无效');
  const storageState = path.resolve(required('R297_OWNER_STORAGE_STATE_PATH'));
  const outputDir = path.resolve(required('R297_LIVE_OUTPUT_DIR'));
  const receiverAckPath = path.resolve(required('R297_PAGE_EVENT_RECEIVER_ACK_PATH'));
  const observerAckPath = path.resolve(required('R297_AUTHENTICATED_OBSERVER_ACK_PATH'));
  if (!fs.statSync(storageState).isFile()) throw new Error('Owner浏览器会话文件不存在');
  if (receiverAckPath === observerAckPath) throw new Error('Receiver与Observer回执路径必须分离');
  const acknowledgementInOutput = [receiverAckPath, observerAckPath].some(candidate => {
    const relative = path.relative(outputDir, candidate);
    return relative === '' || (!relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative));
  });
  if (acknowledgementInOutput) throw new Error('服务端回执必须位于浏览器验收输出目录之外');
  return Object.freeze({
    origin: originUrl.origin, releaseSha, runId,
    storageState, outputDir, receiverAckPath, observerAckPath,
    namespace: required('R297_EVIDENCE_NAMESPACE'),
    tenantId: positiveInteger('R297_EVIDENCE_TENANT_ID'),
    companyId: positiveInteger('R297_EVIDENCE_COMPANY_ID'),
    storeId: positiveInteger('R297_EVIDENCE_STORE_ID'),
    crossStoreId: positiveInteger('R297_EVIDENCE_CROSS_STORE_ID'),
    crossTenantStoreId: positiveInteger('R297_EVIDENCE_CROSS_TENANT_STORE_ID'),
  });
}

function exactKeys(value, keys) {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value)
    && Object.keys(value).sort().join('\0') === [...keys].sort().join('\0'));
}

function sha256File(file) {
  return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
}

function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}

function waitForCondition(label, predicate, {timeoutMs, signal, pollMs = 50}) {
  return new Promise((resolve, reject) => {
    let timer = null;
    let settled = false;
    const finish = (error, value) => {
      if (settled) return;
      settled = true;
      if (timer !== null) clearTimeout(timer);
      if (signal) signal.removeEventListener('abort', aborted);
      error ? reject(error) : resolve(value);
    };
    const aborted = () => finish(new Error(`${label}已取消`));
    const deadline = Date.now() + timeoutMs;
    const poll = async () => {
      if (signal?.aborted) return aborted();
      try {
        const value = await predicate();
        if (value) return finish(null, value);
      } catch (error) { return finish(error); }
      if (Date.now() >= deadline) return finish(new Error(`${label}超时`));
      timer = setTimeout(poll, pollMs);
    };
    if (signal) signal.addEventListener('abort', aborted, {once: true});
    void poll();
  });
}

function readDigestBoundJson(file) {
  const sidecar = `${file}.sha256`;
  for (const candidate of [file, sidecar]) {
    const metadata = fs.lstatSync(candidate);
    if (!metadata.isFile() || metadata.isSymbolicLink() || metadata.nlink !== 1) {
      throw new Error('服务端回执文件无效');
    }
  }
  const content = fs.readFileSync(file);
  const digest = crypto.createHash('sha256').update(content).digest('hex');
  if (fs.readFileSync(sidecar, 'ascii') !== `${digest}  ${path.basename(file)}\n`) {
    throw new Error('服务端回执摘要无效');
  }
  return {event: JSON.parse(content), digest, content};
}

function verifySignedAcknowledgement(content, eventType, issuer, signal) {
  const script = [
    'import json,sys',
    'from datetime import datetime,timezone',
    'from ops.r297_evidence_events import verify_signed_event',
    'event=json.load(sys.stdin)',
    'verify_signed_event(event,event_type=sys.argv[1],issuer=sys.argv[2],environment="acceptance",now=datetime.now(timezone.utc))',
  ].join(';');
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new Error('服务端回执签名验证已取消'));
    const verifier = spawn('python3', ['-c', script, eventType, issuer], {
      cwd: REPOSITORY_ROOT, stdio: ['pipe', 'ignore', 'ignore']
    });
    let settled = false;
    let timer = null;
    let killTimer = null;
    let stopError = null;
    const finish = error => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      clearTimeout(killTimer);
      if (signal) signal.removeEventListener('abort', aborted);
      if (error) reject(error);
      else resolve();
    };
    const stop = message => {
      if (stopError) return;
      stopError = new Error(message);
      verifier.kill('SIGKILL');
      killTimer = setTimeout(() => finish(stopError), 2_000);
    };
    const aborted = () => stop('服务端回执签名验证已取消');
    timer = setTimeout(() => stop('服务端回执签名验证超时'), 10_000);
    if (signal) signal.addEventListener('abort', aborted, {once: true});
    verifier.stdin.on('error', () => {});
    verifier.once('error', () => finish(new Error('服务端回执签名验证失败')));
    verifier.once('close', code => finish(stopError || (code === 0 ? null : new Error('服务端回执签名验证失败'))));
    verifier.stdin.end(content);
  });
}

function assertCommonAcknowledgement(event, config, type, issuer, sequence) {
  assert.ok(exactKeys(event, SIGNED_EVENT_FIELDS), '服务端回执字段错误');
  const bindingMatches = event.namespace === config.namespace
    && event.tenant_id === config.tenantId
    && event.company_id === config.companyId
    && event.store_id === config.storeId
    && event.platform === 'jd'
    && event.release_sha === config.releaseSha
    && event.run_id === config.runId;
  if (!bindingMatches) throw new Error('服务端回执运行绑定错误');
  assert.deepEqual([event.event_type, event.issuer, event.sequence], [type, issuer, sequence], '服务端回执角色错误');
  if (!RUN_RE.test(String(event.nonce || ''))
      || !RUN_RE.test(String(event.key_id || ''))
      || !SIGNATURE_RE.test(String(event.signature || ''))) {
    throw new Error('服务端回执认证字段无效');
  }
}

function assertPageReceiverAcknowledgement(event, config, rawEvent, artifact) {
  assertCommonAcknowledgement(event, config, 'web_page_close', 'page_event_receiver', 1);
  assert.equal(event.observed_at, rawEvent.observed_at, 'Receiver回执时间未绑定原始事件');
  assert.ok(exactKeys(event.payload, [
    'closed', 'source', 'artifact_evidence_sha256', 'artifact_archive_sha256',
    'artifact_id', 'artifact_name', 'workflow_run_id'
  ]), 'Receiver回执payload字段错误');
  assert.equal(event.payload.closed, true);
  assert.equal(event.payload.source, 'browser_pagehide');
  assert.equal(event.payload.artifact_evidence_sha256, artifact.evidenceSha);
  assert.equal(event.payload.artifact_archive_sha256, artifact.archiveSha);
  assert.ok(Number.isInteger(event.payload.artifact_id) && event.payload.artifact_id > 0);
  assert.match(String(event.payload.artifact_name || ''), /^r297-native-pagehide-[A-Za-z0-9._-]+$/);
  assert.ok(Number.isInteger(event.payload.workflow_run_id) && event.payload.workflow_run_id > 0);
}

function assertObserverAcknowledgement(event, config, receiverEvent) {
  assertCommonAcknowledgement(event, config, 'authenticated_observer', 'authenticated_observer', 2);
  assert.ok(exactKeys(event.payload, [
    'subject_nonce', 'subject_event_sha256', 'scheduler_continues', 'observation_source',
    'database_read_only', 'cloud_cycles_before', 'cloud_cycles_after',
    'eligible_store_ids', 'collected_store_ids_after'
  ]), 'Observer回执payload字段错误');
  const subjectMatches = event.payload.subject_nonce === receiverEvent.nonce
    && event.payload.subject_event_sha256
      === crypto.createHash('sha256').update(canonicalJson(receiverEvent)).digest('hex');
  if (!subjectMatches) throw new Error('Observer回执主题绑定错误');
  if (event.run_attempt !== receiverEvent.run_attempt || event.challenge !== receiverEvent.challenge) {
    throw new Error('Observer回执受保护运行绑定错误');
  }
  assert.equal(event.payload.scheduler_continues, true, '独立Observer未证明云端继续运行');
  assert.equal(event.payload.observation_source, 'postgresql_scheduler_state');
  assert.equal(event.payload.database_read_only, true);
  assert.ok(event.payload.cloud_cycles_after > event.payload.cloud_cycles_before);
  assert.deepEqual(event.payload.eligible_store_ids, [config.storeId]);
  assert.deepEqual(event.payload.collected_store_ids_after, [config.storeId]);
}

async function waitForViewerReady(popup, storeId, signal) {
  const websocket = await popup.waitForEvent('websocket', {
    predicate: socket => {
      const url = new URL(socket.url());
      return url.protocol === 'wss:' && !url.search
        && url.pathname === `/jd-browser/novnc/${storeId}/websockify`;
    },
    timeout: 30_000
  });
  const frames = {sent: false, received: false};
  const sent = () => { frames.sent = true; };
  const received = () => { frames.received = true; };
  websocket.on('framesent', sent);
  websocket.on('framereceived', received);
  try {
    await Promise.all([
      waitForCondition('Viewer WebSocket握手', () => frames.sent && frames.received, {
        timeoutMs: 20_000, signal
      }),
    popup.waitForFunction(() => {
      const canvas = document.querySelector('#noVNC_canvas');
      return document.documentElement.classList.contains('noVNC_connected')
        && canvas instanceof HTMLCanvasElement && canvas.width > 0 && canvas.height > 0
        && getComputedStyle(canvas).visibility !== 'hidden';
    }, undefined, {timeout: 30_000})
    ]);
  } finally {
    websocket.off('framesent', sent);
    websocket.off('framereceived', received);
  }
  if (signal?.aborted) throw new Error('Viewer就绪验证已取消');
  return {websocket, path: new URL(websocket.url()).pathname};
}

function safeUrl(input) {
  try { const url = new URL(input); return `${url.origin}${url.pathname}`; }
  catch (_error) { return 'invalid-url'; }
}

function bounded(label, promise, milliseconds) {
  let timer;
  return Promise.race([
    promise,
    new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`${label}超时`)), milliseconds); }),
  ]).finally(() => clearTimeout(timer));
}

async function browserJson(page, url, options, expectedStatus) {
  return bounded(`请求${url}`, page.evaluate(async ({ url, options, expectedStatus }) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10_000);
    try {
      const response = await fetch(url, {
        credentials: 'include', cache: 'no-store', ...options, signal: controller.signal
      });
      let body = null;
      try { body = await response.json(); } catch (_error) {}
      return { status: response.status, body, expectedStatus };
    } finally {
      clearTimeout(timer);
    }
  }, { url, options, expectedStatus }), 12_000);
}

function assertResponse(result, status, keys, label) {
  assert.equal(result.status, status, `${label} HTTP状态错误`);
  assert.ok(exactKeys(result.body, keys), `${label}响应字段错误`);
  return result.body;
}

async function waitForSession(page, config) {
  const deadline = Date.now() + 45_000;
  while (Date.now() < deadline) {
    const result = await browserJson(page, `/api/jd-workbench/stores/${config.storeId}/login-session`, undefined, 200);
    const body = assertResponse(result, 200, ['store_id', 'status'], '查询会话');
    assert.equal(body.store_id, config.storeId);
    assert.ok(SESSION_STATUSES.has(body.status), '登录状态不属于正式枚举');
    if (body.status === 'ACTIVE' || body.status === 'HUMAN_ACTION_REQUIRED') return body.status;
    await page.waitForTimeout(1000);
  }
  throw new Error('Runtime未在45秒内进入可验证状态');
}

async function ticketNegativeChecks(page, config) {
  return page.evaluate(async ({ storeId, crossStoreId, crossTenantStoreId }) => {
    const timedFetch = async (url, options) => {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 10_000);
      try { return await fetch(url, {...options, signal: controller.signal}); }
      finally { clearTimeout(timer); }
    };
    const issue = async () => {
      const response = await timedFetch(`/api/jd-workbench/stores/${storeId}/login-ticket`, {
        method: 'POST', credentials: 'include', cache: 'no-store',
        referrerPolicy: 'no-referrer', headers: {'Content-Type': 'application/json'}, body: '{}'
      });
      const body = await response.json();
      if (response.status !== 200 || Object.keys(body).sort().join(',') !== 'expires_in,ticket'
          || typeof body.ticket !== 'string' || !body.ticket || !Number.isInteger(body.expires_in)
          || body.expires_in <= 0 || body.expires_in > 120) throw new Error('ticket合同无效');
      return body;
    };
    const exchange = (id, ticket) => timedFetch(`/jd-browser/novnc/${id}/exchange`, {
      method: 'POST', credentials: 'include', cache: 'no-store', referrerPolicy: 'no-referrer',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ticket})
    });
    const replayTicket = await issue();
    const first = await exchange(storeId, replayTicket.ticket);
    const replay = await exchange(storeId, replayTicket.ticket);
    const scopedTicket = await issue();
    const crossStore = await exchange(crossStoreId, scopedTicket.ticket);
    const crossTenant = await timedFetch(`/api/jd-workbench/stores/${crossTenantStoreId}/login-ticket`, {
      method: 'POST', credentials: 'include', cache: 'no-store', referrerPolicy: 'no-referrer',
      headers: {'Content-Type': 'application/json'}, body: '{}'
    });
    const expiredTicket = await issue();
    await new Promise(resolve => setTimeout(resolve, (expiredTicket.expires_in + 1) * 1000));
    const expired = await exchange(storeId, expiredTicket.ticket);
    return {
      first: first.status, replay: replay.status, cross_store: crossStore.status,
      cross_tenant: crossTenant.status, expired: expired.status
    };
  }, { storeId: config.storeId, crossStoreId: config.crossStoreId, crossTenantStoreId: config.crossTenantStoreId });
}

async function selfTest() {
  assert.equal(SIGNATURE_RE.test('s'.repeat(342)), true);
  assert.equal(SIGNATURE_RE.test('s'.repeat(128)), false);
  const controller = new AbortController();
  let polls = 0;
  const pending = waitForCondition('自检等待', () => { polls += 1; return false; }, {
    timeoutMs: 5_000, pollMs: 5, signal: controller.signal
  });
  setTimeout(() => controller.abort(), 15);
  await assert.rejects(pending, /已取消/);
  const stoppedAt = polls;
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.equal(polls, stoppedAt, '取消后仍在轮询');
  await assert.rejects(waitForCondition('自检超时', () => false, {
    timeoutMs: 15, pollMs: 5
  }), /超时/);

  const socket = new EventEmitter();
  socket.url = () => 'wss://acceptance.invalid/jd-browser/novnc/3/websockify';
  const popup = {
    waitForEvent: async () => {
      setImmediate(() => { socket.emit('framesent'); socket.emit('framereceived'); });
      return socket;
    },
    waitForFunction: async callback => assert.match(callback.toString(), /noVNC_connected/)
  };
  const readyViewer = await waitForViewerReady(popup, 3);
  assert.equal(readyViewer.path, '/jd-browser/novnc/3/websockify');
  assert.equal(readyViewer.websocket, socket);

  const config = {
    namespace: 'r297-acceptance-test', tenantId: 1, companyId: 2, storeId: 3,
    releaseSha: '1'.repeat(40), runId: 'r297-run-test-0001'
  };
  const rawEvent = {event: 'web_page_close', observed_at: '2026-09-08T00:00:00.000Z', store_id: 3, release_sha: config.releaseSha};
  const receiver = {
    ...{namespace: config.namespace, tenant_id: 1, company_id: 2, store_id: 3, platform: 'jd', release_sha: config.releaseSha,
    run_id: config.runId, run_attempt: 1, challenge: 'challenge-test-0001'},
    event_type: 'web_page_close', issuer: 'page_event_receiver', observed_at: rawEvent.observed_at,
    sequence: 1, nonce: 'receiver-nonce-0001', key_id: 'receiver-key-0001', signature: 's'.repeat(342),
    payload: {closed: true, source: 'browser_pagehide', artifact_evidence_sha256: '2'.repeat(64),
      artifact_archive_sha256: '3'.repeat(64), artifact_id: 1,
      artifact_name: 'r297-native-pagehide-test', workflow_run_id: 2}
  };
  assertPageReceiverAcknowledgement(receiver, config, rawEvent, {evidenceSha: '2'.repeat(64), archiveSha: '3'.repeat(64)});
  process.stdout.write('R297_LIVE_FRONTEND_SELF_TEST=PASS\n');
}

async function main() {
  if (process.argv.includes('--self-test')) return selfTest();
  const config = loadConfig();
  if (process.argv.includes('--check-config')) {
    process.stdout.write(`R297_LIVE_FRONTEND_PREFLIGHT=READY\nR297_RELEASE_SHA=${config.releaseSha}\nR297_RUN_ID=${config.runId}\n`);
    return;
  }
  let checkoutSha;
  try {
    checkoutSha = execFileSync('git', ['rev-parse', 'HEAD'], {cwd: REPOSITORY_ROOT, encoding: 'utf8'}).trim();
    const trackedChanges = execFileSync(
      'git', ['status', '--porcelain', '--untracked-files=no'], {cwd: REPOSITORY_ROOT, encoding: 'utf8'}
    ).trim();
    if (trackedChanges) throw new Error('runner checkout存在已跟踪修改');
  } catch (error) {
    throw new Error(`runner源码绑定检查失败：${error && error.message ? error.message : String(error)}`);
  }
  if (checkoutSha !== config.releaseSha) throw new Error('runner checkout HEAD与验收release不一致');
  const { chromium } = require('playwright');
  if (fs.existsSync(config.outputDir) && fs.readdirSync(config.outputDir).length) {
    throw new Error('验收输出目录必须为空，禁止覆盖或混用旧证据');
  }
  for (const acknowledgement of [config.receiverAckPath, config.observerAckPath]) {
    if (fs.existsSync(acknowledgement) || fs.existsSync(`${acknowledgement}.sha256`)) {
      throw new Error('服务端回执路径必须为空，禁止复用旧回执');
    }
  }
  fs.mkdirSync(config.outputDir, { recursive: true, mode: 0o700 });
  fs.chmodSync(config.outputDir, 0o700);
  const pagehideDir = path.join(config.outputDir, 'pagehide-artifact');
  fs.mkdirSync(pagehideDir, { recursive: true, mode: 0o700 });
  const operations = [];
  const nativeEvents = [];
  const rawEvents = [];
  const consoleErrors = [];
  const pageErrors = [];
  const failedRequests = [];
  let syntheticRejected;
  let browser;
  let context;
  let sessionCleanupRequired = false;
  let sessionRevoked = false;
  let createSettlement = Promise.resolve();
  let cleanupPromise = null;
  let stopping = false;
  let result = 'BLOCK';
  let firstBlocker = '';
  const runController = new AbortController();

  async function cleanup() {
    if (cleanupPromise) return cleanupPromise;
    runController.abort();
    cleanupPromise = (async () => {
      if (sessionCleanupRequired && !sessionRevoked && context) {
        try {
          await createSettlement;
          const response = await context.request.delete(
            `${config.origin}/api/jd-workbench/stores/${config.storeId}/login-session`,
            {timeout: 10_000}
          );
          if (response.status() !== 200) throw new Error(`HTTP ${response.status()}`);
          const body = await response.json();
          if (!exactKeys(body, ['ok', 'store_id', 'status']) || body.ok !== true
              || body.store_id !== config.storeId || body.status !== 'REVOKED') {
            throw new Error('响应字段无效');
          }
          sessionRevoked = true;
        } catch (error) {
          const cleanupError = `会话清理失败：${error && error.message ? error.message : String(error)}`;
          firstBlocker = firstBlocker ? `${firstBlocker}；${cleanupError}` : cleanupError;
        }
      }
      if (browser) await browser.close().catch(() => {});
    })();
    try { await cleanupPromise; }
    finally { cleanupPromise = null; }
  }

  async function stopForSignal(signal, code) {
    if (stopping) return;
    stopping = true;
    result = 'BLOCK';
    firstBlocker = `执行器收到${signal}`;
    await cleanup();
    process.exitCode = code;
  }
  process.once('SIGINT', () => { void stopForSignal('SIGINT', 130); });
  process.once('SIGTERM', () => { void stopForSignal('SIGTERM', 143); });

  try {
    if (runController.signal.aborted) throw new Error('执行器已取消');
    browser = await chromium.launch({ headless: true });
    if (runController.signal.aborted) throw new Error('执行器已取消');
    context = await browser.newContext({ storageState: config.storageState });
    if (runController.signal.aborted) throw new Error('执行器已取消');
    context.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text().slice(0, 300)); });
    context.on('weberror', webError => {
      const error = webError.error();
      pageErrors.push(String(error && error.message || error).slice(0, 300));
    });
    context.on('requestfailed', request => failedRequests.push({url: safeUrl(request.url()), error: request.failure()?.errorText || 'failed'}));
    let ownerPage = null;
    await context.exposeBinding('__tiantongR297AuthenticatedObserver', (source, payload) => {
      if (source.page !== ownerPage) return;
      if (typeof payload === 'string') rawEvents.push(JSON.parse(payload));
      else if (payload && payload.kind === 'native') nativeEvents.push(payload.event);
    });
    await context.addInitScript(() => {
      addEventListener('pagehide', event => {
        globalThis.__tiantongR297AuthenticatedObserver({kind: 'native', event: {
          event: event.type, observed_at: new Date().toISOString(),
          event_is_trusted: event.isTrusted, event_constructor: event.constructor.name
        }});
      });
    });
    const page = await context.newPage();
    ownerPage = page;
    operations.push({operation: 'goto', path: '/stores.html', observed_at: new Date().toISOString()});
    await bounded('店铺页面加载', page.goto(`${config.origin}/stores.html`, {waitUntil: 'networkidle'}), 30_000);

    const health = await browserJson(page, '/api/health', undefined, 200);
    assert.equal(health.status, 200, 'Backend health HTTP状态错误');
    assert.equal(health.body?.release?.commit, config.releaseSha, '运行环境release与候选不一致');
    assert.equal(health.body?.status, 'running');
    assert.equal(health.body?.database, true);
    assert.equal(health.body?.redis, true);
    assert.equal(health.body?.worker, true);

    const me = await browserJson(page, '/api/me', undefined, 200);
    assert.equal(me.status, 200);
    assert.equal(me.body?.role_code, 'owner', '当前浏览器不是Owner身份');
    const stores = await browserJson(page, '/api/stores', undefined, 200);
    assert.equal(stores.status, 200);
    assert.ok(Array.isArray(stores.body));
    const store = stores.body.find(item => item?.id === config.storeId);
    assert.ok(store && store.platform === 'jd' && store.active === true, 'Owner没有目标京东店铺权限');

    const acceptance = await browserJson(page, `/api/jd-workbench/stores/${config.storeId}/acceptance-status`, undefined, 200);
    const accepted = assertResponse(acceptance, 200, [
      'release_sha', 'run_id', 'namespace', 'tenant_id', 'company_id', 'store_id', 'platform',
      'completed_cycle_count', 'interval_seconds', 'next_sync_in_seconds', 'latest_completed_at', 'observed_at'
    ], '验收绑定');
    assert.deepEqual(
      [accepted.release_sha, accepted.run_id, accepted.namespace, accepted.tenant_id, accepted.company_id, accepted.store_id, accepted.platform],
      [config.releaseSha, config.runId, config.namespace, config.tenantId, config.companyId, config.storeId, 'jd'],
      '验收运行scope不匹配'
    );

    const row = page.locator('#stores tr').filter({has: page.locator('td:first-child', {hasText: String(config.storeId)})}).first();
    await bounded('目标店铺行加载', row.waitFor({state: 'visible'}), 15_000);
    const createPath = `/api/jd-workbench/stores/${config.storeId}/login-session`;
    const createRequest = page.waitForRequest(request => {
      const matches = request.method() === 'POST' && new URL(request.url()).pathname === createPath;
      if (matches) sessionCleanupRequired = true;
      return matches;
    });
    const createResponse = page.waitForResponse(response => response.request().method() === 'POST'
      && new URL(response.url()).pathname === createPath);
    createSettlement = bounded(
      '等待创建会话请求终态', createResponse.then(() => undefined, () => undefined), 35_000
    ).catch(() => undefined);
    if (runController.signal.aborted) throw new Error('执行器已取消');
    await row.getByRole('button', {name: /京东登录|重新验证/}).click();
    await bounded('创建会话请求', createRequest, 10_000);
    const createHttp = await bounded('创建会话', createResponse, 35_000);
    assert.equal(createHttp.status(), 200, '创建会话HTTP状态错误');
    const createBody = await createHttp.json();
    assert.ok(exactKeys(createBody, ['store_id', 'status', 'expires_in']), '创建会话响应字段错误');
    assert.equal(createBody.store_id, config.storeId);
    assert.equal(createBody.status, 'LOGIN_REQUIRED');
    assert.ok(Number.isInteger(createBody.expires_in) && createBody.expires_in > 0 && createBody.expires_in <= 600,
      '创建会话TTL错误');
    const sessionStatus = await waitForSession(page, config);
    await page.waitForFunction(id => {
      const rows = [...document.querySelectorAll('#stores tr')];
      const row = rows.find(value => value.querySelector('td')?.textContent.trim() === String(id));
      const button = row && [...row.querySelectorAll('button')].find(value => value.textContent.includes('打开受控验证窗口'));
      return Boolean(button && !button.disabled);
    }, config.storeId);

    const popupPromise = page.waitForEvent('popup', {timeout: 10_000});
    const popup = await bounded('受控登录窗口打开', Promise.all([
      popupPromise, row.getByRole('button', {name: '打开受控验证窗口'}).click()
    ]).then(([opened]) => opened), 10_000);
    const [, viewer] = await Promise.all([
      popup.waitForURL(`**/jd-browser/novnc/${config.storeId}/vnc.html`, {timeout: 30_000}),
      waitForViewerReady(popup, config.storeId, runController.signal)
    ]);
    const viewerCookies = (await context.cookies()).filter(cookie => cookie.name === 'jd_browser_session');
    assert.equal(viewerCookies.length, 1, 'HttpOnly Viewer Cookie缺失');
    assert.equal(viewerCookies[0].httpOnly, true);
    assert.equal(viewerCookies[0].secure, true);
    assert.equal(viewerCookies[0].sameSite, 'Strict');

    const negative = await bounded('ticket拒绝矩阵', ticketNegativeChecks(page, config), 140_000);
    assert.equal(negative.first, 204);
    assert.equal(negative.replay, 401);
    assert.equal(negative.cross_store, 401);
    assert.ok([403, 404].includes(negative.cross_tenant));
    assert.equal(negative.expired, 401);

    const redactSelectors = ['#userInfo', '#stores td:nth-child(3)', '#stores td:nth-child(4)', '#stores td:nth-child(5)', '#stores td:nth-child(7)', '#stores td:nth-child(9)'];
    await page.addStyleTag({content: `${redactSelectors.join(',')}{filter:blur(12px)!important;color:transparent!important}`});
    const screenshotPath = path.join(config.outputDir, `r297-owner-ui-redacted-${config.releaseSha}.png`);
    await page.screenshot({path: screenshotPath, fullPage: true});
    fs.chmodSync(screenshotPath, 0o600);

    syntheticRejected = await page.evaluate(storeId => {
      const reporter = R297OwnerLogin.createPageCloseReporter({getReleaseSha: () => '0'.repeat(40)});
      return {
        constructed_event: reporter.report(new PageTransitionEvent('pagehide'), [storeId]),
        plain_object: reporter.report({type: 'pagehide', isTrusted: true}, [storeId])
      };
    }, config.storeId);
    assert.deepEqual(syntheticRejected, {constructed_event: false, plain_object: false});
    operations.push({operation: 'goto', path: '/login.html', observed_at: new Date().toISOString()});
    await page.goto(`${config.origin}/login.html`, {waitUntil: 'domcontentloaded'});
    await waitForCondition('原生pagehide事件', () => nativeEvents.length >= 1 && rawEvents.length >= 1, {
      timeoutMs: 5_000, signal: runController.signal
    });
    assert.equal(nativeEvents.length, 1);
    assert.deepEqual(nativeEvents[0], {
      event: 'pagehide', observed_at: nativeEvents[0].observed_at,
      event_is_trusted: true, event_constructor: 'PageTransitionEvent'
    });
    assert.equal(rawEvents.length, 1);
    assert.deepEqual(Object.keys(rawEvents[0]).sort(), RAW_FIELDS);
    assert.deepEqual(
      [rawEvents[0].event, rawEvents[0].store_id, rawEvents[0].release_sha],
      ['web_page_close', config.storeId, config.releaseSha]
    );

    const evidenceName = `r297-native-pagehide-evidence-${config.releaseSha}.json`;
    const evidencePath = path.join(pagehideDir, evidenceName);
    const evidence = {
      schema_version: '1.0', release_sha: config.releaseSha, generator_sha: config.releaseSha,
      frontend_source_diff: 'EMPTY', playwright_operations: operations,
      event_listener: 'window.addEventListener("pagehide", handler)', native_events: nativeEvents,
      raw_events: rawEvents, synthetic_event_rejected: syntheticRejected
    };
    fs.writeFileSync(evidencePath, `${JSON.stringify(evidence, null, 2)}\n`, {mode: 0o444});
    const evidenceSha = sha256File(evidencePath);
    fs.writeFileSync(`${evidencePath}.sha256`, `${evidenceSha}  ${evidenceName}\n`, {mode: 0o444});
    const artifactManifest = path.join(pagehideDir, `r297-native-pagehide-manifest-${config.releaseSha}.json`);
    fs.writeFileSync(artifactManifest, `${JSON.stringify({
      schema_version: '1.0', release_sha: config.releaseSha,
      evidence_file: evidenceName, evidence_sha256: evidenceSha
    }, null, 2)}\n`, {mode: 0o444});
    const archivePath = path.join(config.outputDir, `r297-native-pagehide-${config.releaseSha}.zip`);
    const zip = spawnSync('zip', ['-j', '-X', archivePath, evidencePath, `${evidencePath}.sha256`, artifactManifest], {encoding: 'utf8'});
    if (zip.status !== 0) throw new Error(`pagehide归档失败：${zip.stderr.trim()}`);
    fs.chmodSync(archivePath, 0o444);
    const artifact = {evidenceSha, archiveSha: sha256File(archivePath)};
    const receiver = await waitForCondition('Receiver持久接收回执', () => {
      if (!fs.existsSync(config.receiverAckPath) || !fs.existsSync(`${config.receiverAckPath}.sha256`)) return null;
      return readDigestBoundJson(config.receiverAckPath);
    }, {timeoutMs: 180_000, signal: runController.signal});
    await verifySignedAcknowledgement(receiver.content, 'web_page_close', 'page_event_receiver', runController.signal);
    assertPageReceiverAcknowledgement(receiver.event, config, rawEvents[0], artifact);
    const observer = await waitForCondition('独立Observer回执', () => {
      if (!fs.existsSync(config.observerAckPath) || !fs.existsSync(`${config.observerAckPath}.sha256`)) return null;
      return readDigestBoundJson(config.observerAckPath);
    }, {timeoutMs: 180_000, signal: runController.signal});
    await verifySignedAcknowledgement(
      observer.content, 'authenticated_observer', 'authenticated_observer', runController.signal
    );
    assertObserverAcknowledgement(observer.event, config, receiver.event);

    const controlPage = await context.newPage();
    await controlPage.goto(`${config.origin}/login.html`, {waitUntil: 'domcontentloaded'});
    const deleted = await browserJson(controlPage, `/api/jd-workbench/stores/${config.storeId}/login-session`, {method: 'DELETE'}, 200);
    const deletedBody = assertResponse(deleted, 200, ['ok', 'store_id', 'status'], '销毁会话');
    assert.deepEqual(deletedBody, {ok: true, store_id: config.storeId, status: 'REVOKED'});
    sessionRevoked = true;
    await waitForCondition('撤销后既有Viewer WebSocket关闭', () => viewer.websocket.isClosed(), {
      timeoutMs: 20_000, signal: runController.signal
    });
    const revoked = await browserJson(controlPage, `/jd-browser/novnc/${config.storeId}/vnc.html`, undefined, 401);
    assert.ok([401, 403].includes(revoked.status), '撤销后Viewer访问未失效');
    assert.equal(consoleErrors.length, 0, '浏览器控制台存在错误');
    assert.equal(pageErrors.length, 0, '浏览器存在未处理JavaScript错误');
    assert.equal(failedRequests.length, 0, '浏览器存在失败网络请求');

    const manifest = {
      schema_version: '1.0', result: 'PASS', release_sha: config.releaseSha, run_id: config.runId,
      scope: {namespace: config.namespace, tenant_id: config.tenantId, company_id: config.companyId, store_id: config.storeId, platform: 'jd'},
      session_status: sessionStatus, public_api: 'PASS', http_only_cookie: 'PASS',
      novnc_page: 'PASS', viewer_rfb_ready: 'PASS', websocket_path: viewer.path, ticket_rejections: negative,
      receiver_acknowledgement: {result: 'PASS', sha256: receiver.digest},
      authenticated_observer: {result: 'PASS', sha256: observer.digest},
      delete_and_revoke: 'PASS', existing_socket_revoked: 'PASS', pagehide_raw: 'PASS',
      screenshot: {file: path.basename(screenshotPath), sha256: sha256File(screenshotPath), redacted_selectors: redactSelectors},
      pagehide_artifact: {archive: path.basename(archivePath), archive_sha256: artifact.archiveSha, evidence_sha256: evidenceSha, manifest_sha256: sha256File(artifactManifest)},
      console_error_count: consoleErrors.length, page_error_count: pageErrors.length,
      failed_request_count: failedRequests.length,
      observer_handoff: 'ACKNOWLEDGED_BEFORE_SESSION_DELETE'
    };
    fs.writeFileSync(path.join(config.outputDir, 'r297-live-frontend-manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`, {mode: 0o444});
    result = 'PASS';
  } catch (error) {
    if (!firstBlocker) firstBlocker = error && error.message ? error.message : String(error);
    throw error;
  } finally {
    await cleanup();
    if (result !== 'PASS') {
      fs.mkdirSync(config.outputDir, {recursive: true, mode: 0o700});
      const diagnosticPath = path.join(config.outputDir, 'r297-live-frontend-diagnostic.json');
      fs.writeFileSync(diagnosticPath, `${JSON.stringify({
        schema_version: '1.0', result, release_sha: config.releaseSha, run_id: config.runId,
        first_blocker: firstBlocker || '未知阻塞', console_error_count: consoleErrors.length,
        page_error_count: pageErrors.length,
        failed_requests: failedRequests
      }, null, 2)}\n`, {mode: 0o444});
    }
    process.stdout.write(`R297_LIVE_FRONTEND_RESULT=${result}\n`);
    process.stdout.write(`R297_LIVE_FRONTEND_FIRST_BLOCKER=${firstBlocker || 'NONE'}\n`);
    process.stdout.write(`R297_AUTHENTICATED_OBSERVER_REQUIRED=${result === 'PASS' ? 'NO' : 'YES'}\n`);
    process.stdout.write(`R297_AUTHENTICATED_OBSERVER_ACKNOWLEDGED=${result === 'PASS' ? 'YES' : 'NO'}\n`);
  }
}

main().catch(error => {
  console.error(error && error.stack ? error.stack : error);
  process.exitCode = 1;
});
