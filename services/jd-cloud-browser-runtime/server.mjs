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
const SESSION_TTL_MS = 600_000;

function decodeMasterKey(value) {
  const key = Buffer.from(String(value || ''), 'base64');
  if (key.length !== 32) throw new Error('JD_SESSION_MASTER_KEY_REQUIRED');
  return key;
}

function safeEqual(actual, expected) {
  const left = Buffer.from(String(actual || ''));
  const right = Buffer.from(String(expected || ''));
  return left.length === right.length && crypto.timingSafeEqual(left, right);
}

function sessionId(payload) {
  return `${payload.tenant_id}:${payload.company_id}:${payload.store_id}:${payload.platform}`;
}

function cookieValue(header, name) {
  for (const item of String(header || '').split(';')) {
    const [key, ...value] = item.trim().split('=');
    if (key === name) return value.join('=');
  }
  return '';
}

function ticketFromRequest(request) {
  if (request.query?.ticket) return String(request.query.ticket);
  try {
    const original = new URL(String(request.headers['x-original-uri'] || ''), 'https://internal.invalid');
    return original.searchParams.get('ticket') || '';
  } catch (_error) {
    return '';
  }
}

function storeFromRequest(request) {
  try {
    const original = new URL(String(request.headers['x-original-uri'] || ''), 'https://internal.invalid');
    const match = original.pathname.match(/^\/jd-browser\/novnc\/([^/]+)(?:\/|$)/);
    return match ? decodeURIComponent(match[1]) : '';
  } catch (_error) {
    return '';
  }
}

function signedValue(payload, key) {
  const body = Buffer.from(JSON.stringify(payload)).toString('base64url');
  return `${body}.${crypto.createHmac('sha256', key).update(body).digest('base64url')}`;
}

function verifiedValue(value, key) {
  const [body, signature, ...extra] = String(value || '').split('.');
  if (!body || !signature || extra.length) return null;
  const expected = crypto.createHmac('sha256', key).update(body).digest('base64url');
  if (!safeEqual(signature, expected)) return null;
  try {
    return JSON.parse(Buffer.from(body, 'base64url').toString('utf8'));
  } catch (_error) {
    return null;
  }
}

function installReadOnlyPolicy(context) {
  return context.route('**/*', async (route) => {
    const request = route.request();
    let frame;
    try {
      frame = request.frame();
    } catch (_error) {
      frame = null;
    }
    const page = context.pages()[0];
    const isMainFrameSource = Boolean(page && frame && frame === page.mainFrame());
    const resourceType = isMainFrameSource && request.resourceType() === 'document'
      ? 'mainFrame'
      : request.resourceType();
    const decision = classifyRequest({
      url: request.url(),
      method: request.method(),
      resourceType,
      currentMainFrameUrl: frame?.url() || ROUTES.dashboard,
      isActive: true,
      isMainFrameSource,
      initiator: request.headers().referer || frame?.url() || ROUTES.dashboard
    });
    return decision.allow ? route.continue() : route.abort('blockedbyclient');
  });
}

async function archiveSession(context, id, archiveRoot, masterKey) {
  const plaintext = Buffer.from(JSON.stringify(await context.storageState()), 'utf8');
  const nonce = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv('aes-256-gcm', masterKey, nonce);
  const ciphertext = Buffer.concat([cipher.update(plaintext), cipher.final()]);
  const payload = Buffer.concat([nonce, cipher.getAuthTag(), ciphertext]);
  await fs.mkdir(archiveRoot, { recursive: true, mode: 0o700 });
  const filename = `${crypto.createHash('sha256').update(id).digest('hex')}.enc`;
  await fs.writeFile(path.join(archiveRoot, filename), payload, { mode: 0o600 });
}

export function buildApp({
  captureToken,
  controlToken,
  viewerSigningKey,
  masterKey,
  now = Date.now,
  profileRoot = '/tmp/jd-cloud-profiles',
  archiveRoot = '/data/jd-session-archives',
  launchContext = (directory) => chromium.launchPersistentContext(directory, {
    headless: false,
    chromiumSandbox: true
  })
}) {
  if (Buffer.byteLength(String(captureToken || '')) < 32) throw new Error('JD_BROWSER_CAPTURE_TOKEN_REQUIRED');
  if (Buffer.byteLength(String(controlToken || '')) < 32) throw new Error('JD_BROWSER_CONTROL_TOKEN_REQUIRED');
  if (Buffer.byteLength(String(viewerSigningKey || '')) < 32) throw new Error('JD_BROWSER_VIEWER_SIGNING_KEY_REQUIRED');
  const encryptionKey = decodeMasterKey(masterKey);
  if (new Set([captureToken, controlToken, viewerSigningKey]).size !== 3) {
    throw new Error('JD_BROWSER_CAPABILITY_TOKENS_MUST_BE_DISTINCT');
  }
  const app = Fastify({ logger: false });
  const browserSessions = new Map();

  async function closeSession(id, session) {
    if (!browserSessions.delete(id)) return;
    try {
      await archiveSession(session.context, id, archiveRoot, encryptionKey);
    } finally {
      await session.context.close();
    }
  }

  async function purgeExpired() {
    for (const [id, session] of browserSessions) {
      if (session.expiresAt <= now()) await closeSession(id, session);
    }
    const ticketDirectory = path.join(archiveRoot, '.used-viewer-tickets');
    try {
      for (const name of await fs.readdir(ticketDirectory)) {
        const filename = path.join(ticketDirectory, name);
        if (Number(await fs.readFile(filename, 'utf8')) <= now()) await fs.unlink(filename);
      }
    } catch (error) {
      if (error?.code !== 'ENOENT') throw error;
    }
  }

  async function consumeTicket(record) {
    const directory = path.join(archiveRoot, '.used-viewer-tickets');
    const filename = crypto.createHash('sha256').update(record.nonce).digest('hex');
    await fs.mkdir(directory, { recursive: true, mode: 0o700 });
    try {
      await fs.writeFile(path.join(directory, filename), String(record.expiresAt), { flag: 'wx', mode: 0o600 });
      return true;
    } catch (error) {
      if (error?.code === 'EEXIST') return false;
      throw error;
    }
  }

  const expiryTimer = setInterval(() => void purgeExpired().catch((error) => app.log.error(error)), 30_000);
  expiryTimer.unref();
  app.addHook('onClose', async () => clearInterval(expiryTimer));

  function verifyToken(expected) {
    return async (request, reply) => {
      if (safeEqual(request.headers['x-internal-token'], expected)) return;
      return reply.code(401).send({ error: 'UNAUTHORIZED' });
    };
  }
  const verifyControl = verifyToken(controlToken);
  const verifyCapture = verifyToken(captureToken);

  app.get('/internal/jd-browser/health', { preHandler: verifyControl }, async () => {
    await purgeExpired();
    return {
      ok: true,
      service: 'jd-cloud-browser-runtime',
      sessions: browserSessions.size,
      display: process.env.DISPLAY || null,
      chromium_sandbox: true
    };
  });

  app.post('/internal/jd-browser/tickets', { preHandler: verifyControl }, async (request, reply) => {
    const id = String(request.body?.session_id || '').trim();
    const storeId = String(id.split(':')[2] || '').trim();
    const requestedStoreId = request.body?.store_id == null ? storeId : String(request.body.store_id).trim();
    if (!id || id.length > 240 || !storeId) return reply.code(400).send({ error: 'SESSION_ID_REQUIRED' });
    if (requestedStoreId !== storeId) return reply.code(400).send({ error: 'STORE_SCOPE_MISMATCH' });
    await purgeExpired();
    if (!browserSessions.has(id)) return reply.code(409).send({ error: 'SESSION_NOT_ACTIVE' });
    const ticket = signedValue({ id, storeId, nonce: crypto.randomBytes(16).toString('hex'), expiresAt: now() + TICKET_TTL_MS }, viewerSigningKey);
    return { ticket, expires_in: TICKET_TTL_MS / 1000 };
  });

  app.get('/internal/jd-browser/novnc-auth', async (request, reply) => {
    await purgeExpired();
    const storeId = storeFromRequest(request);
    if (!storeId) return reply.code(401).send({ error: 'STORE_SCOPE_REQUIRED' });
    const existing = cookieValue(request.headers.cookie, 'jd_browser_session');
    const viewer = verifiedValue(existing, viewerSigningKey);
    if (viewer && viewer.expiresAt > now() && viewer.storeId === storeId && browserSessions.has(viewer.id)) {
      return reply.code(204).send();
    }

    const ticket = ticketFromRequest(request);
    const record = verifiedValue(ticket, viewerSigningKey);
    if (!record || record.expiresAt <= now() || record.storeId !== storeId || !browserSessions.has(record.id)) {
      return reply.code(401).send({ error: 'TICKET_INVALID' });
    }
    if (!await consumeTicket(record)) return reply.code(401).send({ error: 'TICKET_INVALID' });
    const viewerSession = signedValue({ id: record.id, storeId, expiresAt: now() + SESSION_TTL_MS }, viewerSigningKey);
    reply.header(
      'set-cookie',
      `jd_browser_session=${viewerSession}; Max-Age=${SESSION_TTL_MS / 1000}; Path=/jd-browser/novnc/${encodeURIComponent(storeId)}/; HttpOnly; Secure; SameSite=Strict`
    );
    return reply.code(204).send();
  });

  app.post('/internal/jd-browser/sessions', { preHandler: verifyControl }, async (request, reply) => {
    const payload = request.body || {};
    const id = sessionId(payload);
    await purgeExpired();
    if (browserSessions.has(id)) {
      return { session_id: id, expires_in: SESSION_TTL_MS / 1000 };
    }
    if (browserSessions.size) {
      return reply.code(409).send({ error: 'ACTIVE_SESSION_EXISTS' });
    }
    const directory = path.join(profileRoot, crypto.createHash('sha256').update(id).digest('hex'));
    await fs.mkdir(directory, { recursive: true, mode: 0o700 });
    const context = await launchContext(directory);
    await installReadOnlyPolicy(context);
    browserSessions.set(id, { context, expiresAt: now() + SESSION_TTL_MS });
    return { session_id: id, expires_in: SESSION_TTL_MS / 1000 };
  });

  app.post('/internal/jd-browser/capture', { preHandler: verifyCapture }, async (request, reply) => {
    const payload = request.body || {};
    await purgeExpired();
    const session = browserSessions.get(sessionId(payload));
    if (!session) return reply.code(409).send({ status: 'LOGIN_REQUIRED', data: {} });
    const page = session.context.pages()[0] || await session.context.newPage();
    await page.goto(ROUTES.dashboard, { waitUntil: 'domcontentloaded' });
    const metrics = await page.evaluate(() => Object.fromEntries(
      [...document.querySelectorAll('[data-metric]')]
        .map((node) => [node.getAttribute('data-metric'), node.textContent?.trim()])
        .filter(([key, value]) => key && value)
    ));
    if (!Object.keys(metrics).length) return reply.code(422).send({ status: 'JD_METRIC_NOT_FOUND', data: {} });
    return {
      status: 'OK',
      data: {
        source: 'jd_cloud_playwright',
        captured_at: new Date(now()).toISOString(),
        store_id: payload.store_id,
        metrics
      }
    };
  });

  app.get('/internal/jd-browser/sessions/:sid', { preHandler: verifyControl }, async (request) => {
    await purgeExpired();
    return { status: browserSessions.has(request.params.sid) ? 'ACTIVE' : 'REVOKED' };
  });

  app.delete('/internal/jd-browser/sessions/:sid', { preHandler: verifyControl }, async (request) => {
    const session = browserSessions.get(request.params.sid);
    if (session) await closeSession(request.params.sid, session);
    return { ok: true };
  });

  return app;
}

export async function startFromEnv() {
  const app = buildApp({
    captureToken: process.env.JD_BROWSER_CAPTURE_TOKEN,
    controlToken: process.env.JD_BROWSER_CONTROL_TOKEN,
    viewerSigningKey: process.env.JD_BROWSER_VIEWER_SIGNING_KEY,
    masterKey: process.env.JD_SESSION_MASTER_KEY,
    profileRoot: process.env.JD_PROFILE_ROOT,
    archiveRoot: process.env.JD_SESSION_ARCHIVE_ROOT
  });
  await app.listen({ host: '0.0.0.0', port: Number(process.env.PORT || 8787) });
  return app;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  startFromEnv().catch((error) => {
    console.error(error.message);
    process.exit(1);
  });
}
