'use strict';

const fs = require('node:fs');
const crypto = require('node:crypto');

const CLOUD_ORIGIN = 'https://internal.tiantongai.com';
const PAIR_URL = `${CLOUD_ORIGIN}/api/jd-workbench/pair`;
const STORES_URL = `${CLOUD_ORIGIN}/api/jd-workbench/stores`;
const HEARTBEAT_URL = `${CLOUD_ORIGIN}/api/jd-workbench/heartbeat`;
const SYNC_URL = `${CLOUD_ORIGIN}/api/jd-workbench/sync`;
const CLIENT_VERSION = '2.97.0-r297';
const MAX_RESPONSE_BYTES = 1024 * 1024;
const REQUEST_TIMEOUT_MS = 15_000;
const DEVICE_UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function clientError(code) {
  const error = new Error(code);
  error.code = code;
  return error;
}

function requireProtectedSafeStorage(safeStorage) {
  if (!safeStorage.isEncryptionAvailable()) {
    throw clientError('SECURE_STORAGE_UNAVAILABLE');
  }
  if (
    process.platform === 'linux' &&
    typeof safeStorage.getSelectedStorageBackend === 'function' &&
    safeStorage.getSelectedStorageBackend() === 'basic_text'
  ) {
    throw clientError('SECURE_STORAGE_BASIC_TEXT_REJECTED');
  }
}

function createCloudClient({ net, safeStorage, identityPath }) {
  let identity = null;

  function readIdentity() {
    requireProtectedSafeStorage(safeStorage);
    let parsed;
    try {
      parsed = JSON.parse(fs.readFileSync(identityPath, 'utf8'));
    } catch (error) {
      if (error && error.code === 'ENOENT') return false;
      throw clientError('DEVICE_IDENTITY_INVALID');
    }
    if (
      !parsed ||
      !DEVICE_UUID_PATTERN.test(String(parsed.deviceId || '')) ||
      typeof parsed.encryptedToken !== 'string' ||
      parsed.encryptedToken.length > 4096 ||
      typeof parsed.encryptedPrivateKey !== 'string' ||
      parsed.encryptedPrivateKey.length > 16384 ||
      typeof parsed.expiresAt !== 'string'
    ) {
      throw clientError('DEVICE_IDENTITY_INVALID');
    }
    let token;
    let privateKeyPem;
    try {
      token = safeStorage.decryptString(Buffer.from(parsed.encryptedToken, 'base64'));
      privateKeyPem = safeStorage.decryptString(Buffer.from(parsed.encryptedPrivateKey, 'base64'));
      crypto.createPrivateKey(privateKeyPem);
    } catch (_error) {
      throw clientError('DEVICE_IDENTITY_INVALID');
    }
    if (!(token.length >= 40 && token.length <= 256)) {
      throw clientError('DEVICE_IDENTITY_INVALID');
    }
    const expiresAt = Date.parse(parsed.expiresAt);
    if (!Number.isFinite(expiresAt) || expiresAt <= Date.now()) {
      throw clientError('DEVICE_AUTHORIZATION_EXPIRED');
    }
    identity = Object.freeze({
      deviceId: parsed.deviceId.toLowerCase(),
      token,
      privateKeyPem,
      expiresAt: new Date(expiresAt).toISOString()
    });
    return true;
  }

  function writeIdentity({ deviceId, deviceToken, privateKeyPem, expiresAt }) {
    requireProtectedSafeStorage(safeStorage);
    if (
      !DEVICE_UUID_PATTERN.test(String(deviceId || '')) ||
      typeof deviceToken !== 'string' ||
      !(deviceToken.length >= 40 && deviceToken.length <= 256) ||
      typeof privateKeyPem !== 'string' ||
      privateKeyPem.length > 8192 ||
      !Number.isFinite(Date.parse(expiresAt))
    ) {
      throw clientError('PAIR_RESPONSE_INVALID');
    }
    const encryptedToken = safeStorage.encryptString(deviceToken).toString('base64');
    let encryptedPrivateKey;
    try {
      crypto.createPrivateKey(privateKeyPem);
      encryptedPrivateKey = safeStorage.encryptString(privateKeyPem).toString('base64');
    } catch (_error) {
      throw clientError('PAIR_RESPONSE_INVALID');
    }
    const serialized = JSON.stringify({
      deviceId: deviceId.toLowerCase(),
      encryptedToken,
      encryptedPrivateKey,
      expiresAt: new Date(Date.parse(expiresAt)).toISOString()
    });
    const temporaryPath = `${identityPath}.tmp`;
    fs.writeFileSync(temporaryPath, serialized, { encoding: 'utf8', mode: 0o600 });
    fs.renameSync(temporaryPath, identityPath);
    identity = Object.freeze({
      deviceId: deviceId.toLowerCase(),
      token: deviceToken,
      privateKeyPem,
      expiresAt: new Date(Date.parse(expiresAt)).toISOString()
    });
  }

  async function requestJson({ url, method, body, authenticated }) {
    if (url !== PAIR_URL && url !== STORES_URL && url !== HEARTBEAT_URL && url !== SYNC_URL) {
      throw clientError('CLOUD_ENDPOINT_REJECTED');
    }
    if (authenticated && !identity) throw clientError('DEVICE_NOT_PAIRED');

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    const headers = Object.create(null);
    headers.Accept = 'application/json';
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    const bodyText = body === undefined ? '' : JSON.stringify(body);
    if (authenticated) {
      const timestamp = String(Math.floor(Date.now() / 1000));
      const nonce = crypto.randomBytes(16).toString('hex');
      const parsedUrl = new URL(url);
      const requestPath = `${parsedUrl.pathname}${parsedUrl.search}`;
      const bodyDigest = crypto.createHash('sha256').update(bodyText, 'utf8').digest('hex');
      const canonical = ['R291', timestamp, nonce, method, requestPath, bodyDigest].join('\n');
      const signature = crypto.sign(
        'sha256',
        Buffer.from(canonical, 'utf8'),
        { key: identity.privateKeyPem, padding: crypto.constants.RSA_PKCS1_PADDING }
      ).toString('base64url');
      headers.Authorization = `Device ${identity.token}`;
      headers['X-R291-Timestamp'] = timestamp;
      headers['X-R291-Nonce'] = nonce;
      headers['X-R291-Signature'] = signature;
    }

    let response;
    try {
      response = await net.fetch(url, {
        method,
        headers,
        body: body === undefined ? undefined : bodyText,
        cache: 'no-store',
        credentials: 'omit',
        redirect: 'error',
        signal: controller.signal
      });
    } catch (_error) {
      throw clientError('CLOUD_CONNECTION_FAILED');
    } finally {
      clearTimeout(timeout);
    }

    if (response.status === 401 || response.status === 403) {
      throw clientError('AUTHORIZATION_REVOKED');
    }
    if (!response.ok) throw clientError('CLOUD_REQUEST_REJECTED');

    const text = await response.text();
    if (Buffer.byteLength(text, 'utf8') > MAX_RESPONSE_BYTES) {
      throw clientError('CLOUD_RESPONSE_TOO_LARGE');
    }
    try {
      return JSON.parse(text);
    } catch (_error) {
      throw clientError('CLOUD_RESPONSE_INVALID');
    }
  }

  async function pair({ code, deviceName }) {
    requireProtectedSafeStorage(safeStorage);
    const pairingCode = String(code || '').trim();
    const cleanDeviceName = String(deviceName || '')
      .replace(/[\u0000-\u001f\u007f]/g, '')
      .trim()
      .slice(0, 120);
    if (!/^\d{8}$/.test(pairingCode) || !cleanDeviceName) {
      throw clientError('PAIR_REQUEST_INVALID');
    }
    const { publicKey, privateKey } = crypto.generateKeyPairSync('rsa', {
      modulusLength: 2048,
      publicExponent: 0x10001
    });
    const publicKeyJwk = publicKey.export({ format: 'jwk' });
    const privateKeyPem = privateKey.export({ format: 'pem', type: 'pkcs8' }).toString();
    const result = await requestJson({
      url: PAIR_URL,
      method: 'POST',
      authenticated: false,
      body: {
        code: pairingCode,
        device_name: cleanDeviceName,
        client_version: CLIENT_VERSION,
        public_key: { kty: publicKeyJwk.kty, n: publicKeyJwk.n, e: publicKeyJwk.e }
      }
    });
    writeIdentity({
      deviceId: result && result.device_id,
      deviceToken: result && result.device_token,
      privateKeyPem,
      expiresAt: result && result.expires_at
    });
    return Object.freeze({ deviceId: identity.deviceId, expiresAt: identity.expiresAt });
  }

  async function listStores() {
    const result = await requestJson({
      url: STORES_URL,
      method: 'GET',
      authenticated: true
    });
    if (!Array.isArray(result)) throw clientError('CLOUD_RESPONSE_INVALID');
    return result;
  }

  async function heartbeat({ status = 'ONLINE', storeId = null, reasonCode = null, lastAttemptAt = null, nextSyncAt = null, retryCount = 0 } = {}) {
    const allowedStatuses = new Set(['ONLINE', 'IDLE', 'SYNCING', 'PAUSED', 'OFFLINE', 'ERROR', 'HUMAN_ACTION_REQUIRED']);
    if (!allowedStatuses.has(status)) throw clientError('HEARTBEAT_REQUEST_INVALID');
    const body = { client_version: CLIENT_VERSION, status };
    if (storeId !== null) {
      if (!Number.isSafeInteger(storeId) || storeId <= 0) throw clientError('HEARTBEAT_REQUEST_INVALID');
      body.store_id = storeId;
    }
    if (reasonCode !== null) {
      if (typeof reasonCode !== 'string' || !/^[A-Z_]{3,64}$/.test(reasonCode)) {
        throw clientError('HEARTBEAT_REQUEST_INVALID');
      }
      body.reason_code = reasonCode;
    }
    if (!Number.isInteger(retryCount) || retryCount < 0 || retryCount > 5) {
      throw clientError('HEARTBEAT_REQUEST_INVALID');
    }
    body.retry_count = retryCount;
    for (const [field, value] of [['last_attempt_at', lastAttemptAt], ['next_sync_at', nextSyncAt]]) {
      if (value === null) continue;
      if (!Number.isFinite(Date.parse(value))) throw clientError('HEARTBEAT_REQUEST_INVALID');
      body[field] = new Date(Date.parse(value)).toISOString();
    }
    return requestJson({
      url: HEARTBEAT_URL,
      method: 'POST',
      authenticated: true,
      body
    });
  }

  async function syncDataset({ store, datasetType, sourcePeriod, collectedAt, records }) {
    if (!store || !Number.isSafeInteger(store.storeId) || !Number.isSafeInteger(store.subjectId)) {
      throw clientError('SYNC_REQUEST_INVALID');
    }
    if (typeof datasetType !== 'string' || !Array.isArray(records) || !Number.isFinite(Date.parse(collectedAt))) {
      throw clientError('SYNC_REQUEST_INVALID');
    }
    const digest = crypto.createHash('sha256')
      .update(JSON.stringify({ storeId: store.storeId, datasetType, sourcePeriod, records }), 'utf8')
      .digest('hex');
    return requestJson({
      url: SYNC_URL,
      method: 'POST',
      authenticated: true,
      body: {
        store_id: store.storeId,
        subject_id: store.subjectId,
        dataset_type: datasetType,
        source_period: sourcePeriod,
        collected_at: new Date(Date.parse(collectedAt)).toISOString(),
        idempotency_key: `r297:${sourcePeriod}:${datasetType}:${digest}`,
        client_version: CLIENT_VERSION,
        records
      }
    });
  }

  return Object.freeze({
    clientVersion: CLIENT_VERSION,
    cloudOrigin: CLOUD_ORIGIN,
    heartbeat,
    isPaired: () => Boolean(identity),
    listStores,
    pair,
    readIdentity,
    syncDataset
  });
}

module.exports = Object.freeze({
  CLIENT_VERSION,
  CLOUD_ORIGIN,
  HEARTBEAT_URL,
  PAIR_URL,
  SYNC_URL,
  STORES_URL,
  createCloudClient,
  requireProtectedSafeStorage
});
