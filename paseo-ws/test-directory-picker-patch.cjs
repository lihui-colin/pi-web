const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const baseline = require('./patch-web-ui.baseline.json');
test('installed upstream bundle accepts the directory picker patch idempotently', t => {
  const relativeServer = 'runtime/lib/node_modules/@getpaseo/cli/node_modules/@getpaseo/server';
  const installedWeb = path.join(__dirname, relativeServer, 'dist/server/web-ui');
  const sourceName = 'index-1ac09e1966ac6dd37f983e4daa1beff5.js';
  const source = path.join(installedWeb, '_expo/static/js/web', sourceName);
  if (!fs.existsSync(source)) { t.skip('Original Paseo 0.14.0 bundle not installed'); return; }
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'paseo-picker-patch-'));
  t.after(() => {
    assert.ok(path.resolve(root).startsWith(path.join(os.tmpdir(), 'paseo-picker-patch-')));
    fs.rmSync(root, { recursive: true, force: true });
  });
  for (const file of ['patch-web-ui.cjs', 'patch-web-ui.baseline.json', 'server-directory-picker.js']) {
    fs.copyFileSync(path.join(__dirname, file), path.join(root, file));
  }
  const server = path.join(root, relativeServer), web = path.join(server, 'dist/server/web-ui');
  fs.mkdirSync(path.join(web, '_expo/static/js/web'), { recursive: true });
  fs.writeFileSync(path.join(server, 'package.json'), JSON.stringify({ version: baseline.version, gitHead: baseline.commit }));
  fs.copyFileSync(source, path.join(web, '_expo/static/js/web', sourceName));
  const originalHtml = '<head></head><script src="/_expo/static/js/web/' + sourceName + '"></script>';
  fs.writeFileSync(path.join(web, 'index.html'), originalHtml);
  const run = () => spawnSync(process.execPath, [path.join(root, 'patch-web-ui.cjs')], { encoding: 'utf8' });
  const first = run(); assert.equal(first.status, 0, first.stderr);
  const html = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
  assert.notEqual(html, originalHtml);
  const outputPath = path.join(web, html.match(/src="([^"]+)"/)[1]);
  const bundle = fs.readFileSync(outputPath, 'utf8');
  assert.ok(bundle.includes('globalThis.__paseoPickServerDirectory(je,'));
  assert.ok(bundle.includes('client.listDirectory(path,'));
  assert.ok(bundle.includes('timeoutMs:20000'));
  assert.equal(bundle.includes('__paseoMountTerminalClipboard'), false);
  const handler = bundle.match(/oe=\(0,n\.useCallback\)\((n=>\{typeof window\.paseoDesktop\?\.menu\?\.showContextMenu==="function"&&\(n\.preventDefault\(\),te\(\)\)\}),\[te\]\)/)?.[1];
  assert.ok(handler, 'browser context menu handler is present');
  const vm = require('node:vm');
  let prevented = 0, desktopMenus = 0;
  const event = { preventDefault() { prevented++; } };
  vm.runInNewContext('(' + handler + ')(event)', { window: {}, event, te() { desktopMenus++; } });
  assert.equal(prevented, 0, 'Web leaves the native browser menu enabled');
  vm.runInNewContext('(' + handler + ')(event)', { window: { paseoDesktop: { menu: { showContextMenu() {} } } }, event, te() { desktopMenus++; } });
  assert.equal(prevented, 1);
  assert.equal(desktopMenus, 1);
  const second = run(); assert.equal(second.status, 0, second.stderr);
  assert.equal(fs.readFileSync(path.join(web, 'index.html'), 'utf8'), html);
  assert.equal(fs.readFileSync(outputPath, 'utf8'), bundle);
});
