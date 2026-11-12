const {sourceFile, fixtureFile} = require('./support.cjs');
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { patchSource, patchAssets, patchHome } = require('../srcs/patches/plugins/dsh/patch-dsh-catalog.cjs');
test('plugin keeps its configured home after a restart without inherited environment', () => {
  const vm = require('node:vm');
  const source = 'export default function contribute(server: PluginServerContext) {\n  server.home = process.env.DSH_HOME;\n}\n';
  const patched = patchHome(source, '/configured/dsh');
  assert.equal(patchHome(patched, '/configured/dsh'), patched);
  assert.ok(!patchHome(patched, '/new/dsh').includes('/configured/dsh'));
  for (const inherited of [undefined, '/explicit/dsh']) {
    const context = { process: { env: inherited ? { DSH_HOME: inherited } : {} }, server: {} };
    vm.runInNewContext(patched.replace('export default ', '').replace(': PluginServerContext', '') + '\ncontribute(server);', context);
    assert.equal(context.server.home, inherited ?? '/configured/dsh');
  }
});
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
  for (const source of [original + original, patchSource(original) + original, patchSource(original).repeat(2)]) {
    assert.throws(() => patchSource(source), /Unsupported/);
    const embedded = '"lib/index.js": "' + Buffer.from(source).toString('base64') + '"';
    assert.throws(() => patchAssets(embedded), /Unsupported/);
  }
  const source = '"lib/index.js": "' + Buffer.from(original).toString('base64') + '"';
  const patched = patchAssets(source);
  assert.equal(patchAssets(patched), patched);
  assert.equal(Buffer.from(patched.match(/: "([^"]+)"/)[1], 'base64').toString(), patchSource(original));
});

test('CLI defaults to repository DSH home regardless of cwd and honors explicit override', t => {
  const fs = require('node:fs'), os = require('node:os'), path = require('node:path');
  const { spawnSync } = require('node:child_process');
  for (const explicit of [false, true]) {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'paseo-catalog-home-'));
    t.after(() => fs.rmSync(root, { recursive: true, force: true }));
    const service = path.join(root, 'paseo-ws'), home = path.join(root, 'home');
    const dshHome = explicit ? path.join(service, 'data/dsh') : path.join(root, 'ds-harness/data/.dsh');
    const profile = explicit ? 'custom-paseo' : 'paseo';
    const bridgePath = (base, name = profile) => path.join(base, 'profiles', name, 'node_modules/dsh-paseo-bridge/lib/index.js');
    const actual = bridgePath(dshHome);
    const sibling = bridgePath(path.join(home, '.dsh'), 'paseo');
    const asset = path.join(service, 'data/.paseo/plugins/dsh-paseo/version/node_modules/paseo-dsh/server/bridge-assets.ts');
    for (const file of [actual, sibling, asset]) fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(actual, original); fs.writeFileSync(sibling, original);
    fs.writeFileSync(asset, '"lib/index.js": "' + Buffer.from(original).toString('base64') + '"');
    const entry = path.join(path.dirname(path.dirname(asset)), 'index.server.ts');
    const entrySource = 'export default function contribute(server: PluginServerContext) {\n}\n';
    fs.writeFileSync(entry, entrySource);
    const script = path.join(service, 'srcs/patches/plugins/dsh/patch-dsh-catalog.cjs');
    fs.mkdirSync(path.dirname(script), { recursive: true });
    fs.copyFileSync(sourceFile('patch-dsh-catalog.cjs'), script);
    const env = { ...process.env, HOME: home };
    delete env.DSH_HOME; delete env.DSH_PASEO_PROFILE;
    if (explicit) { env.DSH_HOME = dshHome; env.DSH_PASEO_PROFILE = profile; }
    const result = spawnSync(process.execPath, [script], { env, cwd: home, encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr);
    assert.equal(fs.readFileSync(entry, 'utf8'), patchHome(entrySource, dshHome));
    assert.equal(fs.readFileSync(actual, 'utf8'), patchSource(original));
    assert.equal(fs.readFileSync(sibling, 'utf8'), original);
    const embedded = fs.readFileSync(asset, 'utf8').match(/: "([^"]+)"/)[1];
    assert.equal(Buffer.from(embedded, 'base64').toString(), patchSource(original));
  }
});
