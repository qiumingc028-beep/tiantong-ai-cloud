'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { createCloudClient, HEARTBEAT_URL, PAIR_URL, STORES_URL, SYNC_URL } = require('./cloud-client');

const temporaryRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'r291-cloud-client-'));
const identityPath = path.join(temporaryRoot, 'identity.json');
let publicKey = null;
const seenNonces = new Set();

const safeStorage = Object.freeze({
  isEncryptionAvailable: () => true,
  getSelectedStorageBackend: () => 'kwallet',
  encryptString: (value) => Buffer.from(`encrypted:${value}`, 'utf8'),
  decryptString: (value) => {
    const decoded = value.toString('utf8');
    assert.ok(decoded.startsWith('encrypted:'));
    return decoded.slice('encrypted:'.length);
  }
});

function jsonResponse(payload, status = 200) {
  return Object.freeze({
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(payload)
  });
}

const net = Object.freeze({
  fetch: async (url, options) => {
    assert.equal(options.cache, 'no-store');
    assert.equal(options.credentials, 'omit');
    assert.equal(options.redirect, 'error');
    if (url === PAIR_URL) {
      const payload = JSON.parse(options.body);
      assert.equal(payload.code, '12345678');
      assert.equal(payload.public_key.kty, 'RSA');
      publicKey = crypto.createPublicKey({ key: payload.public_key, format: 'jwk' });
      return jsonResponse({
        device_id: 'a7d3456a-2ccb-4a67-85c5-a23528c8d4dd',
        device_token: 'r291-test-device-token-that-is-long-enough-for-policy-1234567890',
        expires_at: '2099-01-01T00:00:00Z'
      });
    }

    assert.ok(url === STORES_URL || url === HEARTBEAT_URL || url === SYNC_URL);
    assert.ok(publicKey);
    assert.match(options.headers.Authorization, /^Device /);
    assert.match(options.headers['X-R291-Timestamp'], /^\d{10,11}$/);
    assert.match(options.headers['X-R291-Nonce'], /^[0-9a-f]{32}$/);
    assert.ok(!seenNonces.has(options.headers['X-R291-Nonce']));
    seenNonces.add(options.headers['X-R291-Nonce']);
    const parsedUrl = new URL(url);
    const bodyText = options.body || '';
    const bodyDigest = crypto.createHash('sha256').update(bodyText, 'utf8').digest('hex');
    const canonical = [
      'R291',
      options.headers['X-R291-Timestamp'],
      options.headers['X-R291-Nonce'],
      options.method,
      `${parsedUrl.pathname}${parsedUrl.search}`,
      bodyDigest
    ].join('\n');
    assert.equal(
      crypto.verify(
        'sha256',
        Buffer.from(canonical, 'utf8'),
        { key: publicKey, padding: crypto.constants.RSA_PKCS1_PADDING },
        Buffer.from(options.headers['X-R291-Signature'], 'base64url')
      ),
      true
    );
    if (url === SYNC_URL) {
      const payload = JSON.parse(options.body);
      assert.equal(payload.dataset_type, 'fulfillment_orders');
      assert.equal(payload.records[0].order_state, '待出库');
      assert.equal(payload.records[0].source_record_key.length, 64);
      assert.equal(payload.records[0].order_no, undefined);
      return jsonResponse({ ok: true, accepted: 1 });
    }
    return jsonResponse(url === STORES_URL ? [] : { ok: true, status: 'ONLINE' });
  }
});

(async () => {
  try {
    const first = createCloudClient({ net, safeStorage, identityPath });
    await first.pair({ code: '12345678', deviceName: 'R291 test device' });
    assert.equal(first.isPaired(), true);
    assert.deepEqual(await first.listStores(), []);
    assert.equal((await first.heartbeat({ status: 'ONLINE' })).ok, true);
    assert.equal((await first.syncDataset({
      store: { storeId: 1, subjectId: 1 },
      datasetType: 'fulfillment_orders',
      sourcePeriod: '2026-09-01',
      collectedAt: '2026-09-01T00:00:00Z',
      records: [{ source_record_key: 'a'.repeat(64), order_state: '待出库' }]
    })).accepted, 1);
    const stored = JSON.parse(fs.readFileSync(identityPath, 'utf8'));
    assert.equal(typeof stored.encryptedPrivateKey, 'string');
    assert.equal(stored.deviceToken, undefined);
    assert.equal(stored.privateKey, undefined);

    const restarted = createCloudClient({ net, safeStorage, identityPath });
    assert.equal(restarted.readIdentity(), true);
    assert.deepEqual(await restarted.listStores(), []);
    assert.equal(seenNonces.size, 4);
    console.log('R297_CLOUD_CLIENT_BEHAVIOR=4_SIGNED_REQUESTS_PASS');
  } finally {
    fs.rmSync(temporaryRoot, { recursive: true, force: true });
  }
})().catch((error) => {
  fs.rmSync(temporaryRoot, { recursive: true, force: true });
  console.error(error);
  process.exitCode = 1;
});
