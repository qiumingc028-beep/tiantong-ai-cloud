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
  internalToken,
  masterKey,
  now = Date.now,
  profileRoot = '/tmp/jd-cloud-profiles',
  archiveRoot = '/data/jd-session-archives',
  launchContext = (directory) => chromium.launchPersistentContext(directory, {
    headless: false,
    chromiumSandbox: true
  })
}) {
  if (Buffer.byteLength(String(internalToken || '')) < 32) {
    throw new Error('JD_BROWSER_INTERNAL_TOKEN_REQUIRED');
  }
  const encryptionKey = decodeMasterKey(masterKey);
  const app = Fastify({ logger: false });
  const browserSessions = new Map();
  const tickets = new Map();
  const viewerSessions = new Map();

  async function closeSession(id, session) {
    await archiveSession(session.context, id, archiveRoot, encryptionKey);
    await session.context.close();
    browserSessions.delete(id);
    for (const [viewer, record] of viewerSessions) {
      if (record.id === id) viewerSessions.delete(viewer);
    }
  }

  async function purgeExpired() {
    for (const [ticket, record] of tickets) if (record.expiresAt <= now()) tickets.delete(ticket);
    for (const [session, record] of viewerSessions) if (record.expiresAt <= now()) viewerSessions.delete(session);
    for (const [id, session] of browserSessions) {
      if (session.expiresAt <= now()) await closeSession(id, session);
    }
  }

  const expiryTimer = setInterval(() => void purgeExpired(), 30_000);
  expiryTimer.unref();
  app.addHook('onClose', async () => clearInterval(expiryTimer));

  async function verifyInternal(request, reply) {
    if (!safeEqual(request.headers['x-internal-token'], internalToken)) {
      return reply.code(401).send({ error: 'UNAUTHORIZED' });
    }
  }

  app.get('/internal/jd-browser/health', { preHandler: verifyInternal }, async () => {
    await purgeExpired();
    return {
      ok: true,
      service: 'jd-cloud-browser-runtime',
      sessions: browserSessions.size,
      display: process.env.DISPLAY || null,
      chromium_sandbox: true
    };
  });

  app.post('/internal/jd-browser/tickets', { preHandler: verifyInternal }, async (request, reply) => {
    const id = String(request.body?.session_id || '').trim();
    if (!id || id.length > 240) return reply.code(400).send({ error: 'SESSION_ID_REQUIRED' });
    await purgeExpired();
    if (browserSessions.size && !browserSessions.has(id)) {
      return reply.code(409).send({ error: 'SESSION_NOT_ACTIVE' });
    }
    const ticket = crypto.randomBytes(32).toString('hex');
    tickets.set(ticket, { id, expiresAt: now() + TICKET_TTL_MS });
    return { ticket, expires_in: TICKET_TTL_MS / 1000 };
  });

  app.get('/internal/jd-browser/novnc-auth', async (request, reply) => {
    await purgeExpired();
    const existing = cookieValue(request.headers.cookie, 'jd_browser_session');
    if (existing && viewerSessions.has(existing)) return reply.code(204).send();

    const ticket = ticketFromRequest(request);
    const record = tickets.get(ticket);
    if (!record || record.expiresAt <= now()) return reply.code(401).send({ error: 'TICKET_INVALID' });
    tickets.delete(ticket);
    const viewerSession = crypto.randomBytes(32).toString('hex');
    viewerSessions.set(viewerSession, { id: record.id, expiresAt: now() + SESSION_TTL_MS });
    reply.header(
      'set-cookie',
      `jd_browser_session=${viewerSession}; Max-Age=${SESSION_TTL_MS / 1000}; Path=/jd-browser/novnc/; HttpOnly; Secure; SameSite=Strict`
    );
    return reply.code(204).send();
  });

  app.post('/internal/jd-browser/sessions', { preHandler: verifyInternal }, async (request, reply) => {
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

  app.post('/internal/jd-browser/capture', { preHandler: verifyInternal }, async (request, reply) => {
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

  app.get('/internal/jd-browser/sessions/:sid', { preHandler: verifyInternal }, async (request) => {
    await purgeExpired();
    return { status: browserSessions.has(request.params.sid) ? 'ACTIVE' : 'REVOKED' };
  });

  app.delete('/internal/jd-browser/sessions/:sid', { preHandler: verifyInternal }, async (request) => {
    const session = browserSessions.get(request.params.sid);
    if (session) await closeSession(request.params.sid, session);
    return { ok: true };
  });

  return app;
}

export async function startFromEnv() {
  const app = buildApp({
    internalToken: process.env.JD_BROWSER_INTERNAL_TOKEN,
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
