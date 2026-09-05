const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { chromium } = require('playwright');

const releaseSha = String(process.argv[2] || '').trim().toLowerCase();
const generatorSha = String(process.argv[3] || '').trim().toLowerCase();
const outputDir = process.argv[4];
assert.match(releaseSha, /^[0-9a-f]{40}$/);
assert.match(generatorSha, /^[0-9a-f]{40}$/);
assert.ok(outputDir);

(async () => {
  const operations = [];
  const nativeEvents = [];
  const rawEvents = [];
  let eventsArrived;
  const allEventsArrived = new Promise(resolve => { eventsArrived = resolve; });
  const moduleSource = fs.readFileSync('/workspace/frontend/r297-owner-login.js');
  const fixture = `<!doctype html><main id="ready">ready</main>
<script src="/r297-owner-login.js"></script><script>
window.__tiantongR297AuthenticatedObserver = payload => navigator.sendBeacon('/raw', payload);
const reporter = R297OwnerLogin.createPageCloseReporter({getReleaseSha: () => ${JSON.stringify(releaseSha)}});
window.__syntheticRejected = {
  constructed_event: reporter.report(new PageTransitionEvent('pagehide'), [7]),
  plain_object: reporter.report({type: 'pagehide', isTrusted: true}, [7])
};
addEventListener('pagehide', event => {
  navigator.sendBeacon('/native', JSON.stringify({
    event: event.type,
    observed_at: new Date().toISOString(),
    event_is_trusted: event.isTrusted,
    event_constructor: event.constructor.name
  }));
  reporter.report(event, [7]);
});
</script>`;
  const server = http.createServer((request, response) => {
    response.setHeader('Cache-Control', 'no-store');
    if (request.method === 'POST' && (request.url === '/native' || request.url === '/raw')) {
      const chunks = [];
      request.on('data', chunk => chunks.push(chunk));
      request.on('end', () => {
        const payload = JSON.parse(Buffer.concat(chunks).toString('utf8'));
        (request.url === '/native' ? nativeEvents : rawEvents).push(payload);
        if (nativeEvents.length === 1 && rawEvents.length === 1) eventsArrived();
        response.writeHead(204).end();
      });
      return;
    }
    if (request.url === '/r297-owner-login.js') {
      response.setHeader('Content-Type', 'application/javascript');
      return response.end(moduleSource);
    }
    response.setHeader('Content-Type', 'text/html; charset=utf-8');
    response.end(request.url === '/fixture' ? fixture : '<!doctype html><title>done</title>');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    operations.push({ operation: 'goto', url: '/fixture', observed_at: new Date().toISOString() });
    await page.goto(`${origin}/fixture`);
    await page.waitForSelector('#ready');
    const syntheticRejected = await page.evaluate(() => window.__syntheticRejected);
    assert.deepEqual(syntheticRejected, { constructed_event: false, plain_object: false });

    operations.push({ operation: 'goto', url: '/done', observed_at: new Date().toISOString() });
    await page.goto(`${origin}/done`);
    let timeout;
    await Promise.race([
      allEventsArrived,
      new Promise((_, reject) => { timeout = setTimeout(() => reject(new Error('原生pagehide事件采集超时')), 5000); })
    ]).finally(() => clearTimeout(timeout));

    assert.equal(nativeEvents.length, 1);
    assert.equal(nativeEvents[0].event, 'pagehide');
    assert.equal(nativeEvents[0].event_constructor, 'PageTransitionEvent');
    assert.equal(nativeEvents[0].event_is_trusted, true);
    assert.equal(rawEvents.length, 1);
    assert.deepEqual(Object.keys(rawEvents[0]).sort(), ['event', 'observed_at', 'release_sha', 'store_id']);
    assert.equal(rawEvents[0].event, 'web_page_close');
    assert.equal(rawEvents[0].store_id, 7);
    assert.equal(rawEvents[0].release_sha, releaseSha);
    assert.equal('scheduler_continues' in rawEvents[0], false);

    const evidence = {
      schema_version: '1.0',
      release_sha: releaseSha,
      generator_sha: generatorSha,
      frontend_source_diff: 'EMPTY',
      playwright_operations: operations,
      event_listener: 'window.addEventListener("pagehide", handler)',
      native_events: nativeEvents,
      raw_events: rawEvents,
      synthetic_event_rejected: syntheticRejected
    };
    fs.mkdirSync(outputDir, { recursive: true });
    const evidencePath = path.join(outputDir, 'r297-native-pagehide-evidence.json');
    fs.writeFileSync(evidencePath, `${JSON.stringify(evidence, null, 2)}\n`, { mode: 0o444 });
    const digest = crypto.createHash('sha256').update(fs.readFileSync(evidencePath)).digest('hex');
    fs.writeFileSync(`${evidencePath}.sha256`, `${digest}  ${path.basename(evidencePath)}\n`, { mode: 0o444 });
    console.log(`R297_NATIVE_PAGEHIDE_EVIDENCE_SHA256=${digest}`);
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => {
  console.error(error && error.stack ? error.stack : error);
  process.exit(1);
});
