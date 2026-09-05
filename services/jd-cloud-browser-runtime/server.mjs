import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

import Fastify from 'fastify';
import { chromium } from 'playwright';

const require = createRequire(import.meta.url);
const { ROUTES } = require('../../desktop/jd-workbench/readonly-collector.js');
const { classifyRequest } = require('../../desktop/jd-workbench/security-policy.js');

const TICKET_TTL_MS = 60_000;
const COOKIE_TTL_MS = 600_000;
const SESSION_TTL_MS = 600_000;
const TOKEN_ISSUER = 'tiantong-jd-browser-runtime';
const TICKET_TYPE = 'viewer_ticket';
const TICKET_AUDIENCE = 'jd-browser-viewer-exchange';
const COOKIE_TYPE = 'viewer_cookie';
const COOKIE_AUDIENCE = 'jd-browser-novnc';
const SCOPE_KEYS = Object.freeze(['tenant_id', 'company_id', 'store_id', 'platform']);
const SCOPE_VALUE = /^[A-Za-z0-9_-]{1,64}$/;

function decodeMasterKey(value) {
  const key = Buffer.from(String(value || ''), 'base64');
  if (key.length !== 32) throw new Error('JD_SESSION_MASTER_KEY_REQUIRED');
  return key;
}

function requiredSecret(value, name) {
  const secret = String(value || '');
  if (Buffer.byteLength(secret) < 32) throw new Error(`${name}_REQUIRED`);
  return secret;
}

function safeEqual(actual, expected) {
  const left = Buffer.from(String(actual || ''));
  const right = Buffer.from(String(expected || ''));
  return left.length === right.length && crypto.timingSafeEqual(left, right);
}

function normalizedScope(payload) {
  const scope = Object.fromEntries(SCOPE_KEYS.map((key) => [key, String(payload?.[key] ?? '').trim()]));
  if (!SCOPE_KEYS.every((key) => SCOPE_VALUE.test(scope[key]))) return null;
  return scope;
}

function sessionId(scope) {
  return SCOPE_KEYS.map((key) => scope[key]).join(':');
}

function cookieValue(header, name) {
  for (const item of String(header || '').split(';')) {
    const [key, ...value] = item.trim().split('=');
    if (key === name) return value.join('=');
  }
  return '';
}

function signedValue(payload, key) {
  const body = Buffer.from(JSON.stringify(payload)).toString('base64url');
  return `${body}.${crypto.createHmac('sha256', key).update(body).digest('base64url')}`;
}

function verifiedValue(value, key, { typ, aud, now }) {
  const [body, signature, ...extra] = String(value || '').split('.');
  if (!body || !signature || extra.length) return null;
  const expected = crypto.createHmac('sha256', key).update(body).digest('base64url');
  if (!safeEqual(signature, expected)) return null;
  try {
    const payload = JSON.parse(Buffer.from(body, 'base64url').toString('utf8'));
    if (
      payload.typ !== typ || payload.aud !== aud || payload.iss !== TOKEN_ISSUER ||
      typeof payload.jti !== 'string' || !/^[0-9a-f]{32}$/.test(payload.jti) ||
      !Number.isInteger(payload.issued_at) || !Number.isInteger(payload.expires_at) ||
      payload.issued_at > now() || payload.expires_at <= now() ||
      sessionId(normalizedScope(payload) || {}) !== payload.session_id
    ) return null;
    return payload;
  } catch (_error) {
    return null;
  }
}

function archiveFilename(id) {
  return `${crypto.createHash('sha256').update(id).digest('hex')}.enc`;
}

function decryptArchive(payload, masterKey, aad) {
  if (payload.length < 29) throw new Error('SESSION_ARCHIVE_INVALID');
  try {
    const decipher = crypto.createDecipheriv('aes-256-gcm', masterKey, payload.subarray(0, 12));
    decipher.setAAD(Buffer.from(aad));
    decipher.setAuthTag(payload.subarray(12, 28));
    const record = JSON.parse(Buffer.concat([
      decipher.update(payload.subarray(28)), decipher.final()
    ]).toString('utf8'));
    if (
      !Number.isInteger(record.expires_at) ||
      !/^[0-9a-f]{32}$/.test(record.session_nonce || '') ||
      !record.storage_state || typeof record.storage_state !== 'object'
    ) throw new Error('SESSION_ARCHIVE_INVALID');
    return record;
  } catch (_error) {
    throw new Error('SESSION_ARCHIVE_INVALID');
  }
}

function installReadOnlyPolicy(context, dashboardUrl = ROUTES.dashboard) {
  return context.route('**/*', async (route) => {
    const request = route.request();
    let frame;
    try { frame = request.frame(); } catch (_error) { frame = null; }
    const page = context.pages()[0];
    const isMainFrameSource = Boolean(page && frame && frame === page.mainFrame());
    const resourceType = isMainFrameSource && request.resourceType() === 'document'
      ? 'mainFrame'
      : request.resourceType();
    if (
      dashboardUrl !== ROUTES.dashboard && request.method() === 'GET' &&
      resourceType === 'mainFrame' && request.url() === dashboardUrl
    ) return route.continue();
    const decision = classifyRequest({
      url: request.url(), method: request.method(), resourceType,
      currentMainFrameUrl: frame?.url() || ROUTES.dashboard,
      isActive: true, isMainFrameSource,
      initiator: request.headers().referer || frame?.url() || ROUTES.dashboard
    });
    return decision.allow ? route.continue() : route.abort('blockedbyclient');
  });
}

async function writeArchive(context, id, archiveRoot, masterKey, expiresAt, nonce) {
  const plaintext = Buffer.from(JSON.stringify({
    expires_at: expiresAt,
    session_nonce: nonce,
    storage_state: await context.storageState()
  }), 'utf8');
  const archiveNonce = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv('aes-256-gcm', masterKey, archiveNonce);
  const filename = archiveFilename(id);
  cipher.setAAD(Buffer.from(filename));
  const ciphertext = Buffer.concat([cipher.update(plaintext), cipher.final()]);
  const payload = Buffer.concat([archiveNonce, cipher.getAuthTag(), ciphertext]);
  await fs.mkdir(archiveRoot, { recursive: true, mode: 0o700 });
  decryptArchive(payload, masterKey, filename);
  const temporary = path.join(archiveRoot, `.${filename}.${crypto.randomBytes(8).toString('hex')}.tmp`);
  let handle;
  try {
    handle = await fs.open(temporary, 'wx', 0o600);
    await handle.writeFile(payload);
    await handle.sync();
    await handle.close();
    handle = null;
    await fs.rename(temporary, path.join(archiveRoot, filename));
  } finally {
    if (handle) await handle.close().catch(() => {});
    await fs.rm(temporary, { force: true }).catch(() => {});
  }
}

async function readArchive(id, archiveRoot, masterKey) {
  const filename = archiveFilename(id);
  let payload;
  try {
    payload = await fs.readFile(path.join(archiveRoot, filename));
  } catch (error) {
    if (error?.code === 'ENOENT') return null;
    throw error;
  }
  return decryptArchive(payload, masterKey, filename);
}

function defaultSessionAuthorizer(controlToken) {
  return async (scope) => {
    const response = await fetch(
      process.env.JD_BROWSER_SESSION_AUTH_URL || 'http://backend:8000/api/jd-workbench/internal/browser-session-authorize',
      {
        method: 'POST',
        headers: { 'content-type': 'application/json', 'x-internal-token': controlToken },
        body: JSON.stringify(scope)
      }
    );
    return response.ok;
  };
}

export function buildApp({
  captureToken,
  controlToken,
  viewerTicketSigningKey,
  viewerCookieSigningKey,
  masterKey,
  now = Date.now,
  profileRoot = '/tmp/jd-cloud-profiles',
  archiveRoot = '/data/jd-session-archives',
  authorizeSession,
  dashboardUrl = ROUTES.dashboard,
  launchContext = (directory) => chromium.launchPersistentContext(directory, {
    headless: false,
    chromiumSandbox: true
  })
}) {
  const captureKey = requiredSecret(captureToken, 'JD_BROWSER_CAPTURE_TOKEN');
  const controlKey = requiredSecret(controlToken, 'JD_BROWSER_CONTROL_TOKEN');
  const ticketKey = requiredSecret(viewerTicketSigningKey, 'JD_BROWSER_VIEWER_TICKET_SIGNING_KEY');
  const cookieKey = requiredSecret(viewerCookieSigningKey, 'JD_BROWSER_VIEWER_COOKIE_SIGNING_KEY');
  const encryptionKey = decodeMasterKey(masterKey);
  if (new Set([captureKey, controlKey, ticketKey, cookieKey]).size !== 4) {
    throw new Error('JD_BROWSER_CAPABILITY_TOKENS_MUST_BE_DISTINCT');
  }
  const authorize = authorizeSession || defaultSessionAuthorizer(controlKey);
  const app = Fastify({ logger: false });
  const browserSessions = new Map();
  app.addHook('onSend', async (_request, reply, payload) => {
    reply.header('cache-control', 'no-store').header('referrer-policy', 'no-referrer');
    return payload;
  });

  async function isAuthorized(scope) {
    try { return await authorize(scope) === true; } catch (_error) { return false; }
  }

  async function sessionRemainsAuthorized(id, session) {
    if (await isAuthorized(session.scope)) return true;
    await destroySession(id, session).catch((error) => app.log.error(error));
    return false;
  }

  function profileDirectory(id) {
    return path.join(profileRoot, crypto.createHash('sha256').update(id).digest('hex'));
  }

  function remainingSeconds(expiresAt) {
    return Math.max(0, Math.ceil((expiresAt - now()) / 1000));
  }

  function ticketDirectory(id) {
    return path.join(archiveRoot, '.used-viewer-tickets', crypto.createHash('sha256').update(id).digest('hex'));
  }

  function ticketDirectoryFromDigest(digest) {
    return path.join(archiveRoot, '.used-viewer-tickets', digest);
  }

  async function removePlaintextProfile(id) {
    await fs.rm(profileDirectory(id), { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
  }

  async function runAllCleanup(steps, initialError = null) {
    let failure = initialError;
    for (const step of steps) {
      try { await step(); } catch (error) { failure ||= error; }
    }
    if (failure) throw failure;
  }

  async function suspendSession(id, session) {
    if (!browserSessions.delete(id)) return;
    let archiveError = null;
    try {
      await writeArchive(session.context, id, archiveRoot, encryptionKey, session.expiresAt, session.nonce);
    } catch (error) { archiveError = error; }
    await runAllCleanup([
      () => session.context.close(),
      () => removePlaintextProfile(id)
    ], archiveError);
  }

  async function destroySession(id, session) {
    browserSessions.delete(id);
    await runAllCleanup([
      ...(session ? [() => session.context.close()] : []),
      () => removePlaintextProfile(id),
      () => fs.rm(path.join(archiveRoot, archiveFilename(id)), { force: true }),
      () => fs.rm(ticketDirectory(id), { recursive: true, force: true })
    ]);
  }

  async function purgeExpired() {
    for (const [id, session] of browserSessions) {
      if (session.expiresAt <= now()) await destroySession(id, session);
    }
    let entries;
    try { entries = await fs.readdir(archiveRoot, { withFileTypes: true }); }
    catch (error) {
      if (error?.code === 'ENOENT') return;
      throw error;
    }
    for (const entry of entries) {
      if (!entry.isFile() || !/^[0-9a-f]{64}\.enc$/.test(entry.name)) continue;
      try {
        const archive = decryptArchive(await fs.readFile(path.join(archiveRoot, entry.name)), encryptionKey, entry.name);
        if (archive.expires_at <= now()) {
          await fs.rm(path.join(archiveRoot, entry.name), { force: true });
          await fs.rm(ticketDirectoryFromDigest(entry.name.slice(0, -4)), { recursive: true, force: true });
        }
      } catch (_error) {
        // Invalid archives remain fail-closed for an explicit restore attempt.
      }
    }
    const usedRoot = path.join(archiveRoot, '.used-viewer-tickets');
    let sessionDirectories = [];
    try { sessionDirectories = await fs.readdir(usedRoot, { withFileTypes: true }); }
    catch (error) {
      if (error?.code !== 'ENOENT') throw error;
    }
    for (const directory of sessionDirectories) {
      if (!directory.isDirectory() || !/^[0-9a-f]{64}$/.test(directory.name)) continue;
      const fullDirectory = path.join(usedRoot, directory.name);
      for (const marker of await fs.readdir(fullDirectory, { withFileTypes: true })) {
        if (!marker.isFile()) continue;
        let expiresAt = 0;
        try { expiresAt = Number(await fs.readFile(path.join(fullDirectory, marker.name), 'utf8')); }
        catch (_error) { expiresAt = 0; }
        if (!Number.isInteger(expiresAt) || expiresAt <= now()) {
          await fs.rm(path.join(fullDirectory, marker.name), { force: true });
        }
      }
      if (!(await fs.readdir(fullDirectory)).length) {
        try { await fs.rmdir(fullDirectory); }
        catch (error) {
          if (!['ENOENT', 'ENOTEMPTY'].includes(error?.code)) throw error;
        }
      }
    }
  }

  async function consumeTicket(record) {
    const directory = ticketDirectory(record.session_id);
    await fs.mkdir(directory, { recursive: true, mode: 0o700 });
    try {
      await fs.writeFile(path.join(directory, record.jti), String(record.expires_at), { flag: 'wx', mode: 0o600 });
      return true;
    } catch (error) {
      if (error?.code === 'EEXIST') return false;
      throw error;
    }
  }

  const expiryTimer = setInterval(() => void purgeExpired().catch((error) => app.log.error(error)), 30_000);
  expiryTimer.unref();
  app.addHook('onClose', async () => {
    clearInterval(expiryTimer);
    for (const [id, session] of [...browserSessions]) await suspendSession(id, session);
  });

  function verifyToken(expected) {
    return async (request, reply) => {
      if (safeEqual(request.headers['x-internal-token'], expected)) return;
      return reply.code(401).send({ error: 'UNAUTHORIZED' });
    };
  }
  const verifyControl = verifyToken(controlKey);
  const verifyCapture = verifyToken(captureKey);

  app.get('/internal/jd-browser/health', { preHandler: verifyControl }, async () => {
    await purgeExpired();
    return { ok: true, service: 'jd-cloud-browser-runtime', sessions: browserSessions.size,
      display: process.env.DISPLAY || null, chromium_sandbox: true };
  });

  app.post('/internal/jd-browser/sessions', { preHandler: verifyControl }, async (request, reply) => {
    const scope = normalizedScope(request.body);
    if (!scope) return reply.code(403).send({ error: 'SESSION_SCOPE_REJECTED' });
    const id = sessionId(scope);
    if (!await isAuthorized(scope)) {
      const active = browserSessions.get(id);
      if (active) await destroySession(id, active).catch((error) => app.log.error(error));
      return reply.code(403).send({ error: 'SESSION_SCOPE_REJECTED' });
    }
    await purgeExpired();
    if (browserSessions.has(id)) {
      const active = browserSessions.get(id);
      return { session_id: id, expires_in: remainingSeconds(active.expiresAt) };
    }
    if (browserSessions.size) return reply.code(409).send({ error: 'ACTIVE_SESSION_EXISTS' });
    let restored;
    try { restored = await readArchive(id, archiveRoot, encryptionKey); }
    catch (_error) { return reply.code(409).send({ error: 'SESSION_ARCHIVE_INVALID' }); }
    if (restored && restored.expires_at <= now()) {
      await destroySession(id);
      restored = null;
    }
    const directory = profileDirectory(id);
    await fs.mkdir(directory, { recursive: true, mode: 0o700 });
    let context;
    try {
      context = await launchContext(directory, restored);
      if (restored?.storage_state?.cookies?.length && typeof context.addCookies === 'function') {
        await context.addCookies(restored.storage_state.cookies);
      }
      if (restored?.storage_state?.origins?.length && typeof context.addInitScript === 'function') {
        await context.addInitScript(({ origins }) => {
          const state = origins.find((item) => item.origin === globalThis.location.origin);
          for (const entry of state?.localStorage || []) globalThis.localStorage.setItem(entry.name, entry.value);
        }, { origins: restored.storage_state.origins });
      }
      await installReadOnlyPolicy(context, dashboardUrl);
      // Viewer authority is intentionally process-bound: restore JD state, never a pre-restart cookie.
      const nonce = crypto.randomBytes(16).toString('hex');
      browserSessions.set(id, {
        context, scope, nonce, expiresAt: restored?.expires_at || now() + SESSION_TTL_MS
      });
    } catch (error) {
      await runAllCleanup([
        ...(context ? [() => context.close()] : []),
        () => removePlaintextProfile(id)
      ], error);
    }
    return {
      session_id: id,
      expires_in: remainingSeconds(browserSessions.get(id).expiresAt),
      restored: Boolean(restored)
    };
  });

  app.post('/internal/jd-browser/tickets', { preHandler: verifyControl }, async (request, reply) => {
    if (Object.keys(request.body || {}).some((key) => key !== 'session_id')) {
      return reply.code(400).send({ error: 'INVALID_TICKET_REQUEST' });
    }
    const id = String(request.body?.session_id || '').trim();
    const session = browserSessions.get(id);
    if (!session || !await sessionRemainsAuthorized(id, session)) {
      return reply.code(409).send({ error: 'SESSION_NOT_ACTIVE' });
    }
    const issuedAt = now();
    const ticket = signedValue({
      typ: TICKET_TYPE, aud: TICKET_AUDIENCE, iss: TOKEN_ISSUER,
      jti: crypto.randomBytes(16).toString('hex'), ...session.scope, session_id: id,
      session_nonce: session.nonce,
      issued_at: issuedAt, expires_at: issuedAt + TICKET_TTL_MS
    }, ticketKey);
    return reply.header('cache-control', 'no-store').header('referrer-policy', 'no-referrer')
      .send({ ticket, expires_in: TICKET_TTL_MS / 1000 });
  });

  app.post('/internal/jd-browser/viewer/exchange/:store', async (request, reply) => {
    if (Object.keys(request.query || {}).length || Object.keys(request.body || {}).some((key) => key !== 'ticket')) {
      return reply.code(400).send({ error: 'INVALID_TICKET_REQUEST' });
    }
    const storeId = String(request.params.store || '');
    const ticket = String(request.body?.ticket || '');
    const record = verifiedValue(ticket, ticketKey, { typ: TICKET_TYPE, aud: TICKET_AUDIENCE, now });
    const session = record && browserSessions.get(record.session_id);
    if (
      !record || record.store_id !== storeId || !session || record.session_nonce !== session.nonce ||
      !await sessionRemainsAuthorized(record.session_id, session) ||
      !await consumeTicket(record)
    ) return reply.code(401).send({ error: 'TICKET_INVALID' });
    const issuedAt = now();
    const viewerSession = signedValue({
      typ: COOKIE_TYPE, aud: COOKIE_AUDIENCE, iss: TOKEN_ISSUER,
      jti: crypto.randomBytes(16).toString('hex'), ...Object.fromEntries(SCOPE_KEYS.map((key) => [key, record[key]])),
      session_id: record.session_id, session_nonce: record.session_nonce,
      issued_at: issuedAt, expires_at: issuedAt + COOKIE_TTL_MS
    }, cookieKey);
    return reply
      .header('cache-control', 'no-store')
      .header('referrer-policy', 'no-referrer')
      .header('set-cookie', `jd_browser_session=${viewerSession}; Max-Age=${COOKIE_TTL_MS / 1000}; Path=/jd-browser/novnc/${encodeURIComponent(storeId)}/; HttpOnly; Secure; SameSite=Strict`)
      .code(204).send();
  });

  app.get('/internal/jd-browser/viewer/authorize', async (request, reply) => {
    const match = /^\/jd-browser\/novnc\/([A-Za-z0-9_-]{1,64})\//.exec(String(request.headers['x-original-uri'] || ''));
    const storeId = match?.[1] || '';
    const viewer = verifiedValue(cookieValue(request.headers.cookie, 'jd_browser_session'), cookieKey,
      { typ: COOKIE_TYPE, aud: COOKIE_AUDIENCE, now });
    const session = viewer && browserSessions.get(viewer.session_id);
    if (
      !viewer || viewer.store_id !== storeId || !session || viewer.session_nonce !== session.nonce ||
      !await sessionRemainsAuthorized(viewer.session_id, session)
    ) {
      return reply.code(401).send({ error: 'VIEWER_SESSION_INVALID' });
    }
    return reply.header('cache-control', 'no-store').header('referrer-policy', 'no-referrer').code(204).send();
  });

  app.post('/internal/jd-browser/capture', { preHandler: verifyCapture }, async (request, reply) => {
    const scope = normalizedScope(request.body);
    const session = scope && browserSessions.get(sessionId(scope));
    if (!session || !await sessionRemainsAuthorized(sessionId(scope), session)) {
      return reply.code(409).send({ status: 'LOGIN_REQUIRED', data: {} });
    }
    const page = session.context.pages()[0] || await session.context.newPage();
    await page.goto(dashboardUrl, { waitUntil: 'domcontentloaded' });
    const metrics = await page.evaluate(() => Object.fromEntries(
      [...document.querySelectorAll('[data-metric]')]
        .map((node) => [node.getAttribute('data-metric'), node.textContent?.trim()])
        .filter(([key, value]) => key && value)
    ));
    if (!Object.keys(metrics).length) return reply.code(422).send({ status: 'JD_METRIC_NOT_FOUND', data: {} });
    return { status: 'OK', data: { source: 'jd_cloud_playwright', captured_at: new Date(now()).toISOString(),
      store_id: scope.store_id, ...metrics } };
  });

  app.get('/internal/jd-browser/sessions/:sid', { preHandler: verifyControl }, async (request, reply) => {
    await purgeExpired();
    const session = browserSessions.get(request.params.sid);
    if (session && !await sessionRemainsAuthorized(request.params.sid, session)) return { status: 'REVOKED' };
    return { status: session ? 'ACTIVE' : 'REVOKED' };
  });

  app.delete('/internal/jd-browser/sessions/:sid', { preHandler: verifyControl }, async (request, reply) => {
    const session = browserSessions.get(request.params.sid);
    await destroySession(request.params.sid, session);
    return { ok: true };
  });

  return app;
}

export async function startFromEnv() {
  let dashboardUrl = ROUTES.dashboard;
  if (process.env.R297_CONTROLLED_CANARY === '1') {
    if ((process.env.APP_ENV || '').trim().toLowerCase() === 'production') {
      throw new Error('R297_CONTROLLED_CANARY_FORBIDDEN_IN_PRODUCTION');
    }
    const candidate = new URL(process.env.R297_CONTROLLED_CANARY_DASHBOARD_URL || '');
    if (
      candidate.protocol !== 'http:' || candidate.hostname !== 'host.docker.internal' ||
      candidate.pathname !== '/r297-controlled-canary.html' || candidate.username || candidate.password ||
      candidate.search || candidate.hash
    ) throw new Error('R297_CONTROLLED_CANARY_DASHBOARD_URL_INVALID');
    dashboardUrl = candidate.href;
  }
  const app = buildApp({
    captureToken: process.env.JD_BROWSER_CAPTURE_TOKEN,
    controlToken: process.env.JD_BROWSER_CONTROL_TOKEN,
    viewerTicketSigningKey: process.env.JD_BROWSER_VIEWER_TICKET_SIGNING_KEY,
    viewerCookieSigningKey: process.env.JD_BROWSER_VIEWER_COOKIE_SIGNING_KEY,
    masterKey: process.env.JD_SESSION_MASTER_KEY,
    dashboardUrl,
    profileRoot: process.env.JD_PROFILE_ROOT,
    archiveRoot: process.env.JD_SESSION_ARCHIVE_ROOT
  });
  await app.listen({ host: '127.0.0.1', port: Number(process.env.RUNTIME_API_PORT || 8788) });
  return app;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  startFromEnv().then((app) => {
    let closing = false;
    const close = async () => {
      if (closing) return;
      closing = true;
      try { await app.close(); process.exit(0); }
      catch (error) { console.error(error.message); process.exit(1); }
    };
    process.once('SIGTERM', close);
    process.once('SIGINT', close);
  }).catch((error) => {
    console.error(error.message);
    process.exit(1);
  });
}
