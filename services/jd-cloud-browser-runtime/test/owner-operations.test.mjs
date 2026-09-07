import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs/promises';
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
