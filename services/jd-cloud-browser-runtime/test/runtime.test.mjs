import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { buildApp } from '../server.mjs';

const controlToken = 'i'.repeat(32);
const captureToken = 'c'.repeat(32);
const viewerSigningKey = 'v'.repeat(32);
const masterKey = Buffer.alloc(32, 7).toString('base64');

async function activeApp(t, { now = Date.now, storeId }) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'jd-viewer-test-'));
  const context = {
    route: async () => {}, storageState: async () => ({ cookies: [] }), close: async () => {}, pages: () => []
  };
  const app = buildApp({
    captureToken, controlToken, viewerSigningKey, masterKey, now,
    profileRoot: path.join(root, 'profiles'), archiveRoot: path.join(root, 'archives'),
    launchContext: async () => context
  });
  t.after(async () => { await app.close(); await fs.rm(root, { recursive: true, force: true }); });
  const created = await app.inject({
    method: 'POST', url: '/internal/jd-browser/sessions',
    headers: { 'x-internal-token': controlToken },
    payload: { tenant_id: 'tenant', company_id: 'company', store_id: storeId, platform: 'jd' }
  });
  assert.equal(created.statusCode, 200);
  return app;
}

test('health is internal-token gated', async (t) => {
  const app = buildApp({ captureToken, controlToken, viewerSigningKey, masterKey });
  t.after(() => app.close());

  assert.equal((await app.inject({ method: 'GET', url: '/internal/jd-browser/health' })).statusCode, 401);
  const response = await app.inject({
    method: 'GET',
    url: '/internal/jd-browser/health',
    headers: { 'x-internal-token': controlToken }
  });
  assert.equal(response.statusCode, 200);
  assert.equal(response.json().service, 'jd-cloud-browser-runtime');
});

test('capture and control credentials cannot be used interchangeably', async (t) => {
  const app = buildApp({ captureToken, controlToken, viewerSigningKey, masterKey });
  t.after(() => app.close());
  const controlHeaders = { 'x-internal-token': controlToken };
  const captureHeaders = { 'x-internal-token': captureToken };
  assert.equal((await app.inject({ method: 'GET', url: '/internal/jd-browser/health', headers: captureHeaders })).statusCode, 401);
  assert.equal((await app.inject({ method: 'POST', url: '/internal/jd-browser/capture', headers: controlHeaders })).statusCode, 401);
});

test('capability credentials must be distinct', () => {
  assert.throws(
    () => buildApp({ captureToken: controlToken, controlToken, viewerSigningKey, masterKey }),
    /JD_BROWSER_CAPABILITY_TOKENS_MUST_BE_DISTINCT/
  );
});

test('backend ticket is single-use and exchanges for a short-lived noVNC cookie', async (t) => {
  let now = 1_000_000;
  const app = await activeApp(t, { now: () => now, storeId: 'store' });

  const issued = await app.inject({
    method: 'POST',
    url: '/internal/jd-browser/tickets',
    headers: { 'x-internal-token': controlToken },
    payload: { session_id: 'tenant:company:store:jd' }
  });
  assert.equal(issued.statusCode, 200);
  const ticket = issued.json().ticket;
  assert.match(ticket, /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/);

  const consumed = await app.inject({
    method: 'GET',
    url: `/internal/jd-browser/novnc-auth?ticket=${ticket}`,
    headers: { 'x-original-uri': `/jd-browser/novnc/store/?ticket=${ticket}` }
  });
  assert.equal(consumed.statusCode, 204);
  const cookie = consumed.headers['set-cookie'];
  assert.match(cookie, /^jd_browser_session=/);

  assert.equal((await app.inject({
    method: 'GET',
    url: `/internal/jd-browser/novnc-auth?ticket=${ticket}`,
    headers: { 'x-original-uri': `/jd-browser/novnc/store/?ticket=${ticket}` }
  })).statusCode, 401);
  assert.equal((await app.inject({
    method: 'GET',
    url: '/internal/jd-browser/novnc-auth',
    headers: { cookie, 'x-original-uri': '/jd-browser/novnc/store/' }
  })).statusCode, 204);

  now += 601_000;
  assert.equal((await app.inject({
    method: 'GET',
    url: '/internal/jd-browser/novnc-auth',
    headers: { cookie, 'x-original-uri': '/jd-browser/novnc/store/' }
  })).statusCode, 401);
});

test('expired backend ticket is rejected without creating a session', async (t) => {
  let now = 2_000_000;
  const app = await activeApp(t, { now: () => now, storeId: 'expired' });
  const issued = await app.inject({
    method: 'POST',
    url: '/internal/jd-browser/tickets',
    headers: { 'x-internal-token': controlToken },
    payload: { session_id: 'tenant:company:expired:jd' }
  });
  now += 61_000;
  assert.equal((await app.inject({
    method: 'GET',
    url: `/internal/jd-browser/novnc-auth?ticket=${issued.json().ticket}`,
    headers: { 'x-original-uri': `/jd-browser/novnc/expired/?ticket=${issued.json().ticket}` }
  })).statusCode, 401);
});

test('viewer ticket and cookie are scoped to one store', async (t) => {
  const app = await activeApp(t, { storeId: 'store-a' });
  const issued = await app.inject({
    method: 'POST',
    url: '/internal/jd-browser/tickets',
    headers: { 'x-internal-token': controlToken },
    payload: { session_id: 'tenant:company:store-a:jd' }
  });
  const ticket = issued.json().ticket;
  assert.equal((await app.inject({
    method: 'POST', url: '/internal/jd-browser/tickets',
    headers: { 'x-internal-token': controlToken },
    payload: { session_id: 'tenant:company:store-a:jd', store_id: 'store-b' }
  })).statusCode, 400);
  assert.equal((await app.inject({
    method: 'GET',
    url: `/internal/jd-browser/novnc-auth?ticket=${ticket}`,
    headers: { 'x-original-uri': `/jd-browser/novnc/store-b/?ticket=${ticket}` }
  })).statusCode, 401);
  const consumed = await app.inject({
    method: 'GET',
    url: `/internal/jd-browser/novnc-auth?ticket=${ticket}`,
    headers: { 'x-original-uri': `/jd-browser/novnc/store-a/?ticket=${ticket}` }
  });
  assert.equal(consumed.statusCode, 204);
  assert.match(consumed.headers['set-cookie'], /Path=\/jd-browser\/novnc\/store-a\/; HttpOnly; Secure; SameSite=Strict/);
  assert.equal((await app.inject({
    method: 'GET',
    url: '/internal/jd-browser/novnc-auth',
    headers: { cookie: consumed.headers['set-cookie'], 'x-original-uri': '/jd-browser/novnc/store-b/' }
  })).statusCode, 401);
});

test('consumed viewer ticket remains rejected after runtime restart', async (t) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'jd-viewer-restart-'));
  const context = { route: async () => {}, storageState: async () => ({ cookies: [] }), close: async () => {}, pages: () => [] };
  const options = {
    captureToken, controlToken, viewerSigningKey, masterKey,
    profileRoot: path.join(root, 'profiles'), archiveRoot: path.join(root, 'archives'),
    launchContext: async () => context
  };
  const create = async (app) => app.inject({
    method: 'POST', url: '/internal/jd-browser/sessions', headers: { 'x-internal-token': controlToken },
    payload: { tenant_id: 'tenant', company_id: 'company', store_id: 'restart', platform: 'jd' }
  });
  const first = buildApp(options);
  assert.equal((await create(first)).statusCode, 200);
  const issued = await first.inject({
    method: 'POST', url: '/internal/jd-browser/tickets', headers: { 'x-internal-token': controlToken },
    payload: { session_id: 'tenant:company:restart:jd' }
  });
  const ticket = issued.json().ticket;
  const request = {
    method: 'GET', url: `/internal/jd-browser/novnc-auth?ticket=${ticket}`,
    headers: { 'x-original-uri': `/jd-browser/novnc/restart/?ticket=${ticket}` }
  };
  assert.equal((await first.inject(request)).statusCode, 204);
  await first.close();
  const second = buildApp(options);
  t.after(async () => { await second.close(); await fs.rm(root, { recursive: true, force: true }); });
  assert.equal((await create(second)).statusCode, 200);
  assert.equal((await second.inject(request)).statusCode, 401);
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
    captureToken,
    controlToken,
    viewerSigningKey,
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
    headers: { 'x-internal-token': controlToken },
    payload: { tenant_id: 1, company_id: 2, store_id: 3, platform: 'jd' }
  });
  assert.equal(created.statusCode, 200);
  const removed = await app.inject({
    method: 'DELETE',
    url: `/internal/jd-browser/sessions/${encodeURIComponent(created.json().session_id)}`,
    headers: { 'x-internal-token': controlToken }
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
    captureToken,
    controlToken,
    viewerSigningKey,
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
  const headers = { 'x-internal-token': controlToken };
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
