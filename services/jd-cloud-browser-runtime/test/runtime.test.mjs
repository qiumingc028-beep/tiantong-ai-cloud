import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { buildApp } from '../server.mjs';

const controlToken = 'i'.repeat(32);
const captureToken = 'c'.repeat(32);
const viewerSigningKey = 'v'.repeat(32);
const viewerCookieSigningKey = 'o'.repeat(32);
const masterKey = Buffer.alloc(32, 7).toString('base64');

test('viewer ticket and cookie keys are independently required', () => {
  assert.throws(
    () => buildApp({
      captureToken,
      controlToken,
      viewerTicketSigningKey: viewerSigningKey,
      masterKey
    }),
    /JD_BROWSER_VIEWER_COOKIE_SIGNING_KEY_REQUIRED/
  );
  assert.throws(
    () => buildApp({
      captureToken,
      controlToken,
      viewerTicketSigningKey: viewerSigningKey,
      viewerCookieSigningKey: viewerSigningKey,
      masterKey
    }),
    /JD_BROWSER_CAPABILITY_TOKENS_MUST_BE_DISTINCT/
  );
});

async function activeApp(t, { now = Date.now, storeId }) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'jd-viewer-test-'));
  const context = {
    route: async () => {}, storageState: async () => ({ cookies: [] }), close: async () => {}, pages: () => []
  };
  const app = buildApp({
    captureToken, controlToken, viewerTicketSigningKey: viewerSigningKey, viewerCookieSigningKey, masterKey, now,
    authorizeSession: async () => true,
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
  const app = buildApp({ captureToken, controlToken, viewerTicketSigningKey: viewerSigningKey, viewerCookieSigningKey, masterKey });
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
  const app = buildApp({ captureToken, controlToken, viewerTicketSigningKey: viewerSigningKey, viewerCookieSigningKey, masterKey });
  t.after(() => app.close());
  const controlHeaders = { 'x-internal-token': controlToken };
  const captureHeaders = { 'x-internal-token': captureToken };
  assert.equal((await app.inject({ method: 'GET', url: '/internal/jd-browser/health', headers: captureHeaders })).statusCode, 401);
  assert.equal((await app.inject({ method: 'POST', url: '/internal/jd-browser/capture', headers: controlHeaders })).statusCode, 401);
});

test('explicit controlled dashboard is used by the real capture path', async (t) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'jd-runtime-canary-'));
  const visited = [];
  const page = {
    goto: async (url) => { visited.push(url); },
    evaluate: async () => ({ gmv: '1.00', orders: '1' })
  };
  const app = buildApp({
    captureToken,
    controlToken,
    viewerTicketSigningKey: viewerSigningKey,
    viewerCookieSigningKey,
    masterKey,
    dashboardUrl: 'http://host.docker.internal:18789/controlled-canary',
    authorizeSession: async () => true,
    profileRoot: path.join(root, 'profiles'),
    archiveRoot: path.join(root, 'archives'),
    launchContext: async () => ({
      route: async () => {},
      storageState: async () => ({ cookies: [] }),
      close: async () => {},
      pages: () => [page]
    })
  });
  t.after(async () => { await app.close(); await fs.rm(root, { recursive: true, force: true }); });
  const headers = { 'x-internal-token': controlToken };
  assert.equal((await app.inject({
    method: 'POST', url: '/internal/jd-browser/sessions', headers,
    payload: { tenant_id: 1, company_id: 2, store_id: 3, platform: 'jd' }
  })).statusCode, 200);
  const captured = await app.inject({
    method: 'POST', url: '/internal/jd-browser/capture',
    headers: { 'x-internal-token': captureToken },
    payload: { tenant_id: 1, company_id: 2, store_id: 3, platform: 'jd', dataset: 'metrics' }
  });
  assert.equal(captured.statusCode, 200);
  assert.equal(captured.json().status, 'OK');
  assert.equal(captured.json().data.gmv, '1.00');
  assert.deepEqual(visited, ['http://host.docker.internal:18789/controlled-canary']);
});

test('capability credentials must be distinct', () => {
  assert.throws(
    () => buildApp({ captureToken: controlToken, controlToken, viewerTicketSigningKey: viewerSigningKey, viewerCookieSigningKey, masterKey }),
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
  const claims = JSON.parse(Buffer.from(ticket.split('.')[0], 'base64url').toString('utf8'));
  assert.deepEqual(Object.keys(claims).sort(), [
    'aud', 'company_id', 'expires_at', 'iss', 'issued_at', 'jti', 'platform',
    'session_id', 'session_nonce', 'store_id', 'tenant_id', 'typ'
  ]);

  assert.equal((await app.inject({
    method: 'GET', url: `/internal/jd-browser/viewer/authorize?ticket=${ticket}`,
    headers: { 'x-original-uri': '/jd-browser/novnc/store/vnc.html' }
  })).statusCode, 401);
  assert.equal((await app.inject({
    method: 'GET', url: '/internal/jd-browser/viewer/authorize',
    headers: { cookie: `jd_browser_session=${ticket}`, 'x-original-uri': '/jd-browser/novnc/store/vnc.html' }
  })).statusCode, 401);
  const consumed = await app.inject({
    method: 'POST', url: '/internal/jd-browser/viewer/exchange/store', payload: { ticket }
  });
  assert.equal(consumed.statusCode, 204);
  const cookie = consumed.headers['set-cookie'];
  assert.match(cookie, /^jd_browser_session=/);

  assert.equal((await app.inject({
    method: 'POST', url: '/internal/jd-browser/viewer/exchange/store', payload: { ticket }
  })).statusCode, 401);
  assert.equal((await app.inject({
    method: 'POST', url: `/internal/jd-browser/viewer/exchange/store?ticket=${ticket}`, payload: { ticket }
  })).statusCode, 400);
  assert.equal((await app.inject({
    method: 'GET',
    url: '/internal/jd-browser/viewer/authorize', headers: { cookie, 'x-original-uri': '/jd-browser/novnc/store/vnc.html' }
  })).statusCode, 204);

  const sessionPath = `/internal/jd-browser/sessions/${encodeURIComponent('tenant:company:store:jd')}`;
  assert.equal((await app.inject({
    method: 'DELETE', url: sessionPath, headers: { 'x-internal-token': controlToken }
  })).statusCode, 200);
  assert.equal((await app.inject({
    method: 'POST', url: '/internal/jd-browser/sessions', headers: { 'x-internal-token': controlToken },
    payload: { tenant_id: 'tenant', company_id: 'company', store_id: 'store', platform: 'jd' }
  })).statusCode, 200);
  assert.equal((await app.inject({
    method: 'POST', url: '/internal/jd-browser/viewer/exchange/store', payload: { ticket }
  })).statusCode, 401, 'a deleted session generation cannot replay its ticket after recreation');
  assert.equal((await app.inject({
    method: 'GET', url: '/internal/jd-browser/viewer/authorize',
    headers: { cookie, 'x-original-uri': '/jd-browser/novnc/store/vnc.html' }
  })).statusCode, 401, 'a deleted session generation cannot reuse its cookie after recreation');

  now += 599_000;
  const nearlyExpired = await app.inject({
    method: 'POST', url: '/internal/jd-browser/sessions', headers: { 'x-internal-token': controlToken },
    payload: { tenant_id: 'tenant', company_id: 'company', store_id: 'store', platform: 'jd' }
  });
  assert.equal(nearlyExpired.json().expires_in, 1, 'existing sessions report remaining TTL without extension');
  now += 2_000;
  assert.equal((await app.inject({
    method: 'GET',
    url: '/internal/jd-browser/viewer/authorize', headers: { cookie, 'x-original-uri': '/jd-browser/novnc/store/vnc.html' }
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
    method: 'POST', url: '/internal/jd-browser/viewer/exchange/expired', payload: { ticket: issued.json().ticket }
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
    method: 'POST', url: '/internal/jd-browser/viewer/exchange/store-b', payload: { ticket }
  })).statusCode, 401);
  const consumed = await app.inject({
    method: 'POST', url: '/internal/jd-browser/viewer/exchange/store-a', payload: { ticket }
  });
  assert.equal(consumed.statusCode, 204);
  assert.match(consumed.headers['set-cookie'], /Path=\/jd-browser\/novnc\/store-a\/; HttpOnly; Secure; SameSite=Strict/);
  assert.equal((await app.inject({
    method: 'GET',
    url: '/internal/jd-browser/viewer/authorize',
    headers: { cookie: consumed.headers['set-cookie'], 'x-original-uri': '/jd-browser/novnc/store-b/vnc.html' }
  })).statusCode, 401);
});

test('consumed viewer ticket remains rejected after runtime restart', async (t) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'jd-viewer-restart-'));
  const context = { route: async () => {}, storageState: async () => ({ cookies: [] }), close: async () => {}, pages: () => [] };
  const options = {
    captureToken, controlToken, viewerTicketSigningKey: viewerSigningKey, viewerCookieSigningKey, masterKey,
    authorizeSession: async () => true,
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
    method: 'POST', url: '/internal/jd-browser/viewer/exchange/restart', payload: { ticket }
  };
  assert.equal((await first.inject(request)).statusCode, 204);
  await first.close();
  const second = buildApp(options);
  t.after(async () => { await second.close(); await fs.rm(root, { recursive: true, force: true }); });
  assert.equal((await create(second)).statusCode, 200);
  assert.equal((await second.inject(request)).statusCode, 401);
});

test('graceful restart restores encrypted state and revoke removes every session artifact', async (t) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'jd-runtime-test-'));
  const archiveRoot = path.join(root, 'archives');
  let closeCount = 0;
  const contexts = [];
  const launchContext = async (_directory, restored) => {
    const context = {
      route: async () => {},
      storageState: async () => ({
        cookies: [{ name: 'session', value: 'plaintext-secret' }],
        origins: [{ origin: 'https://shop.jd.com', localStorage: [{ name: 'mode', value: 'readonly' }] }]
      }),
      addCookies: async (cookies) => { context.restoredCookies = cookies; },
      addInitScript: async (_script, state) => { context.restoredOrigins = state.origins; },
      close: async () => { closeCount += 1; }
    };
    contexts.push({ context, restored });
    return context;
  };
  const options = {
    captureToken,
    controlToken,
    viewerTicketSigningKey: viewerSigningKey,
    viewerCookieSigningKey,
    masterKey,
    authorizeSession: async () => true,
    profileRoot: path.join(root, 'profiles'),
    archiveRoot,
    launchContext
  };
  const first = buildApp(options);
  t.after(async () => {
    await fs.rm(root, { recursive: true, force: true });
  });

  const created = await first.inject({
    method: 'POST',
    url: '/internal/jd-browser/sessions',
    headers: { 'x-internal-token': controlToken },
    payload: { tenant_id: 1, company_id: 2, store_id: 3, platform: 'jd' }
  });
  assert.equal(created.statusCode, 200);
  await first.close();
  assert.equal(closeCount, 1);
  const files = await fs.readdir(archiveRoot);
  assert.equal(files.filter((name) => name.endsWith('.enc')).length, 1);
  assert.equal(files.filter((name) => name.endsWith('.tmp')).length, 0);
  const encrypted = await fs.readFile(path.join(archiveRoot, files.find((name) => name.endsWith('.enc'))));
  assert.equal(encrypted.includes(Buffer.from('plaintext-secret')), false);

  const second = buildApp(options);
  const restored = await second.inject({
    method: 'POST',
    url: '/internal/jd-browser/sessions',
    headers: { 'x-internal-token': controlToken },
    payload: { tenant_id: 1, company_id: 2, store_id: 3, platform: 'jd' }
  });
  assert.equal(restored.statusCode, 200);
  assert.equal(restored.json().restored, true);
  assert.deepEqual(contexts[1].context.restoredCookies, [{ name: 'session', value: 'plaintext-secret' }]);
  assert.deepEqual(contexts[1].context.restoredOrigins, [
    { origin: 'https://shop.jd.com', localStorage: [{ name: 'mode', value: 'readonly' }] }
  ]);
  const removed = await second.inject({
    method: 'DELETE',
    url: `/internal/jd-browser/sessions/${encodeURIComponent(created.json().session_id)}`,
    headers: { 'x-internal-token': controlToken }
  });
  assert.equal(removed.statusCode, 200);
  assert.equal(closeCount, 2);
  assert.equal((await fs.readdir(archiveRoot)).filter((name) => name.endsWith('.enc')).length, 0);
  assert.deepEqual(await fs.readdir(path.join(root, 'profiles')), []);
  await second.close();
});

test('database revocation invalidates viewer and capture access and control can always destroy', async (t) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'jd-runtime-revoke-'));
  let authorized = true;
  const context = {
    route: async () => {}, storageState: async () => ({ cookies: [] }), close: async () => {}, pages: () => []
  };
  const app = buildApp({
    captureToken, controlToken, viewerTicketSigningKey: viewerSigningKey, viewerCookieSigningKey,
    masterKey, authorizeSession: async () => authorized,
    profileRoot: path.join(root, 'profiles'), archiveRoot: path.join(root, 'archives'),
    launchContext: async () => context
  });
  t.after(async () => { await app.close(); await fs.rm(root, { recursive: true, force: true }); });
  const id = 'tenant:company:revoked:jd';
  assert.equal((await app.inject({
    method: 'POST', url: '/internal/jd-browser/sessions', headers: { 'x-internal-token': controlToken },
    payload: { tenant_id: 'tenant', company_id: 'company', store_id: 'revoked', platform: 'jd' }
  })).statusCode, 200);
  const ticket = (await app.inject({
    method: 'POST', url: '/internal/jd-browser/tickets', headers: { 'x-internal-token': controlToken },
    payload: { session_id: id }
  })).json().ticket;
  const exchanged = await app.inject({
    method: 'POST', url: '/internal/jd-browser/viewer/exchange/revoked', payload: { ticket }
  });
  const cookie = exchanged.headers['set-cookie'];
  authorized = false;
  assert.equal((await app.inject({
    method: 'GET', url: '/internal/jd-browser/viewer/authorize',
    headers: { cookie, 'x-original-uri': '/jd-browser/novnc/revoked/vnc.html' }
  })).statusCode, 401);
  assert.equal((await app.inject({
    method: 'POST', url: '/internal/jd-browser/capture', headers: { 'x-internal-token': captureToken },
    payload: { tenant_id: 'tenant', company_id: 'company', store_id: 'revoked', platform: 'jd' }
  })).statusCode, 409);
  assert.equal((await app.inject({
    method: 'DELETE', url: `/internal/jd-browser/sessions/${encodeURIComponent(id)}`,
    headers: { 'x-internal-token': controlToken }
  })).statusCode, 200);
});

test('session initialization failure closes Chromium and removes plaintext profile', async (t) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'jd-runtime-init-failure-'));
  let closed = 0;
  const app = buildApp({
    captureToken, controlToken, viewerTicketSigningKey: viewerSigningKey, viewerCookieSigningKey,
    masterKey, authorizeSession: async () => true,
    profileRoot: path.join(root, 'profiles'), archiveRoot: path.join(root, 'archives'),
    launchContext: async () => ({
      route: async () => { throw new Error('POLICY_INSTALL_FAILED'); },
      storageState: async () => ({ cookies: [] }), close: async () => { closed += 1; }, pages: () => []
    })
  });
  t.after(async () => { await app.close(); await fs.rm(root, { recursive: true, force: true }); });
  assert.equal((await app.inject({
    method: 'POST', url: '/internal/jd-browser/sessions', headers: { 'x-internal-token': controlToken },
    payload: { tenant_id: 'tenant', company_id: 'company', store_id: 'init-fail', platform: 'jd' }
  })).statusCode, 500);
  assert.equal(closed, 1);
  assert.deepEqual(await fs.readdir(path.join(root, 'profiles')), []);
});

test('expired dormant archive and ticket markers are purged without restoring the store', async (t) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'jd-runtime-dormant-expiry-'));
  let now = 4_000_000;
  const options = {
    captureToken, controlToken, viewerTicketSigningKey: viewerSigningKey, viewerCookieSigningKey,
    masterKey, now: () => now, authorizeSession: async () => true,
    profileRoot: path.join(root, 'profiles'), archiveRoot: path.join(root, 'archives'),
    launchContext: async () => ({
      route: async () => {}, storageState: async () => ({ cookies: [] }), close: async () => {}, pages: () => []
    })
  };
  const first = buildApp(options);
  const id = 'tenant:company:dormant:jd';
  await first.inject({
    method: 'POST', url: '/internal/jd-browser/sessions', headers: { 'x-internal-token': controlToken },
    payload: { tenant_id: 'tenant', company_id: 'company', store_id: 'dormant', platform: 'jd' }
  });
  const ticket = (await first.inject({
    method: 'POST', url: '/internal/jd-browser/tickets', headers: { 'x-internal-token': controlToken },
    payload: { session_id: id }
  })).json().ticket;
  await first.inject({ method: 'POST', url: '/internal/jd-browser/viewer/exchange/dormant', payload: { ticket } });
  await first.close();
  now += 601_000;
  const second = buildApp(options);
  t.after(async () => { await second.close(); await fs.rm(root, { recursive: true, force: true }); });
  assert.equal((await second.inject({
    method: 'GET', url: '/internal/jd-browser/health', headers: { 'x-internal-token': controlToken }
  })).statusCode, 200);
  assert.equal((await fs.readdir(path.join(root, 'archives'))).filter((name) => name.endsWith('.enc')).length, 0);
  assert.deepEqual(await fs.readdir(path.join(root, 'archives', '.used-viewer-tickets')), []);
});

test('revoke removes all artifacts even when Chromium context close fails', async (t) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'jd-runtime-cleanup-'));
  const archiveRoot = path.join(root, 'archives');
  const profileRoot = path.join(root, 'profiles');
  const app = buildApp({
    captureToken, controlToken, viewerTicketSigningKey: viewerSigningKey, viewerCookieSigningKey,
    masterKey, authorizeSession: async () => true, archiveRoot, profileRoot,
    launchContext: async () => ({
      route: async () => {}, storageState: async () => ({ cookies: [] }), pages: () => [],
      close: async () => { throw new Error('CHROMIUM_CLOSE_FAILED'); }
    })
  });
  t.after(async () => { await fs.rm(root, { recursive: true, force: true }); });
  const id = 'tenant:company:cleanup:jd';
  assert.equal((await app.inject({
    method: 'POST', url: '/internal/jd-browser/sessions', headers: { 'x-internal-token': controlToken },
    payload: { tenant_id: 'tenant', company_id: 'company', store_id: 'cleanup', platform: 'jd' }
  })).statusCode, 200);
  const ticket = (await app.inject({
    method: 'POST', url: '/internal/jd-browser/tickets', headers: { 'x-internal-token': controlToken },
    payload: { session_id: id }
  })).json().ticket;
  assert.equal((await app.inject({
    method: 'POST', url: '/internal/jd-browser/viewer/exchange/cleanup', payload: { ticket }
  })).statusCode, 204);
  assert.equal((await app.inject({
    method: 'DELETE', url: `/internal/jd-browser/sessions/${encodeURIComponent(id)}`,
    headers: { 'x-internal-token': controlToken }
  })).statusCode, 500);
  assert.deepEqual(await fs.readdir(profileRoot), []);
  assert.equal((await fs.readdir(archiveRoot)).filter((name) => name.endsWith('.enc')).length, 0);
  assert.deepEqual(await fs.readdir(path.join(archiveRoot, '.used-viewer-tickets')), []);
});

test('wrong key, corrupt archive, and cross-store archive replacement are rejected', async (t) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'jd-runtime-archive-'));
  const archiveRoot = path.join(root, 'archives');
  const profileRoot = path.join(root, 'profiles');
  const context = {
    route: async () => {}, storageState: async () => ({ cookies: [] }), close: async () => {}, pages: () => []
  };
  const options = {
    captureToken, controlToken, viewerTicketSigningKey: viewerSigningKey, viewerCookieSigningKey,
    masterKey, authorizeSession: async () => true, archiveRoot, profileRoot,
    launchContext: async () => context
  };
  const create = (app, store) => app.inject({
    method: 'POST', url: '/internal/jd-browser/sessions', headers: { 'x-internal-token': controlToken },
    payload: { tenant_id: 'tenant', company_id: 'company', store_id: store, platform: 'jd' }
  });
  const first = buildApp(options);
  assert.equal((await create(first, 'store-a')).statusCode, 200);
  await first.close();
  const [archive] = (await fs.readdir(archiveRoot)).filter((name) => name.endsWith('.enc'));

  const wrongKey = buildApp({ ...options, masterKey: Buffer.alloc(32, 8).toString('base64') });
  assert.equal((await create(wrongKey, 'store-a')).statusCode, 409);
  await wrongKey.close();

  const storeBArchive = `${crypto.createHash('sha256').update('tenant:company:store-b:jd').digest('hex')}.enc`;
  await fs.copyFile(path.join(archiveRoot, archive), path.join(archiveRoot, storeBArchive));
  const crossStore = buildApp(options);
  assert.equal((await create(crossStore, 'store-b')).statusCode, 409);
  await crossStore.close();

  await fs.writeFile(path.join(archiveRoot, archive), Buffer.from('corrupt'));
  const corrupt = buildApp(options);
  assert.equal((await create(corrupt, 'store-a')).statusCode, 409);
  await corrupt.close();
  t.after(() => fs.rm(root, { recursive: true, force: true }));
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
    viewerTicketSigningKey: viewerSigningKey,
    viewerCookieSigningKey,
    masterKey,
    authorizeSession: async () => true,
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
