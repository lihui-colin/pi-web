const { test } = require('node:test');
const assert = require('node:assert/strict');
const { patchSource, patchAssets } = require('./patch-dsh-catalog.cjs');
const original = "if (method === 'initialize') await ctx.get('loader')?.await();\nreturn server.handleRequest(method, params);";
test('catalog waits for loader readiness before querying stored credentials', async () => {
  const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
  const handler = new AsyncFunction('method', 'params', 'ctx', 'server', patchSource(original));
  let release, calls = 0;
  const ready = new Promise(resolve => { release = resolve; });
  const pending = handler('paseo/catalog', {}, { get: () => ({ await: () => ready }) }, { handleRequest: () => { calls++; return ['xinmian/grok-4.7']; } });
  await new Promise(setImmediate);
  assert.equal(calls, 0);
  release();
  assert.deepEqual(await pending, ['xinmian/grok-4.7']);
  assert.equal(calls, 1);
});
test('readiness patch is idempotent and rejects unknown source structures', () => {
  assert.equal(patchSource(patchSource(original)), patchSource(original));
  assert.throws(() => patchSource('unsupported'), /Unsupported/);
  const source = '"lib/index.js": "' + Buffer.from(original).toString('base64') + '"';
  const patched = patchAssets(source);
  assert.equal(patchAssets(patched), patched);
  assert.equal(Buffer.from(patched.match(/: "([^"]+)"/)[1], 'base64').toString(), patchSource(original));
});
