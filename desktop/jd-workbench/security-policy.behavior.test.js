'use strict';

const assert = require('node:assert/strict');
const { classifyRequest } = require('./security-policy');

function decide(overrides = {}) {
  return classifyRequest({
    url: 'https://shop.jd.com/',
    method: 'GET',
    resourceType: 'mainFrame',
    currentMainFrameUrl: 'https://shop.jd.com/',
    isActive: true,
    isMainFrameSource: true,
    ...overrides
  });
}

assert.deepEqual(
  decide({ isActive: false }),
  { allow: false, code: 'INACTIVE_PARTITION' },
  'inactive partitions must fail closed before all other classification'
);
assert.deepEqual(
  decide({ url: 'https://shop.jd.com.attacker.example/' }),
  { allow: false, code: 'UNKNOWN_DOMAIN' },
  'suffix spoofing must not pass the exact host allowlist'
);
assert.deepEqual(
  decide({ url: 'http://shop.jd.com/' }),
  { allow: false, code: 'UNKNOWN_DOMAIN' },
  'plaintext HTTP must never pass'
);
assert.deepEqual(
  decide({ url: 'https://shop.jd.com/api/save', method: 'POST', resourceType: 'xhr' }),
  { allow: false, code: 'READ_ONLY_WRITE_BLOCKED' },
  'business POSTs must fail closed'
);
assert.deepEqual(
  decide({
    url: 'https://passport.jd.com/new/login.aspx',
    method: 'POST',
    resourceType: 'xhr',
    currentMainFrameUrl: 'https://shop.jd.com/'
  }),
  { allow: false, code: 'READ_ONLY_WRITE_BLOCKED' },
  'an auth target is insufficient when the visible page is not an audited auth route'
);
assert.deepEqual(
  decide({
    url: 'https://passport.jd.com/uc/loginService',
    method: 'POST',
    resourceType: 'xhr',
    currentMainFrameUrl: 'https://passport.jd.com/new/login.aspx'
  }),
  { allow: false, code: 'READ_ONLY_WRITE_BLOCKED' },
  'host-level auth POST permission must not exist'
);
assert.deepEqual(
  decide({
    url: 'https://jshopx.jd.com/',
    method: 'POST',
    resourceType: 'mainFrame',
    currentMainFrameUrl: 'https://jshopx.jd.com/'
  }),
  { allow: false, code: 'READ_ONLY_WRITE_BLOCKED' },
  'legacy jshopx must not be an authentication exception'
);
assert.deepEqual(
  decide({
    url: 'https://passport.jd.com/new/login.aspx',
    method: 'POST',
    resourceType: 'xhr',
    currentMainFrameUrl: 'https://passport.jd.com/new/login.aspx',
    isMainFrameSource: false
  }),
  { allow: false, code: 'READ_ONLY_WRITE_BLOCKED' },
  'subframes and service workers must not use the authentication exception'
);
assert.deepEqual(
  decide({ resourceType: 'webSocket' }),
  { allow: false, code: 'BACKGROUND_CHANNEL_BLOCKED' },
  'background duplex channels must be blocked'
);
assert.deepEqual(
  decide({ url: 'https://shop.jd.com/api/query', method: 'GET', resourceType: 'xhr' }),
  { allow: false, code: 'ENDPOINT_NOT_AUDITED' },
  'GET must not be treated as read-only without endpoint semantics'
);
assert.deepEqual(
  decide({ url: 'https://shop.jd.com/api/delete', method: 'GET', resourceType: 'mainFrame' }),
  { allow: false, code: 'ENDPOINT_NOT_AUDITED' },
  'main-frame paths outside the audited route set must fail closed'
);
assert.deepEqual(
  decide({ url: 'https://img10.360buyimg.com/example.png', method: 'GET', resourceType: 'image' }),
  { allow: true, code: 'STATIC_RESOURCE' },
  'exact static hosts remain available only for static resource types'
);
assert.deepEqual(
  decide({
    url: 'https://passport.jd.com/new/login.aspx?ReturnUrl=https%3A%2F%2Fshop.jd.com%2F',
    method: 'POST',
    resourceType: 'mainFrame',
    currentMainFrameUrl: 'https://passport.jd.com/new/login.aspx?ReturnUrl=https%3A%2F%2Fshop.jd.com%2F'
  }),
  { allow: true, code: 'HUMAN_AUTHENTICATION' },
  'the exact audited login route remains usable by the active main frame'
);

console.log('R291_SECURITY_POLICY_BEHAVIOR=13_PASS');
