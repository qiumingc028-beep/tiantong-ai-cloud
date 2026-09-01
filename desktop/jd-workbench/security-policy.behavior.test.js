'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {
  classifyRequest,
  detectHumanActionFromUrl,
  isAuditedMainFrameRoute,
  isAuthenticationPage,
  parseAllowedHttpsUrl
} = require('./security-policy');

const allowedMainFrames = [
  'https://shop.jd.com/',
  'https://shop.jd.com/jdm/home/',
  'https://shop.jd.com/jdm/home/unknown-future-route?source=login',
  'https://passport.shop.jd.com/login/index.action/jdm',
  'https://passport.shop.jd.com/a/future/login/route',
  'https://passport.jd.com/new/login.aspx',
  'https://jshopx.jd.com/',
  'https://jm.jd.com/',
  'https://sz.jd.com/home',
  'https://jzt.jd.com/'
];

for (const url of allowedMainFrames) {
  assert.equal(
    isAuditedMainFrameRoute(url),
    true,
    `official top-level JD navigation must remain compatible: ${url}`
  );
}

const rejectedMainFrames = [
  'http://shop.jd.com/',
  'https://shop.jd.com.attacker.example/',
  'https://attacker.example/?next=https://shop.jd.com/',
  'https://user:password@shop.jd.com/',
  'https://shop.jd.com:444/',
  'javascript:alert(1)',
  'file:///C:/Windows/System32/calc.exe',
  'https://static.360buyimg.com/'
];

for (const url of rejectedMainFrames) {
  assert.equal(
    isAuditedMainFrameRoute(url),
    false,
    `non-document or untrusted navigation must be blocked: ${url}`
  );
}

assert.equal(isAuthenticationPage('https://passport.jd.com/any/new/path'), true);
assert.equal(isAuthenticationPage('https://passport.shop.jd.com/any/new/path'), true);
assert.equal(isAuthenticationPage('https://jshopx.jd.com/any/new/path'), true);
assert.equal(isAuthenticationPage('https://shop.jd.com/jdm/home/'), false);

assert.equal(
  parseAllowedHttpsUrl('https://sff.jd.com/api?api=dsm.shop.home.comm.grayFacade.isGray').hostname,
  'sff.jd.com',
  'known JD subresource hosts remain available to the standard browser network stack'
);
assert.equal(parseAllowedHttpsUrl('https://sff.jd.com.attacker.example/api'), null);
assert.equal(parseAllowedHttpsUrl('http://sff.jd.com/api'), null);

assert.equal(
  detectHumanActionFromUrl('https://passport.jd.com/safe-verify/index'),
  'RISK_OR_CAPTCHA',
  'human checks must be surfaced to the operator without closing the page'
);
assert.equal(detectHumanActionFromUrl('https://shop.jd.com/jdm/home/'), null);

const request = (overrides = {}) => classifyRequest({
  url: 'https://shop.jd.com/jdm/home/', method: 'GET', resourceType: 'mainFrame',
  currentMainFrameUrl: 'https://shop.jd.com/jdm/home/', isActive: true,
  isMainFrameSource: true, initiator: 'https://shop.jd.com', ...overrides
});
assert.equal(request().allow, true);
assert.equal(request({ isActive: false }).code, 'INACTIVE_PARTITION');
assert.equal(request({ url: 'https://shop.jd.com.attacker.example/' }).allow, false);
assert.equal(request({
  url: 'https://sff.jd.com/api?api=dsm.order.updateOrder', method: 'POST', resourceType: 'xhr'
}).code, 'READ_ONLY_WRITE_BLOCKED');
assert.equal(request({
  url: 'https://sff.jd.com/api?api=dsm.order.queryOrderList', method: 'POST', resourceType: 'xhr'
}).allow, true);

const mainSource = fs.readFileSync(path.join(__dirname, 'main.js'), 'utf8');
const preloadSource = fs.readFileSync(path.join(__dirname, 'preload.js'), 'utf8');
const rendererSource = fs.readFileSync(path.join(__dirname, 'renderer', 'app.js'), 'utf8');
const rendererHtml = fs.readFileSync(path.join(__dirname, 'renderer', 'index.html'), 'utf8');
assert.equal(
  mainSource.includes('webRequest.onBeforeRequest'),
  true,
  'R297 must keep the centralized read-only request firewall'
);
for (const requiredPreference of [
  'nodeIntegration: false',
  'contextIsolation: true',
  'sandbox: true',
  'webSecurity: true',
  'allowRunningInsecureContent: false',
  'webviewTag: false'
]) {
  assert.equal(
    mainSource.includes(requiredPreference),
    true,
    `R294 must preserve the Electron browser isolation preference: ${requiredPreference}`
  );
}

for (const section of ['business', 'stores', 'sync', 'alerts']) {
  assert.equal(
    rendererHtml.includes(`data-section="${section}"`),
    true,
    `R293 navigation must expose an operable ${section} button`
  );
}
assert.equal(rendererHtml.includes('id="syncNow" class="primary" disabled'), false);
assert.equal(preloadSource.includes('setSection:'), true);
assert.equal(rendererSource.includes("elements.topnav.addEventListener('click'"), true);
assert.equal(rendererSource.includes("elements.syncNow.addEventListener('click'"), true);
assert.equal(rendererSource.includes("elements.browseMode.addEventListener('click'"), true);
assert.equal(rendererSource.includes("elements.refreshStores.addEventListener('click'"), true);

assert.equal(mainSource.includes('executeJavaScript(buildRecognizerScript())'), true);
assert.equal(preloadSource.includes('recognizePage:'), true);

console.log('R297_SECURITY_POLICY_AND_RECOGNITION=PASS');
