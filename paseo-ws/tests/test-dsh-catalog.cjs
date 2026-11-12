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

test('installed paseo-dsh 0.2.17 assets and bridge are canonical, idempotent and reject drift (read only)', t => {
  const fs = require('node:fs'), path = require('node:path');
  const plugins = path.resolve(__dirname, '../data/.paseo/plugins/dsh-paseo');
  if (!fs.existsSync(plugins)) return t.skip('paseo-dsh plugin not installed');
  const roots = fs.readdirSync(plugins).map(version => path.join(plugins, version, 'node_modules/paseo-dsh'))
    .filter(root => fs.existsSync(path.join(root, 'package.json')));
  if (!roots.length) return t.skip('paseo-dsh package not installed');
  const before = "if (method === 'initialize') await ctx.get('loader')?.await();";
  const after = "if (method === 'initialize' || method === 'paseo/catalog') await ctx.get('loader')?.await();";
  const home = process.env.DSH_HOME ?? path.resolve(__dirname, '../../ds-harness/data/.dsh');
  for (const root of roots) {
    assert.equal(JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8')).version, '0.2.17');
    const assets = fs.readFileSync(path.join(root, 'server/bridge-assets.ts'), 'utf8');
    const entry = fs.readFileSync(path.join(root, 'index.server.ts'), 'utf8');
    const embedded = [...assets.matchAll(/("lib\/index\.js":\s*")([A-Za-z0-9+/=]+)(")/g)];
    assert.equal(embedded.length, 1);
    const bridge = Buffer.from(embedded[0][2], 'base64').toString('utf8');
    const upstream = bridge.replace(after, before);
    assert.ok(upstream.includes(before));
    const canonical = patchSource(upstream);
    assert.equal(patchSource(canonical), canonical);
    assert.equal(canonical, upstream.replace(before, after));
    const canonicalAssets = patchAssets(assets);
    assert.equal(patchAssets(canonicalAssets), canonicalAssets);
    assert.equal(Buffer.from(canonicalAssets.match(/"lib\/index\.js":\s*"([A-Za-z0-9+/=]+)"/)[1], 'base64').toString(), canonical);
    assert.throws(() => patchSource(upstream.replace(before, "if (method === 'initialize') await unknown();")), /Unsupported/);
    assert.throws(() => patchAssets(assets.replace(embedded[0][2], Buffer.from('unknown bridge').toString('base64'))), /Unsupported/);
    assert.throws(() => patchAssets(assets + embedded[0][0]), /exactly one/);
    assert.equal(patchHome(patchHome(entry, home), home), patchHome(entry, home));
    assert.throws(() => patchHome(entry.replace('export default function contribute', 'export default function unknown'), home), /Unsupported/);
    const file = path.join(home, 'profiles', process.env.DSH_PASEO_PROFILE ?? 'paseo', 'node_modules/dsh-paseo-bridge/lib/index.js');
    if (fs.existsSync(file)) {
      const actual = fs.readFileSync(file, 'utf8');
      assert.equal(patchSource(actual), canonical, 'provisioned bridge matches embedded bridge');
    }
  }
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
