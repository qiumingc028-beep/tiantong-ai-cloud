import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import net from 'node:net';
import { once } from 'node:events';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { buildApp } from '../server.mjs';

async function fixture(t, overrides = {}) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'r297-operations-'));
  const scope = { namespace: 'causal-test', tenant_id: '1', company_id: '1', store_id: '1', platform: 'jd' };
  const options = {
    captureToken: crypto.randomBytes(32).toString('hex'), controlToken: crypto.randomBytes(32).toString('hex'),
    viewerTicketSigningKey: crypto.randomBytes(32).toString('hex'), viewerCookieSigningKey: crypto.randomBytes(32).toString('hex'),
    masterKey: crypto.randomBytes(32).toString('base64'), sessionNamespace: scope.namespace,
    profileRoot: path.join(root, 'profiles'), archiveRoot: path.join(root, 'archives'),
    authorizeSession: async () => true,
    launchContext: async () => ({route: async () => {}, close: async () => {}, storageState: async () => ({cookies: [], origins: []})}),
    ...overrides,
  };
  const apps = [];
  const start = () => { const app = buildApp(options); apps.push(app); return app; };
  t.after(async () => { for (const app of apps) await app.close(); await fs.rm(root, {recursive: true, force: true}); });
  return {root, scope, options, start, headers: {'x-internal-token': options.controlToken}};
}

test('all Owner operations have durable correlated receipts without storing response secrets', async t => {
  const f = await fixture(t);
  let app = f.start();
  const sid = Object.values(f.scope).join(':');
  const receipts = [];
  let ticket;
  for (const [operation, method, url, payload] of [
    ['owner_login_session_create', 'POST', '/sessions', f.scope],
    ['owner_login_session_status', 'GET', `/sessions/${encodeURIComponent(sid)}`],
    ['owner_login_ticket', 'POST', '/tickets', {session_id: sid}],
    ['owner_login_session_revoke', 'DELETE', `/sessions/${encodeURIComponent(sid)}`],
  ]) {
    const id = crypto.randomBytes(16).toString('hex');
    const request = {method, url: `/internal/jd-browser${url}`, payload, headers: {...f.headers, 'x-owner-operation-id': id}};
    const response = await app.inject(request);
    assert.equal(response.statusCode, 200);
    assert.equal(response.headers['x-owner-operation-id'], id);
    const digest = crypto.createHash('sha256').update(response.body).digest('hex');
    assert.equal(response.headers['x-owner-result-sha256'], digest);
    if (operation === 'owner_login_ticket') ticket = response.json().ticket;
    const expected = {operation_id: id, operation, session_id: sid, status: 'SUCCESS', response_sha256: digest};
    receipts.push(expected);
    const receipt = await app.inject({method: 'GET', url: `/internal/jd-browser/operations/${id}`, headers: f.headers});
    assert.deepEqual(receipt.json(), expected);
    assert.equal((await app.inject(request)).statusCode, 409, 'one operation ID cannot execute twice');
  }
  await app.close();
  app = f.start();
  for (const expected of receipts) {
    const url = `/internal/jd-browser/operations/${expected.operation_id}`;
    assert.equal((await app.inject({method: 'GET', url, headers: {'x-internal-token': f.options.captureToken}})).statusCode, 401);
    assert.deepEqual((await app.inject({method: 'GET', url, headers: f.headers})).json(), expected);
  }
  const directory = path.join(f.options.archiveRoot, 'owner-operations');
  for (const name of await fs.readdir(directory)) {
    const contents = await fs.readFile(path.join(directory, name), 'utf8');
    const decoded = Buffer.from(contents.split('.')[0], 'base64url').toString();
    assert.equal(decoded.includes(ticket), false);
    assert.equal(decoded.includes(f.options.controlToken), false);
  }
  const filename = path.join(directory, `${receipts[0].operation_id}.json`);
  const [body, signature] = (await fs.readFile(filename, 'utf8')).split('.');
  const changed = Buffer.from(Buffer.from(body, 'base64url').toString().replace(receipts[0].response_sha256, '0'.repeat(64))).toString('base64url');
  await fs.writeFile(filename, `${changed}.${signature}`);
  assert.equal((await app.inject({method: 'GET', url: `/internal/jd-browser/operations/${receipts[0].operation_id}`, headers: f.headers})).statusCode, 503);
});

test('runtime failure stays pending across restart and never invents an operation result', async t => {
  const id = crypto.randomBytes(16).toString('hex');
  const f = await fixture(t, {launchContext: async () => {
    const value = await fs.readFile(path.join(f.options.archiveRoot, 'owner-operations', `${id}.json`), 'utf8');
    assert.equal(JSON.parse(Buffer.from(value.split('.')[0], 'base64url')).status, 'PENDING');
    throw new Error('controlled failure');
  }});
  let app = f.start();
  const response = await app.inject({method: 'POST', url: '/internal/jd-browser/sessions', payload: f.scope,
    headers: {...f.headers, 'x-owner-operation-id': id}});
  assert.equal(response.statusCode, 500);
  await app.close();
  app = f.start();
  const receipt = await app.inject({method: 'GET', url: `/internal/jd-browser/operations/${id}`, headers: f.headers});
  assert.equal(receipt.json().status, 'PENDING');
  assert.equal(receipt.json().response_sha256, null);
  assert.equal((await app.inject({method: 'GET', url: `/internal/jd-browser/operations/${'0'.repeat(32)}`, headers: f.headers})).statusCode, 404);
});

test('receipt commit failure cannot return success and keeps the original pending record', async t => {
  const f = await fixture(t);
  const app = f.start();
  const id = crypto.randomBytes(16).toString('hex');
  const rename = fs.rename;
  t.mock.method(fs, 'rename', async (source, target) => {
    if (target.endsWith(`owner-operations/${id}.json`)) throw new Error('controlled receipt commit failure');
    return rename(source, target);
  });
  const response = await app.inject({method: 'POST', url: '/internal/jd-browser/sessions', payload: f.scope,
    headers: {...f.headers, 'x-owner-operation-id': id}});
  assert.equal(response.statusCode, 503);
  assert.equal(response.headers['x-owner-operation-id'], undefined);
  const receipt = await app.inject({method: 'GET', url: `/internal/jd-browser/operations/${id}`, headers: f.headers});
  assert.equal(receipt.json().status, 'PENDING');
  assert.equal(receipt.json().response_sha256, null);
});

test('revoking the original Owner grant disconnects an already upgraded Viewer', async t => {
  const upstream = net.createServer(socket => socket.once('data', () => socket.write('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n')));
  upstream.listen(0, '127.0.0.1');
  await once(upstream, 'listening');
  t.after(() => upstream.close());
  let authorized = true;
  const id = crypto.randomBytes(16).toString('hex');
  const f = await fixture(t, {viewerUpstreamPort: upstream.address().port,
    authorizeSession: async (_scope, operationId) => authorized && operationId === id});
  const app = f.start();
  await app.listen({port: 0, host: '127.0.0.1'});
  const created = await app.inject({method: 'POST', url: '/internal/jd-browser/sessions', payload: f.scope,
    headers: {...f.headers, 'x-owner-operation-id': id}});
  assert.equal(created.statusCode, 200);
  const ticket = (await app.inject({method: 'POST', url: '/internal/jd-browser/tickets',
    headers: f.headers, payload: {session_id: created.json().session_id}})).json().ticket;
  const exchanged = await app.inject({method: 'POST', url: '/internal/jd-browser/viewer/exchange/1', payload: {ticket}});
  assert.equal(exchanged.statusCode, 204);
  const socket = net.connect(app.server.address().port, '127.0.0.1');
  t.after(() => socket.destroy());
  socket.setTimeout(2000, () => socket.destroy(new Error('Viewer handshake timeout')));
  socket.write(`GET /internal/jd-browser/viewer/stream/1 HTTP/1.1\r\nHost: localhost\r\nConnection: Upgrade\r\nUpgrade: websocket\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: ${crypto.randomBytes(16).toString('base64')}\r\nCookie: ${exchanged.headers['set-cookie'].split(';')[0]}\r\n\r\n`);
  const [response] = await once(socket, 'data');
  assert.match(response.toString(), /^HTTP\/1.1 101/);
  const disconnected = once(socket, 'close');
  authorized = false;
  await app.inject({method: 'GET', url: '/internal/jd-browser/health', headers: f.headers});
  await disconnected;
});

test('production namespace is deployment-specific and pinned across restart', async t => {
  const f = await fixture(t);
  const original = process.env.APP_ENV;
  process.env.APP_ENV = 'production';
  t.after(() => { if (original === undefined) delete process.env.APP_ENV; else process.env.APP_ENV = original; });
  for (const placeholder of ['default', 'production', 'ci']) {
    assert.throws(() => buildApp({...f.options, sessionNamespace: placeholder}), /JD_DEPLOYMENT_NAMESPACE_REQUIRED/);
  }
  f.options.sessionNamespace = 'r297-' + crypto.randomBytes(12).toString('hex');
  const first = f.start();
  await first.ready();
  await first.close();
  const same = f.start();
  await same.ready();
  await same.close();
  f.options.sessionNamespace = 'r297-' + crypto.randomBytes(12).toString('hex');
  const changed = f.start();
  await assert.rejects(changed.ready(), /JD_DEPLOYMENT_NAMESPACE_CHANGED/);
});

test('default authorizer pins its credential destination and bounds unknown results', async t => {
  const f = await fixture(t, {authorizeSession: undefined});
  const original = process.env.JD_BROWSER_SESSION_AUTH_URL;
  t.after(() => { if (original === undefined) delete process.env.JD_BROWSER_SESSION_AUTH_URL; else process.env.JD_BROWSER_SESSION_AUTH_URL = original; });
  process.env.JD_BROWSER_SESSION_AUTH_URL = 'https://example.invalid/collect';
  assert.throws(f.start, /JD_SESSION_AUTH_DESTINATION_INVALID/);
  delete process.env.JD_BROWSER_SESSION_AUTH_URL;
  let sent = 0;
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    sent++;
    assert.equal(url, 'http://backend:8000/api/jd-workbench/internal/browser-session-authorize');
    assert.equal(options.redirect, 'error');
    assert.ok(options.signal instanceof AbortSignal);
    // A server accepts the request but never resolves it; abort must fail closed.
    return new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => reject(options.signal.reason), {once: true}));
  });
  const app = f.start();
  const response = await app.inject({method: 'POST', url: '/internal/jd-browser/sessions', payload: f.scope,
    headers: {...f.headers, 'x-owner-operation-id': crypto.randomBytes(16).toString('hex')}});
  assert.equal(response.statusCode, 403);
  assert.equal(sent, 1);
});

test('late revocation of an old grant cannot remove its replacement session', async t => {
  const oldId = crypto.randomBytes(16).toString('hex');
  const newId = crypto.randomBytes(16).toString('hex');
  let delayOld = false;
  let release;
  let entered;
  const waiting = new Promise(resolve => { entered = resolve; });
  const f = await fixture(t, {authorizeSession: async (_scope, operationId) => {
    if (delayOld && operationId === oldId) {
      delayOld = false;
      entered();
      return new Promise(resolve => { release = resolve; });
    }
    return true;
  }});
  const app = f.start();
  const create = id => app.inject({method: 'POST', url: '/internal/jd-browser/sessions', payload: f.scope,
    headers: {...f.headers, 'x-owner-operation-id': id}});
  assert.equal((await create(oldId)).statusCode, 200);
  delayOld = true;
  const stale = app.inject({method: 'GET', url: '/internal/jd-browser/health', headers: f.headers});
  await waiting;
  const replacement = await create(newId);
  assert.equal(replacement.statusCode, 200);
  release(false);
  await stale;
  const ticket = await app.inject({method: 'POST', url: '/internal/jd-browser/tickets', headers: f.headers,
    payload: {session_id: replacement.json().session_id}});
  assert.equal(ticket.statusCode, 200, 'late old authorization must not destroy the replacement');
});

test('controlled container authorization allows only the mapped host gateway and fixed path', async t => {
  const f = await fixture(t, {authorizeSession: undefined});
  const keys = ['APP_ENV', 'R297_CONTROLLED_CANARY', 'JD_BROWSER_SESSION_AUTH_URL'];
  const original = Object.fromEntries(keys.map(key => [key, process.env[key]]));
  t.after(() => { for (const key of keys) { if (original[key] === undefined) delete process.env[key]; else process.env[key] = original[key]; } });
  process.env.APP_ENV = 'acceptance';
  process.env.R297_CONTROLLED_CANARY = '1';
  process.env.JD_BROWSER_SESSION_AUTH_URL = 'http://host.docker.internal:18000/api/jd-workbench/internal/browser-session-authorize';
  await f.start().ready();
  process.env.JD_BROWSER_SESSION_AUTH_URL = 'http://example.invalid:18000/api/jd-workbench/internal/browser-session-authorize';
  assert.throws(f.start, /JD_SESSION_AUTH_DESTINATION_INVALID/);
  process.env.JD_BROWSER_SESSION_AUTH_URL = 'http://host.docker.internal:18000/credential-sink';
  assert.throws(f.start, /JD_SESSION_AUTH_DESTINATION_INVALID/);
  process.env.APP_ENV = 'production';
  f.options.sessionNamespace = 'r297-' + crypto.randomBytes(12).toString('hex');
  process.env.JD_BROWSER_SESSION_AUTH_URL = 'http://host.docker.internal:18000/api/jd-workbench/internal/browser-session-authorize';
  assert.throws(f.start, /JD_SESSION_AUTH_DESTINATION_INVALID/);
});
