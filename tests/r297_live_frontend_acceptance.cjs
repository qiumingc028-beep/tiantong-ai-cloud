#!/usr/bin/env node
'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync, spawnSync } = require('node:child_process');
const { EventEmitter } = require('node:events');

const REPOSITORY_ROOT = path.resolve(__dirname, '..');
const SHA_RE = /^[0-9a-f]{40}$/;
const RUN_RE = /^[A-Za-z0-9._:-]{16,128}$/;
const SIGNATURE_RE = /^[A-Za-z0-9_-]{342}$/;
const RUN_BINDING_TTL_MS = 5 * 60 * 1000;
const RUN_BINDING_FUTURE_SKEW_MS = 30 * 1000;
const RAW_FIELDS = ['event', 'observed_at', 'release_sha', 'store_id'];
const SESSION_STATUSES = new Set(['ACTIVE', 'LOGIN_REQUIRED', 'REVOKED', 'EXPIRED', 'HUMAN_ACTION_REQUIRED']);
const SIGNED_EVENT_FIELDS = [
  'namespace', 'tenant_id', 'company_id', 'store_id', 'platform', 'release_sha',
  'run_id', 'run_attempt', 'challenge', 'event_type', 'issuer', 'observed_at',
  'sequence', 'nonce', 'key_id', 'payload', 'signature'
];
const REQUIRED_INPUTS = [
  'R297_WINDOWS_CANARY_BACKEND_HTTPS_URL', 'R297_ACCEPTANCE_RUN_BINDING_PATH',
  'R297_ACK_BROKER_RESULT_PATH',
  'R297_OWNER_STORAGE_STATE_PATH', 'R297_LIVE_OUTPUT_DIR',
  'R297_EVIDENCE_CROSS_STORE_ID', 'R297_EVIDENCE_CROSS_TENANT_STORE_ID',
  'R297_PAGE_EVENT_RECEIVER_ACK_PATH', 'R297_AUTHENTICATED_OBSERVER_ACK_PATH'
];
const RUN_BINDING_FIELDS = [
  'namespace', 'tenant_id', 'company_id', 'store_id', 'platform', 'release_sha',
  'source_workflow_run_id', 'run_id', 'run_attempt', 'challenge', 'issued_at', 'consumed_at', 'state', 'event_receipts'
];
const BROKER_RESULT_FIELDS = [
  'schema_version', 'verifier_id', 'result', 'verified_at', 'binding_file_sha256',
  'receiver_ack_file_sha256', 'observer_ack_file_sha256', 'raw_event_sha256',
  'receiver_event_sha256', 'observer_event_sha256'
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
  const storageState = path.resolve(required('R297_OWNER_STORAGE_STATE_PATH'));
  const outputDir = path.resolve(required('R297_LIVE_OUTPUT_DIR'));
  const bindingPath = path.resolve(required('R297_ACCEPTANCE_RUN_BINDING_PATH'));
  const brokerResultPath = path.resolve(required('R297_ACK_BROKER_RESULT_PATH'));
  const receiverAckPath = path.resolve(required('R297_PAGE_EVENT_RECEIVER_ACK_PATH'));
  const observerAckPath = path.resolve(required('R297_AUTHENTICATED_OBSERVER_ACK_PATH'));
  if (!fs.statSync(storageState).isFile()) throw new Error('Owner浏览器会话文件不存在');
  if (receiverAckPath === observerAckPath) throw new Error('Receiver与Observer回执路径必须分离');
  const acknowledgementInOutput = [bindingPath, brokerResultPath, receiverAckPath, observerAckPath].some(candidate => {
    const relative = path.relative(outputDir, candidate);
    return relative === '' || (!relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative));
  });
  if (acknowledgementInOutput) throw new Error('服务端回执必须位于浏览器验收输出目录之外');
  const protectedBinding = readProtectedDigestBoundJson(bindingPath, {immutable: true});
  const binding = protectedBinding.event;
  if (!exactKeys(binding, RUN_BINDING_FIELDS)
      || !/^[a-z][a-z0-9_-]{7,79}$/.test(String(binding.namespace || ''))
      || ['default', 'development', 'production', 'acceptance', 'namespace', 'changeme'].includes(binding.namespace)
      || binding.platform !== 'jd' || !SHA_RE.test(String(binding.release_sha || ''))
      || !RUN_RE.test(String(binding.run_id || '')) || !RUN_RE.test(String(binding.challenge || ''))
      || !Number.isInteger(binding.run_attempt) || binding.run_attempt <= 0
      || !Number.isInteger(binding.source_workflow_run_id) || binding.source_workflow_run_id <= 0
      || !Number.isInteger(binding.tenant_id) || binding.tenant_id <= 0
      || !Number.isInteger(binding.company_id) || binding.company_id <= 0
      || !Number.isInteger(binding.store_id) || binding.store_id <= 0
      || binding.state !== 'issued' || binding.consumed_at !== null
      || !Array.isArray(binding.event_receipts) || binding.event_receipts.length !== 0
      || Number.isNaN(Date.parse(binding.issued_at))) {
    throw new Error('受保护run binding无效');
  }
  return Object.freeze({
    origin: originUrl.origin, releaseSha: binding.release_sha, runId: binding.run_id,
    runAttempt: binding.run_attempt, challenge: binding.challenge,
    namespace: binding.namespace, tenantId: binding.tenant_id,
    companyId: binding.company_id, storeId: binding.store_id,
    bindingIssuedAt: binding.issued_at,
    storageState, outputDir, bindingPath, bindingDigest: protectedBinding.digest,
    brokerResultPath, receiverAckPath, observerAckPath,
    crossStoreId: positiveInteger('R297_EVIDENCE_CROSS_STORE_ID'),
    crossTenantStoreId: positiveInteger('R297_EVIDENCE_CROSS_TENANT_STORE_ID'),
  });
}

function assertFreshIssuedBinding(binding, now = Date.now()) {
  const issuedAt = Date.parse(binding.issued_at);
  if (!Number.isFinite(issuedAt) || issuedAt > now + RUN_BINDING_FUTURE_SKEW_MS
      || now - issuedAt > RUN_BINDING_TTL_MS) {
    throw new Error('受保护run binding已过期或时间无效');
  }
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

function readProtectedDigestBoundJson(file, {immutable}) {
  const parent = fs.lstatSync(path.dirname(file));
  if (!parent.isDirectory() || parent.isSymbolicLink() || parent.uid !== 0 || (parent.mode & 0o022) !== 0) {
    throw new Error('受保护回执目录无效');
  }
  const readOne = candidate => {
    const descriptor = fs.openSync(candidate, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW || 0));
    try {
      const metadata = fs.fstatSync(descriptor);
      if (!metadata.isFile() || metadata.uid !== 0 || metadata.nlink !== 1
          || (metadata.mode & 0o022) !== 0 || (immutable && (metadata.mode & 0o200) !== 0)) {
        throw new Error('受保护回执文件无效');
      }
      return fs.readFileSync(descriptor);
    } finally { fs.closeSync(descriptor); }
  };
  const content = readOne(file);
  const sidecar = readOne(`${file}.sha256`).toString('ascii');
  const digest = crypto.createHash('sha256').update(content).digest('hex');
  if (sidecar !== `${digest}  ${path.basename(file)}\n`) throw new Error('受保护回执摘要无效');
  return {event: JSON.parse(content), digest, content};
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

function assertCommonAcknowledgement(event, config, type, issuer, sequence) {
  assert.ok(exactKeys(event, SIGNED_EVENT_FIELDS), '服务端回执字段错误');
  // 两份ACK彼此一致不代表当前运行；每份都必须匹配受保护run binding。
  const bindingMatches = event.namespace === config.namespace
    && event.tenant_id === config.tenantId
    && event.company_id === config.companyId
    && event.store_id === config.storeId
    && event.platform === 'jd'
    && event.release_sha === config.releaseSha
    && event.run_id === config.runId
    && event.run_attempt === config.runAttempt
    && event.challenge === config.challenge;
  if (!bindingMatches) throw new Error('服务端回执运行绑定错误');
  assert.deepEqual([event.event_type, event.issuer, event.sequence], [type, issuer, sequence], '服务端回执角色错误');
  if (!RUN_RE.test(String(event.nonce || '')) || !RUN_RE.test(String(event.key_id || ''))
      || !SIGNATURE_RE.test(String(event.signature || ''))) {
    throw new Error('服务端回执认证字段无效');
  }
}

function assertAcknowledgementPayload(event, fields, label) {
  const hasReceipt = Object.hasOwn(event.payload || {}, 'freshness_receipt');
  assert.ok(exactKeys(event.payload, hasReceipt ? [...fields, 'freshness_receipt'] : fields), `${label}回执payload字段错误`);
  if (!hasReceipt) return;
  const receipt = event.payload.freshness_receipt;
  assert.ok(exactKeys(receipt, ['received_at', 'freshness_verified', 'maximum_age_seconds']), '验鲜回执字段错误');
  assert.equal(receipt.freshness_verified, true);
  assert.equal(receipt.maximum_age_seconds, 300);
  assert.match(String(receipt.received_at), /(?:Z|[+-]\d{2}:\d{2})$/);
  const delay = Date.parse(receipt.received_at) - Date.parse(event.observed_at);
  assert.ok(Number.isFinite(delay) && delay >= 0 && delay <= 300_000, '验鲜回执时间错误');
  // This signed producer field is not proof of durable orchestrator verification.
}

function assertPageReceiverAcknowledgement(event, config, rawEvent, artifact) {
  assertCommonAcknowledgement(event, config, 'web_page_close', 'page_event_receiver', 1);
  assert.equal(event.observed_at, rawEvent.observed_at, 'Receiver回执时间未绑定原始事件');
  assertAcknowledgementPayload(event, [
    'closed', 'source', 'artifact_evidence_sha256', 'artifact_archive_sha256',
    'artifact_id', 'artifact_name', 'workflow_run_id'
  ], 'Receiver');
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
  assertAcknowledgementPayload(event, [
    'subject_nonce', 'subject_event_sha256', 'scheduler_continues', 'observation_source',
    'database_read_only', 'cloud_cycles_before', 'cloud_cycles_after',
    'eligible_store_ids', 'collected_store_ids_after'
  ], 'Observer');
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
  const storeScopeMatches = Array.isArray(event.payload.eligible_store_ids)
    && event.payload.eligible_store_ids.length === 1
    && event.payload.eligible_store_ids[0] === config.storeId
    && Array.isArray(event.payload.collected_store_ids_after)
    && event.payload.collected_store_ids_after.length === 1
    && event.payload.collected_store_ids_after[0] === config.storeId;
  if (!storeScopeMatches) throw new Error('Observer回执店铺范围错误');
}

function assertBrokerResult(broker, config, receiver, observer, rawEvent, now = Date.now()) {
  if (!exactKeys(broker.event, BROKER_RESULT_FIELDS)
      || broker.event.schema_version !== 1
      || broker.event.verifier_id !== 'tiantong-r297-ack-broker-v1'
      || broker.event.result !== 'VERIFIED'
      || Number.isNaN(Date.parse(broker.event.verified_at))
      || Date.parse(broker.event.verified_at) > now + 30000
      || now - Date.parse(broker.event.verified_at) > 12 * 60 * 60 * 1000
      || broker.event.binding_file_sha256 !== config.bindingDigest
      || broker.event.receiver_ack_file_sha256 !== receiver.digest
      || broker.event.observer_ack_file_sha256 !== observer.digest
      || broker.event.raw_event_sha256
        !== crypto.createHash('sha256').update(canonicalJson(rawEvent)).digest('hex')
      || broker.event.receiver_event_sha256
        !== crypto.createHash('sha256').update(canonicalJson(receiver.event)).digest('hex')
      || broker.event.observer_event_sha256
        !== crypto.createHash('sha256').update(canonicalJson(observer.event)).digest('hex')) {
    throw new Error('固定ACK broker验证结果与当前事务不匹配');
  }
}

function loadPersistedArtifact(config) {
  const pagehideDir = path.join(config.outputDir, 'pagehide-artifact');
  const evidenceName = `r297-native-pagehide-evidence-${config.releaseSha}.json`;
  const evidence = readDigestBoundJson(path.join(pagehideDir, evidenceName));
  const manifestPath = path.join(pagehideDir, `r297-native-pagehide-manifest-${config.releaseSha}.json`);
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  const archivePath = path.join(config.outputDir, `r297-native-pagehide-${config.releaseSha}.zip`);
  const rawEvents = evidence.event?.raw_events;
  if (!exactKeys(manifest, ['schema_version', 'release_sha', 'evidence_file', 'evidence_sha256'])
      || manifest.schema_version !== '1.0' || manifest.release_sha !== config.releaseSha
      || manifest.evidence_file !== evidenceName || manifest.evidence_sha256 !== evidence.digest
      || !Array.isArray(rawEvents) || rawEvents.length !== 1
      || !exactKeys(rawEvents[0], RAW_FIELDS)
      || rawEvents[0].release_sha !== config.releaseSha || rawEvents[0].store_id !== config.storeId
      || rawEvents[0].event !== 'web_page_close') {
    throw new Error('ACK恢复原始事件工件与当前事务不匹配');
  }
  const archive = fs.lstatSync(archivePath);
  if (!archive.isFile() || archive.isSymbolicLink() || archive.nlink !== 1) {
    throw new Error('ACK恢复归档无效');
  }
  return {rawEvent: rawEvents[0], evidenceSha: evidence.digest, archiveSha: sha256File(archivePath)};
}

function acknowledgementRecoveryState(files, exists = fs.existsSync) {
  const present = files.filter(file => exists(file)).length;
  if (!present) return 'NONE';
  if (present !== files.length) throw new Error('ACK恢复文件不完整或无可信broker来源');
  return 'COMPLETE';
}

function recoverAcknowledgedStage(config) {
  const files = [
    config.receiverAckPath, `${config.receiverAckPath}.sha256`,
    config.observerAckPath, `${config.observerAckPath}.sha256`,
    config.brokerResultPath, `${config.brokerResultPath}.sha256`
  ];
  if (acknowledgementRecoveryState(files) === 'NONE') return null;
  if (fs.existsSync(path.join(config.outputDir, 'r297-live-frontend-manifest.json'))) {
    throw new Error('当前验收事务已经完成，禁止重放Owner副作用');
  }
  const artifact = loadPersistedArtifact(config);
  const receiver = readDigestBoundJson(config.receiverAckPath);
  const observer = readDigestBoundJson(config.observerAckPath);
  const broker = readProtectedDigestBoundJson(config.brokerResultPath, {immutable: true});
  assertPageReceiverAcknowledgement(receiver.event, config, artifact.rawEvent, artifact);
  assertObserverAcknowledgement(observer.event, config, receiver.event);
  assertBrokerResult(broker, config, receiver, observer, artifact.rawEvent);
  return {receiver: receiver.digest, observer: observer.digest, broker: broker.digest};
}

async function revokeRecoveredSession(config, requestFactory) {
  const api = await requestFactory({baseURL: config.origin, storageState: config.storageState});
  try {
    const deleted = await api.delete(
      `/api/jd-workbench/stores/${config.storeId}/login-session`, {timeout: 10_000}
    );
    if (deleted.status() !== 200) throw new Error('ACK恢复会话撤销HTTP状态错误');
    const body = await deleted.json();
    if (!exactKeys(body, ['ok', 'store_id', 'status']) || body.ok !== true
        || body.store_id !== config.storeId || body.status !== 'REVOKED') {
      throw new Error('ACK恢复会话撤销响应无效');
    }
    const revoked = await api.get(`/jd-browser/novnc/${config.storeId}/vnc.html`, {
      timeout: 10_000, maxRedirects: 0
    });
    if (![401, 403].includes(revoked.status())) throw new Error('ACK恢复后Viewer访问未失效');
  } finally {
    await api.dispose();
  }
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
      const canvas = document.querySelector('#noVNC_container canvas');
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

function assertLiveViewerForRevocation(viewer) {
  assert.equal(viewer.websocket.isClosed(), false, 'DELETE前Viewer必须仍存活');
}

async function openRevocationViewer(storeId) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10_000);
  try {
    const request = (url, options) => fetch(url, options);
    const client = R297OwnerLogin.createClient(request);
    const open = () => R297OwnerLogin.openViewer({
      client, request, storeId, signal: controller.signal,
      isActive: () => !controller.signal.aborted
    });
    try { return await open(); }
    catch (error) {
      // The same client has recorded the acknowledged, completed intent.
      // Never create a replacement operation for PENDING/UNKNOWN or transport errors.
      if (error.status !== 409 || error.operation?.status !== 'SUCCESS'
          || !/^[0-9a-f]{32}$/.test(error.operation.operation_id || '')) throw error;
      return await open();
    }
  } finally { clearTimeout(timer); }
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
  const now = Date.parse('2026-09-08T00:05:00.000Z');
  assert.doesNotThrow(() => assertFreshIssuedBinding({issued_at: '2026-09-08T00:00:00.000Z'}, now));
  assert.throws(() => assertFreshIssuedBinding({issued_at: '2026-09-07T23:59:59.999Z'}, now), /已过期/);
  assert.throws(() => assertFreshIssuedBinding({issued_at: '2026-09-08T00:05:30.001Z'}, now), /已过期/);
  const recoveryCalls = [];
  await revokeRecoveredSession({origin: 'https://acceptance.invalid', storageState: {}, storeId: 3}, async () => ({
    delete: async (url, options) => {
      recoveryCalls.push(['DELETE', url, options.timeout]);
      return {status: () => 200, json: async () => ({ok: true, store_id: 3, status: 'REVOKED'})};
    },
    get: async (url, options) => {
      recoveryCalls.push(['GET', url, options.timeout, options.maxRedirects]);
      return {status: () => 401};
    },
    dispose: async () => recoveryCalls.push(['DISPOSE'])
  }));
  assert.deepEqual(recoveryCalls, [
    ['DELETE', '/api/jd-workbench/stores/3/login-session', 10_000],
    ['GET', '/jd-browser/novnc/3/vnc.html', 10_000, 0], ['DISPOSE']
  ]);
  assert.equal(acknowledgementRecoveryState(['a', 'b'], () => false), 'NONE');
  assert.equal(acknowledgementRecoveryState(['a', 'b'], () => true), 'COMPLETE');
  assert.throws(() => acknowledgementRecoveryState(['a', 'b'], value => value === 'a'), /文件不完整/);
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
  // noVNC 1.3 creates an unlabelled canvas inside #noVNC_container.
  class Canvas {}
  const canvas = Object.assign(new Canvas(), {width: 1024, height: 768});
  const viewerDocument = {
    querySelector: selector => selector === '#noVNC_container canvas' ? canvas : null,
    documentElement: {classList: {contains: name => name === 'noVNC_connected'}}
  };
  const popup = {
    waitForEvent: async () => {
      setImmediate(() => { socket.emit('framesent'); socket.emit('framereceived'); });
      return socket;
    },
    waitForFunction: async callback => {
      const evaluate = () => require('node:vm').runInNewContext(`(${callback.toString()})()`, {
        document: viewerDocument, HTMLCanvasElement: Canvas,
        getComputedStyle: () => ({visibility: 'visible'})
      });
      assert.equal(evaluate(), true, 'noVNC动态canvas未就绪');
      canvas.width = 0;
      assert.equal(evaluate(), false, '零尺寸canvas不得通过');
      canvas.width = 1024;
    }
  };
  const readyViewer = await waitForViewerReady(popup, 3);
  assert.equal(readyViewer.path, '/jd-browser/novnc/3/websockify');
  assert.equal(readyViewer.websocket, socket);
  assert.throws(() => assertLiveViewerForRevocation({
    websocket: {isClosed: () => true}
  }), /DELETE前Viewer必须仍存活/);
  assertLiveViewerForRevocation({websocket: {isClosed: () => false}});
  for (const status of ['SUCCESS', 'PENDING', 'UNKNOWN']) {
    let calls = 0;
    const ownerClient = require('../frontend/r297-owner-login.js');
    const pendingOpen = require('node:vm').runInNewContext(`(${openRevocationViewer.toString()})(3)`, {
      R297OwnerLogin: ownerClient, AbortController, setTimeout, clearTimeout,
      fetch: async (url, options) => {
        calls += 1;
        if (calls === 1) return {status: 409, json: async () => ({detail: {
          operation_id: 'a'.repeat(32), status, message: 'controlled operation receipt'
        }})};
        assert.equal(status, 'SUCCESS', '未知操作不能重试出票');
        if (calls === 2) {
          assert.equal(options.headers['x-owner-ack-operation-id'], 'a'.repeat(32));
          return {status: 200, json: async () => ({ticket: 'controlled-fixture', expires_in: 60})};
        }
        assert.equal(url, '/jd-browser/novnc/3/exchange');
        return {status: 204};
      }
    });
    if (status === 'SUCCESS') {
      assert.equal(await pendingOpen, '/jd-browser/novnc/3/vnc.html');
      assert.equal(calls, 3);
    } else {
      await assert.rejects(pendingOpen, error => error.operation.status === status);
      assert.equal(calls, 1);
    }
  }

  const config = {
    namespace: 'r297-acceptance-test', tenantId: 1, companyId: 2, storeId: 3,
    releaseSha: '1'.repeat(40), runId: 'r297-run-test-0001', runAttempt: 1,
    challenge: 'challenge-test-0001', bindingDigest: '4'.repeat(64)
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
  const observer = {
    ...{namespace: config.namespace, tenant_id: 1, company_id: 2, store_id: 3, platform: 'jd', release_sha: config.releaseSha,
      run_id: config.runId, run_attempt: 1, challenge: config.challenge},
    event_type: 'authenticated_observer', issuer: 'authenticated_observer', observed_at: '2026-09-08T00:00:01.000Z',
    sequence: 2, nonce: 'observer-nonce-000001', key_id: 'observer-key-000001', signature: 's'.repeat(342),
    payload: {
      subject_nonce: receiver.nonce,
      subject_event_sha256: crypto.createHash('sha256').update(canonicalJson(receiver)).digest('hex'),
      scheduler_continues: true, observation_source: 'postgresql_scheduler_state', database_read_only: true,
      cloud_cycles_before: 1, cloud_cycles_after: 2, eligible_store_ids: [3], collected_store_ids_after: [3]
    }
  };
  const receiverRecord = {event: receiver, digest: '5'.repeat(64)};
  const observerRecord = {event: observer, digest: '6'.repeat(64)};
  const broker = {digest: '7'.repeat(64), event: {
    schema_version: 1, verifier_id: 'tiantong-r297-ack-broker-v1', result: 'VERIFIED',
    verified_at: '2026-09-08T00:00:02.000Z', binding_file_sha256: config.bindingDigest,
    receiver_ack_file_sha256: receiverRecord.digest, observer_ack_file_sha256: observerRecord.digest,
    raw_event_sha256: crypto.createHash('sha256').update(canonicalJson(rawEvent)).digest('hex'),
    receiver_event_sha256: crypto.createHash('sha256').update(canonicalJson(receiver)).digest('hex'),
    observer_event_sha256: crypto.createHash('sha256').update(canonicalJson(observer)).digest('hex')
  }};
  assertPageReceiverAcknowledgement(receiver, config, rawEvent, {evidenceSha: '2'.repeat(64), archiveSha: '3'.repeat(64)});
  assertObserverAcknowledgement(observer, config, receiver);
  const brokerNow = Date.parse('2026-09-08T00:00:03.000Z');
  assertBrokerResult(broker, config, receiverRecord, observerRecord, rawEvent, brokerNow);
  assert.throws(() => assertBrokerResult(broker, config, receiverRecord, observerRecord, rawEvent,
    brokerNow + 12 * 60 * 60 * 1000), /当前事务不匹配/);
  assert.throws(() => assertBrokerResult(broker, config, receiverRecord, observerRecord, rawEvent,
    brokerNow - 32000), /当前事务不匹配/);
  assert.throws(() => assertPageReceiverAcknowledgement(
    {...receiver, run_attempt: 2}, config, rawEvent,
    {evidenceSha: '2'.repeat(64), archiveSha: '3'.repeat(64)}
  ), /运行绑定错误/);
  assert.throws(() => assertPageReceiverAcknowledgement(
    {...receiver, observed_at: '2026-09-08T00:00:03.000Z'}, config, rawEvent,
    {evidenceSha: '2'.repeat(64), archiveSha: '3'.repeat(64)}
  ), /时间未绑定/);
  assert.throws(() => assertObserverAcknowledgement(
    {...observer, run_attempt: 2}, config, receiver
  ), /运行绑定错误/);
  assert.throws(() => assertBrokerResult(
    {...broker, event: {...broker.event, binding_file_sha256: '8'.repeat(64)}},
    config, receiverRecord, observerRecord, rawEvent
  ), /当前事务不匹配/);
  const receipt = {received_at: '2026-09-08T00:00:01.000Z', freshness_verified: true, maximum_age_seconds: 300};
  const validateReceipt = value => assertPageReceiverAcknowledgement(
    {...receiver, payload: {...receiver.payload, freshness_receipt: value}}, config, rawEvent,
    {evidenceSha: '2'.repeat(64), archiveSha: '3'.repeat(64)}
  );
  validateReceipt(receipt);
  for (const invalid of [
    null, {...receipt, extra: true}, {...receipt, freshness_verified: false},
    {...receipt, maximum_age_seconds: '300'}, {...receipt, received_at: 'invalid'},
    {...receipt, received_at: '2026-09-08T00:05:01.000Z'},
    {...receipt, received_at: '2026-09-07T23:59:59.000Z'}
  ]) assert.throws(() => validateReceipt(invalid));
  process.stdout.write('R297_LIVE_RECEIPT_CONTRACT=PASS\n');
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
  const recovered = recoverAcknowledgedStage(config);
  if (recovered) {
    const { request } = require('playwright');
    await revokeRecoveredSession(config, options => request.newContext(options));
    process.stdout.write('R297_ACK_RECOVERY=PASS\n');
    process.stdout.write('R297_ACK_RECOVERY_REVOKED=PASS\n');
    process.stdout.write('R297_LIVE_FRONTEND_RESULT=ACK_RECOVERED_REVOKED\n');
    process.stdout.write('R297_ACK_RECOVERY_NOTE=ACK恢复不会生成完整验收PASS\n');
    process.exitCode = 2;
    return;
  }
  // Freshness gates new Owner side effects, but must not block idempotent
  // revocation of a fully verified ACK transaction after a runner crash.
  assertFreshIssuedBinding({issued_at: config.bindingIssuedAt});
  const { chromium } = require('playwright');
  if (fs.existsSync(config.outputDir) && fs.readdirSync(config.outputDir).length) {
    throw new Error('验收输出目录必须为空，禁止覆盖或混用旧证据');
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
    const acceptanceMatches = accepted.release_sha === config.releaseSha
      && accepted.run_id === config.runId && accepted.namespace === config.namespace
      && accepted.tenant_id === config.tenantId && accepted.company_id === config.companyId
      && accepted.store_id === config.storeId && accepted.platform === 'jd';
    if (!acceptanceMatches) throw new Error('验收运行scope不匹配');

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
    if (createBody.store_id !== config.storeId) throw new Error('创建会话店铺范围错误');
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
    if (rawEvents[0].event !== 'web_page_close' || rawEvents[0].store_id !== config.storeId
        || rawEvents[0].release_sha !== config.releaseSha) {
      throw new Error('浏览器原始事件绑定错误');
    }

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
    assertPageReceiverAcknowledgement(receiver.event, config, rawEvents[0], artifact);
    const observer = await waitForCondition('独立Observer回执', () => {
      if (!fs.existsSync(config.observerAckPath) || !fs.existsSync(`${config.observerAckPath}.sha256`)) return null;
      return readDigestBoundJson(config.observerAckPath);
    }, {timeoutMs: 180_000, signal: runController.signal});
    assertObserverAcknowledgement(observer.event, config, receiver.event);
    const broker = await waitForCondition('固定ACK broker验证结果', () => {
      if (!fs.existsSync(config.brokerResultPath) || !fs.existsSync(`${config.brokerResultPath}.sha256`)) return null;
      return readProtectedDigestBoundJson(config.brokerResultPath, {immutable: true});
    }, {timeoutMs: 180_000, signal: runController.signal, pollMs: 250});
    assertBrokerResult(broker, config, receiver, observer, rawEvents[0]);

    const controlPage = await context.newPage();
    await controlPage.goto(`${config.origin}/login.html`, {waitUntil: 'domcontentloaded'});
    // pagehide closed the original UI-owned popup. Establish a fresh Viewer
    // through the existing public client so its closure can be bound to DELETE.
    await controlPage.addScriptTag({url: `${config.origin}/r297-owner-login.js`});
    const revocationPath = await bounded('撤销前建立独立Viewer',
      controlPage.evaluate(openRevocationViewer, config.storeId), 12_000);
    assert.equal(revocationPath, `/jd-browser/novnc/${config.storeId}/vnc.html`);
    const revocationPage = await context.newPage();
    const revocationReady = waitForViewerReady(revocationPage, config.storeId, runController.signal);
    const [revocationViewer] = await Promise.all([
      revocationReady, revocationPage.goto(`${config.origin}${revocationPath}`, {waitUntil: 'domcontentloaded'})
    ]);
    assertLiveViewerForRevocation(revocationViewer);
    const deleted = await browserJson(controlPage, `/api/jd-workbench/stores/${config.storeId}/login-session`, {method: 'DELETE'}, 200);
    const deletedBody = assertResponse(deleted, 200, ['ok', 'store_id', 'status'], '销毁会话');
    if (deletedBody.ok !== true || deletedBody.store_id !== config.storeId || deletedBody.status !== 'REVOKED') {
      throw new Error('销毁会话响应绑定错误');
    }
    sessionRevoked = true;
    await waitForCondition('撤销后既有Viewer WebSocket关闭', () => revocationViewer.websocket.isClosed(), {
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
      ack_broker_result: {result: 'PASS', sha256: broker.digest},
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
