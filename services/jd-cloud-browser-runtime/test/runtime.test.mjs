import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { buildApp } from '../server.mjs';

const internalToken = 'i'.repeat(32);
const masterKey = Buffer.alloc(32, 7).toString('base64');

test('health is internal-token gated', async (t) => {
  const app = buildApp({ internalToken, masterKey });
  t.after(() => app.close());

  assert.equal((await app.inject({ method: 'GET', url: '/internal/jd-browser/health' })).statusCode, 401);
  const response = await app.inject({
    method: 'GET',
    url: '/internal/jd-browser/health',
    headers: { 'x-internal-token': internalToken }
  });
  assert.equal(response.statusCode, 200);
  assert.equal(response.json().service, 'jd-cloud-browser-runtime');
});

test('backend ticket is single-use and exchanges for a short-lived noVNC cookie', async (t) => {
  let now = 1_000_000;
  const app = buildApp({ internalToken, masterKey, now: () => now });
  t.after(() => app.close());

  const issued = await app.inject({
    method: 'POST',
    url: '/internal/jd-browser/tickets',
    headers: { 'x-internal-token': internalToken },
    payload: { session_id: 'tenant:company:store:jd' }
  });
  assert.equal(issued.statusCode, 200);
  const ticket = issued.json().ticket;
  assert.match(ticket, /^[a-f0-9]{64}$/);

  const consumed = await app.inject({
    method: 'GET',
    url: `/internal/jd-browser/novnc-auth?ticket=${ticket}`
  });
  assert.equal(consumed.statusCode, 204);
  const cookie = consumed.headers['set-cookie'];
  assert.match(cookie, /^jd_browser_session=/);

  assert.equal((await app.inject({
    method: 'GET',
    url: `/internal/jd-browser/novnc-auth?ticket=${ticket}`
  })).statusCode, 401);
  assert.equal((await app.inject({
    method: 'GET',
    url: '/internal/jd-browser/novnc-auth',
    headers: { cookie }
  })).statusCode, 204);

  now += 601_000;
  assert.equal((await app.inject({
    method: 'GET',
    url: '/internal/jd-browser/novnc-auth',
    headers: { cookie }
  })).statusCode, 401);
});

test('expired backend ticket is rejected without creating a session', async (t) => {
  let now = 2_000_000;
  const app = buildApp({ internalToken, masterKey, now: () => now });
  t.after(() => app.close());
  const issued = await app.inject({
    method: 'POST',
    url: '/internal/jd-browser/tickets',
    headers: { 'x-internal-token': internalToken },
    payload: { session_id: 'tenant:company:expired:jd' }
  });
  now += 61_000;
  assert.equal((await app.inject({
    method: 'GET',
    url: `/internal/jd-browser/novnc-auth?ticket=${issued.json().ticket}`
  })).statusCode, 401);
});

test('closing a browser session writes only an encrypted archive', async (t) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'jd-runtime-test-'));
  const archiveRoot = path.join(root, 'archives');
  let closeCount = 0;
  const context = {
    route: async () => {},
    storageState: async () => ({ cookies: [{ name: 'session', value: 'plaintext-secret' }] }),
    close: async () => { closeCount += 1; }
  };
  const app = buildApp({
    internalToken,
    masterKey,
    profileRoot: path.join(root, 'profiles'),
    archiveRoot,
    launchContext: async () => context
  });
  t.after(async () => {
    await app.close();
    await fs.rm(root, { recursive: true, force: true });
  });

  const created = await app.inject({
    method: 'POST',
    url: '/internal/jd-browser/sessions',
    headers: { 'x-internal-token': internalToken },
    payload: { tenant_id: 1, company_id: 2, store_id: 3, platform: 'jd' }
  });
  assert.equal(created.statusCode, 200);
  const removed = await app.inject({
    method: 'DELETE',
    url: `/internal/jd-browser/sessions/${encodeURIComponent(created.json().session_id)}`,
    headers: { 'x-internal-token': internalToken }
  });
  assert.equal(removed.statusCode, 200);
  assert.equal(closeCount, 1);
  const files = await fs.readdir(archiveRoot);
  assert.equal(files.length, 1);
  const encrypted = await fs.readFile(path.join(archiveRoot, files[0]));
  assert.equal(encrypted.includes(Buffer.from('plaintext-secret')), false);
});

test('one display serves only one active session and expiry closes it', async (t) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'jd-runtime-single-session-'));
  let now = 3_000_000;
  let closeCount = 0;
  const context = {
    route: async () => {},
    storageState: async () => ({ cookies: [] }),
    close: async () => { closeCount += 1; }
  };
  const app = buildApp({
    internalToken,
    masterKey,
    now: () => now,
    profileRoot: path.join(root, 'profiles'),
    archiveRoot: path.join(root, 'archives'),
    launchContext: async () => context
  });
  t.after(async () => {
    await app.close();
    await fs.rm(root, { recursive: true, force: true });
  });
  const headers = { 'x-internal-token': internalToken };
  const first = await app.inject({
    method: 'POST', url: '/internal/jd-browser/sessions', headers,
    payload: { tenant_id: 1, company_id: 2, store_id: 3, platform: 'jd' }
  });
  assert.equal(first.statusCode, 200);
  assert.equal((await app.inject({
    method: 'POST', url: '/internal/jd-browser/sessions', headers,
    payload: { tenant_id: 1, company_id: 2, store_id: 4, platform: 'jd' }
  })).statusCode, 409);
  assert.equal((await app.inject({
    method: 'POST', url: '/internal/jd-browser/tickets', headers,
    payload: { session_id: '1:2:4:jd' }
  })).statusCode, 409);

  now += 601_000;
  const status = await app.inject({
    method: 'GET',
    url: `/internal/jd-browser/sessions/${encodeURIComponent(first.json().session_id)}`,
    headers
  });
  assert.equal(status.json().status, 'REVOKED');
  assert.equal(closeCount, 1);
});
