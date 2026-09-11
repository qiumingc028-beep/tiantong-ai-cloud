import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import net from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

import Fastify from 'fastify';
import { chromium } from 'playwright';

const require = createRequire(import.meta.url);
const { ROUTES } = require('../../desktop/jd-workbench/readonly-collector.js');
const { classifyRequest } = require('../../desktop/jd-workbench/security-policy.js');

const TICKET_TTL_MS = 60_000;
const COOKIE_TTL_MS = 60_000;
const SESSION_TTL_MS = 600_000;
const TOKEN_ISSUER = 'tiantong-jd-browser-runtime';
const TICKET_TYPE = 'viewer_ticket';
const TICKET_AUDIENCE = 'jd-browser-viewer-exchange';
const COOKIE_TYPE = 'viewer_cookie';
const COOKIE_AUDIENCE = 'jd-browser-novnc';
const SCOPE_KEYS = Object.freeze(['namespace', 'tenant_id', 'company_id', 'store_id', 'platform']);
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
  if (!payload || typeof payload !== 'object' || Object.keys(payload).some((key) => !SCOPE_KEYS.includes(key))) return null;
  if (!SCOPE_KEYS.every((key) => typeof payload[key] === 'string' || (key === 'store_id' && Number.isSafeInteger(payload[key]) && payload[key] > 0))) return null;
  const scope = Object.fromEntries(SCOPE_KEYS.map((key) => [key, String(payload[key]).trim()]));
  if (!SCOPE_KEYS.every((key) => SCOPE_VALUE.test(scope[key])) || scope.platform !== 'jd') return null;
  return scope;
}

function sessionId(scope) {
  return SCOPE_KEYS.map((key) => scope[key]).join(':');
}

function parseSessionId(value, expectedNamespace) {
  const parts = String(value || '').split(':');
  if (parts.length !== SCOPE_KEYS.length) return null;
  const scope = normalizedScope(Object.fromEntries(SCOPE_KEYS.map((key, index) => [key, parts[index]])));
  return scope && scope.namespace === expectedNamespace && sessionId(scope) === value ? scope : null;
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
    const scope = normalizedScope(Object.fromEntries(SCOPE_KEYS.map((name) => [name, payload[name]])));
    if (
      payload.typ !== typ || payload.aud !== aud || payload.iss !== TOKEN_ISSUER ||
      typeof payload.jti !== 'string' || !/^[0-9a-f]{32}$/.test(payload.jti) ||
      !Number.isInteger(payload.issued_at) || typeof payload.exp !== 'number' || !Number.isInteger(payload.exp) ||
      payload.issued_at * 1000 > now() || payload.exp * 1000 <= now() || !scope ||
      sessionId(scope) !== payload.session_id
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
  const destination = process.env.JD_BROWSER_SESSION_AUTH_URL || 'http://backend:8000/api/jd-workbench/internal/browser-session-authorize';
  if (destination !== 'http://backend:8000/api/jd-workbench/internal/browser-session-authorize') {
    const url = new URL(destination);
    if (process.env.APP_ENV === 'production' || process.env.R297_CONTROLLED_CANARY !== '1' ||
        url.protocol !== 'http:' || !['127.0.0.1', 'host.docker.internal'].includes(url.hostname) || !url.port || url.username || url.password ||
        url.pathname !== '/api/jd-workbench/internal/browser-session-authorize' || url.search || url.hash) {
      throw new Error('JD_SESSION_AUTH_DESTINATION_INVALID');
    }
  }
  return async (scope, operationId) => {
    if (!/^[0-9a-f]{32}$/.test(operationId || '')) return false;
    const response = await fetch(
      destination,
      {
        method: 'POST',
        headers: { 'content-type': 'application/json', 'x-internal-token': controlToken,
          'x-owner-session-operation-id': operationId },
        redirect: 'error',
        signal: AbortSignal.timeout(5000),
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
  sessionNamespace,
  authorizeSession,
  viewerUpstreamPort = 6080,
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
  if (sessionNamespace !== undefined && !/^([a-z0-9][a-z0-9-]{1,31})$/.test(String(sessionNamespace || ''))) throw new Error('JD_SESSION_NAMESPACE_REQUIRED');
  if (process.env.APP_ENV === 'production' && !/^r297-[0-9a-f]{24}$/.test(sessionNamespace || '')) throw new Error('JD_DEPLOYMENT_NAMESPACE_REQUIRED');
  if (new Set([captureKey, controlKey, ticketKey, cookieKey]).size !== 4) {
    throw new Error('JD_BROWSER_CAPABILITY_TOKENS_MUST_BE_DISTINCT');
  }
  const authorize = authorizeSession || defaultSessionAuthorizer(controlKey);
  const app = Fastify({ logger: false });
  const browserSessions = new Map();
  app.addHook('onReady', async () => {
    if (process.env.APP_ENV !== 'production') return;
    await fs.mkdir(archiveRoot, {recursive: true, mode: 0o700});
    const identityPath = path.join(archiveRoot, '.deployment-namespace');
    try {
      const handle = await fs.open(identityPath, 'wx', 0o600);
      try { await handle.writeFile(sessionNamespace); await handle.sync(); } finally { await handle.close(); }
    } catch (error) { if (error.code !== 'EEXIST') throw error; }
    if (await fs.readFile(identityPath, 'utf8') !== sessionNamespace) throw new Error('JD_DEPLOYMENT_NAMESPACE_CHANGED');
    const directory = await fs.open(archiveRoot, 'r');
    try { await directory.sync(); } finally { await directory.close(); }
  });
  app.addHook('onSend', async (_request, reply, payload) => {
    reply.header('cache-control', 'no-store').header('referrer-policy', 'no-referrer');
    return payload;
  });

  async function isAuthorized(scope, operationId) {
    try { return await authorize(scope, operationId) === true; } catch (_error) { return false; }
  }

  async function sessionRemainsAuthorized(id, session) {
    const allowed = session.expiresAt > now() && await isAuthorized(session.scope, session.ownerOperationId);
    if (browserSessions.get(id) !== session) return false;
    if (allowed) return true;
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
    for (const socket of session.viewerSockets || []) socket.destroy();
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
    for (const socket of session?.viewerSockets || []) socket.destroy();
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
      else await sessionRemainsAuthorized(id, session);
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
      await fs.writeFile(path.join(directory, record.jti), String(record.exp * 1000), { flag: 'wx', mode: 0o600 });
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

  const operationRoot = path.join(archiveRoot, 'owner-operations');
  const operationIdPattern = /^[0-9a-f]{32}$/;
  const operationTypes = {
    'POST /internal/jd-browser/sessions': 'owner_login_session_create',
    'GET /internal/jd-browser/sessions/:sid': 'owner_login_session_status',
    'POST /internal/jd-browser/tickets': 'owner_login_ticket',
    'DELETE /internal/jd-browser/sessions/:sid': 'owner_login_session_revoke'
  };
  const signOperation = record => signedValue(record, crypto.createHmac('sha256', encryptionKey).update('owner-operation-v1').digest());

  async function syncOperationDirectory(directoryPath) {
    const directory = await fs.open(directoryPath, 'r');
    try { await directory.sync(); } finally { await directory.close(); }
  }

  async function writeOperation(record, initial = false) {
    await fs.mkdir(operationRoot, {recursive: true, mode: 0o700});
    // Persist new directory entries before executing any Owner side effect.
    await syncOperationDirectory(path.dirname(archiveRoot));
    await syncOperationDirectory(archiveRoot);
    const target = path.join(operationRoot, `${record.operation_id}.json`);
    const filename = initial ? target : `${target}.${crypto.randomBytes(8).toString('hex')}.tmp`;
    const handle = await fs.open(filename, 'wx', 0o600);
    try { await handle.writeFile(signOperation(record)); await handle.sync(); }
    finally { await handle.close(); }
    if (!initial) await fs.rename(filename, target);
    await syncOperationDirectory(operationRoot);
  }

  function decodeOperation(value, id) {
    const [body, signature, ...extra] = value.split('.');
    const record = JSON.parse(Buffer.from(body, 'base64url').toString('utf8'));
    if (extra.length || !safeEqual(signOperation(record), value) || !signature ||
        record.operation_id !== id || !parseSessionId(record.session_id, sessionNamespace) ||
        !Object.values(operationTypes).includes(record.operation) ||
        !['PENDING', 'SUCCESS'].includes(record.status) ||
        (record.status === 'SUCCESS' && !/^[0-9a-f]{64}$/.test(record.response_sha256 || ''))) throw new Error('OWNER_OPERATION_INVALID');
    return record;
  }

  async function readOperation(id) {
    let record = decodeOperation(await fs.readFile(path.join(operationRoot, `${id}.json`), 'utf8'), id);
    if (record.status === 'PENDING') {
      // The signed SUCCESS temporary is causal evidence produced after the effect,
      // not a guess from current session state. Retry persistence, never the effect.
      for (const name of await fs.readdir(operationRoot)) {
        if (!new RegExp(`^${id}\\.json\\.[0-9a-f]{16}\\.tmp$`).test(name)) continue;
        try {
          const completed = decodeOperation(await fs.readFile(path.join(operationRoot, name), 'utf8'), id);
          if (completed.status !== 'SUCCESS' || completed.operation !== record.operation || completed.session_id !== record.session_id) continue;
          await writeOperation(completed);
          record = completed;
          break;
        } catch (_error) { /* Keep UNKNOWN/PENDING when persistence or proof is unavailable. */ }
      }
    }
    // A previous rename may have succeeded while its directory fsync failed.
    // A queried SUCCESS must be durable before it can confirm the old effect.
    if (record.status === 'SUCCESS') await syncOperationDirectory(operationRoot);
    return record;
  }

  app.addHook('preHandler', async (request, reply) => {
    const id = request.headers['x-owner-operation-id'];
    if (id === undefined) return;
    if (!safeEqual(request.headers['x-internal-token'], controlKey)) return reply.code(401).send({error: 'UNAUTHORIZED'});
    const operation = operationTypes[`${request.method} ${request.routeOptions.url}`];
    if (!operation || typeof id !== 'string' || !operationIdPattern.test(id)) return reply.code(400).send({error: 'OWNER_OPERATION_INVALID'});
    const scope = operation === 'owner_login_session_create' ? normalizedScope(request.body)
      : parseSessionId(operation === 'owner_login_ticket' ? request.body?.session_id : request.params.sid, sessionNamespace);
    if (!scope || scope.namespace !== sessionNamespace) return reply.code(400).send({error: 'OWNER_OPERATION_SCOPE_INVALID'});
    const record = {operation_id: id, operation, session_id: sessionId(scope), status: 'PENDING', response_sha256: null};
    try { await writeOperation(record, true); }
    catch (error) { return reply.code(error.code === 'EEXIST' ? 409 : 503).send({error: 'OWNER_OPERATION_UNAVAILABLE'}); }
    request.ownerOperation = record;
  });

  app.addHook('onSend', async (request, reply, payload) => {
    if (!request.ownerOperation || reply.statusCode !== 200) return payload;
    const responseSha = crypto.createHash('sha256').update(payload).digest('hex');
    const record = {...request.ownerOperation, status: 'SUCCESS', response_sha256: responseSha};
    try { await writeOperation(record); }
    catch (_error) { reply.code(503); return JSON.stringify({error: 'OWNER_OPERATION_UNAVAILABLE'}); }
    reply.header('x-owner-operation-id', record.operation_id).header('x-owner-result-sha256', responseSha);
    return payload;
  });

  app.get('/internal/jd-browser/operations/:id', {preHandler: verifyControl}, async (request, reply) => {
    if (!operationIdPattern.test(request.params.id)) return reply.code(400).send({error: 'OWNER_OPERATION_INVALID'});
    try { return await readOperation(request.params.id); }
    catch (error) { return reply.code(error.code === 'ENOENT' ? 404 : 503).send({error: 'OWNER_OPERATION_UNAVAILABLE'}); }
  });

  app.get('/internal/jd-browser/health', { preHandler: verifyControl }, async () => {
    await purgeExpired();
    return { ok: true, service: 'jd-cloud-browser-runtime', sessions: browserSessions.size,
      display: process.env.DISPLAY || null, chromium_sandbox: true };
  });

  app.post('/internal/jd-browser/sessions', { preHandler: verifyControl }, async (request, reply) => {
    const scope = normalizedScope(request.body);
    if (!scope) return reply.code(400).send({ error: 'SESSION_SCOPE_INVALID' });
    if (scope.namespace !== sessionNamespace) return reply.code(403).send({ error: 'scope_namespace_mismatch' });
    const id = sessionId(scope);
    const operationId = request.ownerOperation?.operation_id;
    if (!await isAuthorized(scope, operationId)) {
      const active = browserSessions.get(id);
      if (active) await destroySession(id, active).catch((error) => app.log.error(error));
      return reply.code(403).send({ error: 'SESSION_SCOPE_REJECTED' });
    }
    await purgeExpired();
    if (browserSessions.has(id)) {
      const active = browserSessions.get(id);
      if (active.ownerOperationId === operationId) {
        return { session_id: id, expires_in: remainingSeconds(active.expiresAt), restored: false };
      }
      // A different Owner grant cannot inherit existing Viewer authority.
      await destroySession(id, active);
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
        context, scope, ownerOperationId: operationId, nonce: restored ? crypto.randomBytes(16).toString('hex') : nonce,
        expiresAt: restored?.expires_at || now() + SESSION_TTL_MS
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
    if (!parseSessionId(id, sessionNamespace)) return reply.code(400).send({ error: 'invalid_session_id' });
    const session = browserSessions.get(id);
    if (!session || !await sessionRemainsAuthorized(id, session)) {
      return reply.code(409).send({ error: 'SESSION_NOT_ACTIVE' });
    }
    const issuedAt = Math.floor(now() / 1000);
    const ticket = signedValue({
      typ: TICKET_TYPE, aud: TICKET_AUDIENCE, iss: TOKEN_ISSUER,
      jti: crypto.randomBytes(16).toString('hex'), ...session.scope, session_id: id,
      session_nonce: session.nonce,
      issued_at: issuedAt, exp: issuedAt + Math.floor(TICKET_TTL_MS / 1000)
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
    const issuedAt = Math.floor(now() / 1000);
    const viewerSession = signedValue({
      typ: COOKIE_TYPE, aud: COOKIE_AUDIENCE, iss: TOKEN_ISSUER,
      jti: crypto.randomBytes(16).toString('hex'), ...Object.fromEntries(SCOPE_KEYS.map((key) => [key, record[key]])),
      session_id: record.session_id, session_nonce: record.session_nonce,
      issued_at: issuedAt, exp: issuedAt + Math.floor(COOKIE_TTL_MS / 1000)
    }, cookieKey);
    return reply
      .header('cache-control', 'no-store')
      .header('referrer-policy', 'no-referrer')
      .header('set-cookie', `jd_browser_session=${viewerSession}; Max-Age=${TICKET_TTL_MS / 1000}; Path=/jd-browser/novnc/${encodeURIComponent(storeId)}/; HttpOnly; Secure; SameSite=Strict`)
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

  app.server.on('upgrade', (request, socket, head) => {
    const connectViewer = async () => {
      const storeId = /^\/internal\/jd-browser\/viewer\/stream\/([A-Za-z0-9_-]{1,64})$/.exec(request.url)?.[1];
      const viewer = verifiedValue(cookieValue(request.headers.cookie, 'jd_browser_session'), cookieKey,
        {typ: COOKIE_TYPE, aud: COOKIE_AUDIENCE, now});
      const session = viewer && browserSessions.get(viewer.session_id);
      if (!storeId || !viewer || viewer.store_id !== storeId || !session || viewer.session_nonce !== session.nonce ||
          !await sessionRemainsAuthorized(viewer.session_id, session) || browserSessions.get(viewer.session_id) !== session) {
        socket.end('HTTP/1.1 401 Unauthorized\r\nConnection: close\r\n\r\n');
        return;
      }
      const upstream = net.connect(viewerUpstreamPort, '127.0.0.1');
      session.viewerSockets ||= new Set();
      session.viewerSockets.add(socket);
      const close = () => { clearTimeout(expiry); session.viewerSockets.delete(socket); socket.destroy(); upstream.destroy(); };
      const expiry = setTimeout(close, Math.max(0, viewer.exp * 1000 - now()));
      expiry.unref();
      socket.on('error', close).on('close', close);
      upstream.on('error', close).on('close', close);
      upstream.setTimeout(10000, close);
      upstream.once('data', () => upstream.setTimeout(0));
      upstream.once('connect', () => {
        const headers = ['GET /websockify HTTP/1.1', 'Host: 127.0.0.1', 'Connection: Upgrade', 'Upgrade: websocket'];
        for (const name of ['sec-websocket-key', 'sec-websocket-version', 'sec-websocket-protocol']) {
          if (request.headers[name]) headers.push(`${name}: ${request.headers[name]}`);
        }
        upstream.write(headers.join('\r\n') + '\r\n\r\n');
        if (head.length) upstream.write(head);
        socket.pipe(upstream).pipe(socket);
      });
    };
    void connectViewer().catch(() => socket.destroy());
  });

  app.post('/internal/jd-browser/capture', { preHandler: verifyCapture }, async (request, reply) => {
    if (!request.body || Object.keys(request.body).some((key) => !['scope', 'dataset', 'date_range'].includes(key)) || typeof request.body.dataset !== 'string' || !['metrics', 'orders', 'products', 'ads'].includes(request.body.dataset)) {
      return reply.code(400).send({ status: 'INVALID_CAPTURE_REQUEST', data: {} });
    }
    const range = request.body.date_range;
    const calendarDate = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) &&
      Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
    if (range !== undefined && (!range || request.body.dataset === 'metrics' ||
        Object.keys(range).sort().join(',') !== 'end,start' || !calendarDate(range.start) || !calendarDate(range.end) || range.start > range.end)) {
      return reply.code(400).send({status: 'INVALID_CAPTURE_REQUEST', data: {}});
    }
    const scope = normalizedScope(request.body.scope);
    if (!scope) return reply.code(400).send({ status: 'INVALID_CAPTURE_REQUEST', data: {} });
    if (scope.namespace !== sessionNamespace) return reply.code(403).send({ status: 'SCOPE_REJECTED', data: {} });
    const session = scope && browserSessions.get(sessionId(scope));
    if (!session || !await sessionRemainsAuthorized(sessionId(scope), session)) {
      return reply.code(409).send({ status: 'LOGIN_REQUIRED', data: {} });
    }
    const page = session.context.pages()[0] || await session.context.newPage();
    const dataset = request.body.dataset;
    const observedAfter = now();
    let networkEvidence = null;
    // Listen before navigation. DOM flags alone cannot authenticate an empty result.
    const emptyProof = dataset !== 'metrics' && range && typeof page.waitForResponse === 'function'
      ? page.waitForResponse(async response => {
        try {
          const req = response.request(), url = new URL(response.url());
          if (response.status() !== 200 || response.fromServiceWorker() || req.method() !== 'GET' || req.redirectedFrom() ||
              req.timing().startTime < observedAfter || req.frame() !== page.mainFrame() ||
              url.origin !== new URL(dashboardUrl).origin ||
              !String(response.headers()['content-type'] || '').includes('application/json') ||
              url.searchParams.get('dataset') !== dataset || url.searchParams.get('store_id') !== scope.store_id ||
              url.searchParams.get('range_start') !== range.start || url.searchParams.get('range_end') !== range.end) return false;
          const body = await response.json();
          const expected = {dataset, store_id: scope.store_id, range_start: range.start, range_end: range.end,
            authenticated: true, permission_granted: true, empty_state: true, total_count: 0, pagination_complete: true};
          if (!body || body.status !== 'OK' || !Array.isArray(body.records) || body.records.length !== 0 ||
              Object.entries(expected).some(([key, value]) => body[key] !== value)) return false;
          networkEvidence = {...expected, source: 'authenticated_network_response'};
          return true;
        } catch (_error) { return false; }
      }, {timeout: 5000}).then(() => networkEvidence, () => null) : Promise.resolve(null);
    await page.goto(dashboardUrl, { waitUntil: 'domcontentloaded' });
    const captured = await page.evaluate((datasetName) => {
      if (datasetName === 'metrics') {
        return Object.fromEntries(
          [...document.querySelectorAll('[data-metric]')]
            .map((node) => [node.getAttribute('data-metric'), node.textContent?.trim()])
            .filter(([key, value]) => key && value)
        );
      }
      const node = document.querySelector(`script[type="application/json"][data-dataset="${datasetName}"]`);
      if (!node) return null;
      try { return JSON.parse(node.textContent || ''); }
      catch (_error) { return null; }
    }, dataset);
    const validCapture = dataset === 'metrics'
      ? captured && !Array.isArray(captured) && typeof captured === 'object' && Object.keys(captured).length > 0
      : Array.isArray(captured) && captured.every((row) => row && !Array.isArray(row) && typeof row === 'object');
    if (!validCapture) return reply.code(422).send({ status: 'JD_DATASET_NOT_FOUND', data: {} });
    let emptyEvidence;
    if (dataset !== 'metrics' && captured.length === 0) {
      // A missing selector or [] is not proof that an authenticated date range is empty.
      if (!range || typeof page.url !== 'function' || page.url() !== dashboardUrl) {
        return reply.code(422).send({status: 'JD_EMPTY_DATASET_UNVERIFIED', data: {}});
      }
      emptyEvidence = await emptyProof;
      if (!emptyEvidence) {
        return reply.code(422).send({status: 'JD_EMPTY_DATASET_UNVERIFIED', data: {}});
      }
    }
    return { status: 'OK', data: { source: 'jd_cloud_playwright', captured_at: new Date(now()).toISOString(),
      store_id: scope.store_id, [dataset]: captured, ...(emptyEvidence ? {empty_evidence: emptyEvidence} : {}) } };
  });

  app.get('/internal/jd-browser/sessions/:sid', { preHandler: verifyControl }, async (request, reply) => {
    if (!parseSessionId(request.params.sid, sessionNamespace)) return reply.code(400).send({ error: 'invalid_session_id' });
    await purgeExpired();
    const session = browserSessions.get(request.params.sid);
    if (session && !await sessionRemainsAuthorized(request.params.sid, session)) return { status: 'REVOKED' };
    return { status: session ? 'ACTIVE' : 'REVOKED' };
  });

  app.delete('/internal/jd-browser/sessions/:sid', { preHandler: verifyControl }, async (request, reply) => {
    if (!parseSessionId(request.params.sid, sessionNamespace)) return reply.code(400).send({ error: 'invalid_session_id' });
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
  if (!/^([a-z0-9][a-z0-9-]{1,31})$/.test(String(process.env.JD_SESSION_NAMESPACE || ''))) throw new Error('JD_SESSION_NAMESPACE_REQUIRED');
  const app = buildApp({
    captureToken: process.env.JD_BROWSER_CAPTURE_TOKEN,
    controlToken: process.env.JD_BROWSER_CONTROL_TOKEN,
    viewerTicketSigningKey: process.env.JD_BROWSER_VIEWER_TICKET_SIGNING_KEY,
    viewerCookieSigningKey: process.env.JD_BROWSER_VIEWER_COOKIE_SIGNING_KEY,
    masterKey: process.env.JD_SESSION_MASTER_KEY,
    dashboardUrl,
    profileRoot: process.env.JD_PROFILE_ROOT,
    archiveRoot: process.env.JD_SESSION_ARCHIVE_ROOT,
    sessionNamespace: process.env.JD_SESSION_NAMESPACE
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
