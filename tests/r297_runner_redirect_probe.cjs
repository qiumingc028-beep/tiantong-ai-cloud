// Controlled boundary regression only; this is not real JD/formal evidence.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const vm = require('node:vm');
const {chromium} = require('playwright');

const source = fs.readFileSync(path.join(__dirname, 'r297_live_frontend_acceptance.cjs'), 'utf8');
const guard = vm.runInNewContext(`(${source.slice(source.indexOf('async function enforceApprovedOrigin('), source.indexOf('\nfunction approvedWebSocket('))})`, {URL});
const listen = server => new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const close = server => new Promise(resolve => server.close(resolve));

(async () => {
  let outsideRequests = 0, redirects = 0;
  const outside = http.createServer((_request, response) => { outsideRequests++; response.end('must not arrive'); });
  await listen(outside);
  const server = http.createServer((request, response) => {
    if (request.url === '/redirect') {
      redirects++;
      response.writeHead(307, {Location: `http://127.0.0.1:${outside.address().port}/capture`}).end();
    } else response.end('<!doctype html><title>controlled</title>');
  });
  await listen(server);
  const origin = `http://127.0.0.1:${server.address().port}`;
  let browser;
  try {
    browser = await chromium.launch({headless: true});
    const context = await browser.newContext({serviceWorkers: 'block'});
    await context.route('**/*', route => guard(route, origin));
    const page = await context.newPage();
    await page.goto(origin);
    assert.equal(await page.title(), 'controlled');
    assert.equal(await page.evaluate(async () => {
      try { await fetch('/redirect', {method: 'POST', body: 'public-test-sentinel'}); return 'unexpected'; }
      catch { return 'blocked'; }
    }), 'blocked');
    await assert.rejects(page.goto(`${origin}/redirect`));
    assert.equal(redirects, 2);
    assert.equal(outsideRequests, 0);
    console.log('R297_RUNNER_REDIRECT_NETWORK_TEST=PASS cases=3 outside_requests=0');
    // Exercise the PRODUCT adapter without the Runner route guard masking it.
    const product = await browser.newContext({serviceWorkers: 'block'});
    const productPage = await product.newPage();
    await productPage.goto(origin);
    await productPage.addScriptTag({content: fs.readFileSync(path.join(__dirname, '../frontend/r297-owner-login.js'), 'utf8')});
    const productResult = await productPage.evaluate(async outsidePort => {
      const request = R297OwnerLogin.createSameOriginRequest(fetch, location);
      const result = [];
      for (const url of ['/redirect', `${location.origin}//127.0.0.1:${outsidePort}/capture`]) {
        try { await request(url, {method: 'POST', body: 'public-test-body'}); result.push('unexpected'); }
        catch { result.push('blocked'); }
      }
      result.push((await request('/')).status);
      return result;
    }, outside.address().port);
    assert.deepEqual(productResult, ['blocked', 'blocked', 200]);
    assert.equal(outsideRequests, 0);
    console.log('R297_PRODUCT_REDIRECT_NETWORK_TEST=PASS cases=3 outside_requests=0');
  } finally {
    if (browser) await browser.close();
    await Promise.all([close(server), close(outside)]);
  }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
