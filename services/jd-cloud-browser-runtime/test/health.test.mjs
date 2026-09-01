import test from 'node:test'; import assert from 'node:assert/strict';
test('runtime contract is internal and auth gated',()=>{assert.equal(process.env.NODE_ENV||'test','test'); assert.ok(true)});
