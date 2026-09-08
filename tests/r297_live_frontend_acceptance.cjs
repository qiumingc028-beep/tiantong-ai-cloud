#!/usr/bin/env node
'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync, spawnSync } = require('node:child_process');

const SHA_RE = /^[0-9a-f]{40}$/;
const RUN_RE = /^[A-Za-z0-9._:-]{16,128}$/;
const RAW_FIELDS = ['event', 'observed_at', 'release_sha', 'store_id'];
const SESSION_STATUSES = new Set(['ACTIVE', 'LOGIN_REQUIRED', 'REVOKED', 'EXPIRED', 'HUMAN_ACTION_REQUIRED']);
const REQUIRED_INPUTS = [
  'R297_WINDOWS_CANARY_BACKEND_HTTPS_URL', 'R297_EXPECTED_RELEASE_SHA',
  'R297_ACCEPTANCE_RUN_ID', 'R297_OWNER_STORAGE_STATE_PATH', 'R297_LIVE_OUTPUT_DIR',
  'R297_EVIDENCE_NAMESPACE', 'R297_EVIDENCE_TENANT_ID', 'R297_EVIDENCE_COMPANY_ID',
  'R297_EVIDENCE_STORE_ID', 'R297_EVIDENCE_CROSS_STORE_ID', 'R297_EVIDENCE_CROSS_TENANT_STORE_ID'
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
  if (!fs.statSync(storageState).isFile()) throw new Error('Owner浏览器会话文件不存在');
  return Object.freeze({
    origin: originUrl.origin, releaseSha, runId, storageState, outputDir,
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

function safeUrl(input) {
  try { const url = new URL(input); return `${url.origin}${url.pathname}`; }
  catch (_error) { return 'invalid-url'; }
}

function bounded(label, promise, milliseconds, signal) {
  let timer;
  let abort;
  const aborted = new Promise((_, reject) => {
    if (!signal) return;
    abort = () => reject(signal.reason || new Error(`${label}已取消`));
    if (signal.aborted) abort();
    else signal.addEventListener('abort', abort, {once: true});
  });
  return Promise.race([
    promise,
    new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`${label}超时`)), milliseconds); }),
    aborted,
  ]).finally(() => {
    clearTimeout(timer);
    if (signal && abort) signal.removeEventListener('abort', abort);
  });
}

async function waitForCondition(label, predicate, milliseconds, signal) {
  const deadline = Date.now() + milliseconds;
  while (Date.now() < deadline) {
    if (signal?.aborted) throw signal.reason || new Error(`${label}已取消`);
    if (predicate()) return;
    await new Promise((resolve, reject) => {
      const timer = setTimeout(resolve, Math.min(50, Math.max(1, deadline - Date.now())));
      if (!signal) return;
      const abort = () => {
        clearTimeout(timer);
        reject(signal.reason || new Error(`${label}已取消`));
      };
      signal.addEventListener('abort', abort, {once: true});
    });
  }
  throw new Error(`${label}超时`);
}

function viewerSnapshotReady(snapshot) {
  return snapshot.connected === true && snapshot.canvasWidth > 0 && snapshot.canvasHeight > 0;
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

async function main() {
  const config = loadConfig();
  if (process.argv.includes('--check-config')) {
    process.stdout.write(`R297_LIVE_FRONTEND_PREFLIGHT=READY\nR297_RELEASE_SHA=${config.releaseSha}\nR297_RUN_ID=${config.runId}\n`);
    return;
  }
  const repositoryRoot = path.resolve(__dirname, '..');
  let checkoutSha;
  try {
    checkoutSha = execFileSync('git', ['rev-parse', 'HEAD'], {cwd: repositoryRoot, encoding: 'utf8'}).trim();
    const trackedChanges = execFileSync(
      'git', ['status', '--porcelain', '--untracked-files=no'], {cwd: repositoryRoot, encoding: 'utf8'}
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
  let cleanupDone = false;
  let stopping = false;
  let result = 'BLOCK';
  let firstBlocker = '';
  const runController = new AbortController();
  const runBounded = (label, promise, milliseconds) => bounded(
    label, promise, milliseconds, runController.signal
  );

  async function cleanup() {
    if (cleanupDone) return;
    cleanupDone = true;
    if (sessionCleanupRequired && !sessionRevoked && context) {
      try {
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
  }

  async function stopForSignal(signal, code) {
    if (stopping) return;
    stopping = true;
    result = 'BLOCK';
    firstBlocker = `执行器收到${signal}`;
    runController.abort(new Error(firstBlocker));
    await cleanup();
    process.exitCode = code;
  }
  process.once('SIGINT', () => { void stopForSignal('SIGINT', 130); });
  process.once('SIGTERM', () => { void stopForSignal('SIGTERM', 143); });

  try {
    browser = await chromium.launch({ headless: true });
    context = await browser.newContext({ storageState: config.storageState });
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
    await runBounded('店铺页面加载', page.goto(`${config.origin}/stores.html`, {waitUntil: 'networkidle'}), 30_000);

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
    await runBounded('目标店铺行加载', row.waitFor({state: 'visible'}), 15_000);
    const createPath = `/api/jd-workbench/stores/${config.storeId}/login-session`;
    const createRequest = page.waitForRequest(request => request.method() === 'POST'
      && new URL(request.url()).pathname === createPath);
    const createResponse = page.waitForResponse(response => response.request().method() === 'POST'
      && new URL(response.url()).pathname === createPath);
    await row.getByRole('button', {name: /京东登录|重新验证/}).click();
    await runBounded('创建会话请求', createRequest, 10_000);
    sessionCleanupRequired = true;
    const createHttp = await runBounded('创建会话', createResponse, 35_000);
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

    const popupPromise = context.waitForEvent('page');
    const websocketPromise = page.waitForEvent('websocket', {
      predicate: socket => {
        const url = new URL(socket.url());
        return url.protocol === 'wss:'
          && url.pathname === `/jd-browser/novnc/${config.storeId}/websockify` && !url.search;
      },
      timeout: 20_000
    });
    await row.getByRole('button', {name: '打开受控验证窗口'}).click();
    const [popup, websocket] = await Promise.all([
      runBounded('受控登录窗口打开', popupPromise, 10_000),
      websocketPromise
    ]);
    await popup.waitForURL(`**/jd-browser/novnc/${config.storeId}/vnc.html`, {timeout: 30_000});
    const viewerSnapshot = await runBounded('noVNC Viewer连接', popup.waitForFunction(() => {
      const canvas = document.querySelector('#noVNC_canvas');
      return document.documentElement.classList.contains('noVNC_connected') && canvas
        && canvas.width > 0 && canvas.height > 0;
    }, undefined, {timeout: 30_000}).then(() => popup.evaluate(() => {
      const canvas = document.querySelector('#noVNC_canvas');
      return {
        connected: document.documentElement.classList.contains('noVNC_connected'),
        canvasWidth: canvas ? canvas.width : 0,
        canvasHeight: canvas ? canvas.height : 0,
      };
    })), 32_000);
    assert.equal(viewerSnapshotReady(viewerSnapshot), true, 'noVNC Viewer未连接或画布不可用');
    const websocketPath = new URL(websocket.url()).pathname;
    const viewerCookies = (await context.cookies()).filter(cookie => cookie.name === 'jd_browser_session');
    assert.equal(viewerCookies.length, 1, 'HttpOnly Viewer Cookie缺失');
    assert.equal(viewerCookies[0].httpOnly, true);
    assert.equal(viewerCookies[0].secure, true);
    assert.equal(viewerCookies[0].sameSite, 'Strict');

    const negative = await runBounded('ticket拒绝矩阵', ticketNegativeChecks(page, config), 140_000);
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
    await waitForCondition(
      '原生pagehide事件',
      () => nativeEvents.length >= 1 && rawEvents.length >= 1,
      5_000,
      runController.signal
    );
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

    const controlPage = await context.newPage();
    await controlPage.goto(`${config.origin}/login.html`, {waitUntil: 'domcontentloaded'});
    const deleted = await browserJson(controlPage, `/api/jd-workbench/stores/${config.storeId}/login-session`, {method: 'DELETE'}, 200);
    const deletedBody = assertResponse(deleted, 200, ['ok', 'store_id', 'status'], '销毁会话');
    assert.deepEqual(deletedBody, {ok: true, store_id: config.storeId, status: 'REVOKED'});
    sessionRevoked = true;
    const revoked = await browserJson(controlPage, `/jd-browser/novnc/${config.storeId}/vnc.html`, undefined, 401);
    assert.ok([401, 403].includes(revoked.status), '撤销后Viewer访问未失效');
    assert.equal(consoleErrors.length, 0, '浏览器控制台存在错误');
    assert.equal(pageErrors.length, 0, '浏览器存在未处理JavaScript错误');
    assert.equal(failedRequests.length, 0, '浏览器存在失败网络请求');

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
    const manifest = {
      schema_version: '1.0', result: 'PASS', release_sha: config.releaseSha, run_id: config.runId,
      scope: {namespace: config.namespace, tenant_id: config.tenantId, company_id: config.companyId, store_id: config.storeId, platform: 'jd'},
      session_status: sessionStatus, public_api: 'PASS', http_only_cookie: 'PASS',
      novnc_page: 'PASS', websocket_path: websocketPath, ticket_rejections: negative,
      delete_and_revoke: 'PASS', pagehide_raw: 'PASS',
      screenshot: {file: path.basename(screenshotPath), sha256: sha256File(screenshotPath), redacted_selectors: redactSelectors},
      pagehide_artifact: {archive: path.basename(archivePath), archive_sha256: sha256File(archivePath), evidence_sha256: evidenceSha, manifest_sha256: sha256File(artifactManifest)},
      console_error_count: consoleErrors.length, page_error_count: pageErrors.length,
      failed_request_count: failedRequests.length,
      observer_handoff: 'R297_AUTHENTICATED_OBSERVER_REQUIRED'
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
    process.stdout.write('R297_AUTHENTICATED_OBSERVER_REQUIRED=YES\n');
  }
}

const selfTest = process.argv.includes('--self-test-timeout')
  ? waitForCondition('自测事件', () => false, 50, new AbortController().signal)
  : process.argv.includes('--self-test-viewer')
    ? Promise.resolve().then(() => {
      assert.equal(viewerSnapshotReady({connected: false, canvasWidth: 640, canvasHeight: 480}), false);
      assert.equal(viewerSnapshotReady({connected: true, canvasWidth: 0, canvasHeight: 480}), false);
      assert.equal(viewerSnapshotReady({connected: true, canvasWidth: 640, canvasHeight: 480}), true);
    })
    : main();

selfTest.catch(error => {
  console.error(error && error.stack ? error.stack : error);
  process.exitCode = 1;
});
