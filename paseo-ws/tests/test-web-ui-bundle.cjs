const { sourceFile, fixtureFile } = require('./support.cjs');
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const crypto = require('node:crypto');
const zlib = require('node:zlib');
const baseline = require('../srcs/patches/service/patch-web-ui.baseline.json');
const { serverRoot } = require('../srcs/patches/patch-utils.cjs');
const { patchMarkdownMath, patchMessageActions, patchProjectWorkspaceMenu, patchTerminalTouchKeys, patchExplorerSidebarMaximize } = require('../srcs/patches/service/patch-web-ui.cjs');

test('Web patch rebuilds from upstream, removes retired features and stays idempotent', t => {
  const installed = fs.existsSync(path.join(serverRoot, 'package.json')) && JSON.parse(fs.readFileSync(path.join(serverRoot, 'package.json'))).version === baseline.version;
  if (process.env.PASEO_RUNTIME_PREFIX) assert.ok(installed, `Explicit PASEO_RUNTIME_PREFIX must contain Paseo ${baseline.version}: ${serverRoot}`);
  if (!installed) return t.skip(`Paseo ${baseline.version} bundle not installed`);
  const source = fs.readFileSync(path.join(serverRoot, 'dist/server/web-ui', baseline.webEntry), 'utf8');
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'paseo-web-patch-'));
  t.after(() => {
    assert.ok(path.resolve(root).startsWith(path.join(os.tmpdir(), 'paseo-web-patch-')));
    fs.rmSync(root, { recursive: true, force: true });
  });
  for (const file of ['patch-web-ui.cjs', 'patch-web-ui.baseline.json', 'patch-utils.cjs', 'mobile-sidebar-swipe.js', 'server-directory-picker.js', 'explorer-sidebar-maximize.js']) fs.copyFileSync(sourceFile(file), fixtureFile(root, file));
  const server = path.join(root, 'runtime/lib/node_modules/@getpaseo/cli/node_modules/@getpaseo/server');
  const web = path.join(server, 'dist/server/web-ui');
  fs.mkdirSync(path.dirname(path.join(web, baseline.webEntry)), { recursive: true });
  fs.writeFileSync(path.join(server, 'package.json'), JSON.stringify({ version: baseline.version, gitHead: baseline.commit }));
  fs.writeFileSync(path.join(web, baseline.webEntry), source);
  const oldEntry = '/_expo/static/js/web/index-deadbeef.js';
  fs.writeFileSync(path.join(web, oldEntry), 'globalThis.__paseoPickServerDirectory = () => {};');
  const originalHtml = `<head></head><script src="${oldEntry}"></script>`;
  fs.writeFileSync(path.join(web, 'index.html'), originalHtml);
  const run = () => spawnSync(process.execPath, [fixtureFile(root, 'patch-web-ui.cjs')], { encoding: 'utf8', env: { ...process.env, PASEO_RUNTIME_PREFIX: path.join(root, 'runtime') } });
  const first = run(); assert.equal(first.status, 0, first.stderr);
  const html = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
  assert.notEqual(html, originalHtml);
  const output = path.join(web, html.match(/src="([^"]+)"/)[1]);
  const bundle = fs.readFileSync(output, 'utf8');
  assert.equal(path.basename(output), `index-${crypto.createHash('sha256').update(bundle).digest('hex').slice(0, 32)}.js`);
  assert.equal(zlib.brotliDecompressSync(fs.readFileSync(output + '.br')).toString(), bundle);
  assert.equal(zlib.gunzipSync(fs.readFileSync(output + '.gz')).toString(), bundle);
  for (const retired of ['__paseoMountTerminalClipboard', '__paseoGetBulkDiffTransport']) assert.equal(bundle.includes(retired), false);
  assert.ok(bundle.includes('globalThis.__paseoPickServerDirectory(Se,{initialPath:Pe[0],hostLabel:ke?.label})'));
  assert.ok(bundle.includes('canBrowse:o&&(!(0,C.getIsElectronRuntime)()'));
  assert.ok(bundle.includes('timeoutMs:20000'));
  assert.ok(bundle.includes('connectTimeoutMs:s.timeoutMs??20000'));
  assert.ok(bundle.includes('__paseoMobileSidebarSwipeCleanup'));
  const moduleContaining = (text, marker) => {
    const at = text.indexOf(marker);
    assert.ok(at > 0, `Missing upstream module marker: ${marker}`);
    assert.equal(at, text.lastIndexOf(marker), `Ambiguous upstream module marker: ${marker}`);
    return text.slice(text.lastIndexOf('\n__d(', at), text.indexOf('\n__d(', at));
  };
  for (const marker of ['e.useOpenAgentListGesture=function', '_e.MobilePanelOverlay=function', 'observeDiff(e){return this.diffStreams.observe(e)}', '"Duplicate diff entry"']) {
    assert.equal(moduleContaining(bundle, marker), moduleContaining(source, marker), 'upstream gestures and diff remain unchanged');
  }
  assert.equal(bundle.includes('latexMath:!1'), false);
  assert.equal((bundle.match(/y=\{latexMath:!0,hardSoftBreaks:!0,admonitions:!0\}/g) || []).length, 1);
  assert.ok(bundle.includes('math:{color:t.colors.foreground,backgroundColor:"transparent"},inlineMath:{color:t.colors.foreground}'));
  const mathMarker = 'e.Markdown=function';
  assert.equal(moduleContaining(bundle, mathMarker), moduleContaining(patchMarkdownMath(source), mathMarker));
  const messageMarker = 'Object.defineProperty(_e,"UserMessage",';
  assert.equal(moduleContaining(bundle, messageMarker), moduleContaining(patchMessageActions(source), messageMarker));
  const projectMarker = 'function rr({project:o,displayName:t';
  assert.equal(moduleContaining(bundle, projectMarker), moduleContaining(patchProjectWorkspaceMenu(source), projectMarker));
  for (const marker of ['_e.TerminalPane=function', 'e.shouldShowTerminalVirtualKeyBar=function']) {
    assert.equal(moduleContaining(bundle, marker), moduleContaining(patchTerminalTouchKeys(source), marker));
  }
  const splitMarker = '_e.SplitContainer=function';
  assert.equal(moduleContaining(bundle, splitMarker), moduleContaining(patchExplorerSidebarMaximize(source), splitMarker));
  for (const marker of ['_e.WorkspaceTabMeasurementScope=function', 'e.ExplorerSidebarDock=function', 'Object.defineProperty(e,"ExplorerFrame",']) {
    assert.equal(moduleContaining(bundle, marker), moduleContaining(patchExplorerSidebarMaximize(source), marker));
  }
  assert.equal(bundle.includes('createPaseoTerminalFullscreen'), false);
  const handler = bundle.match(/oe=\(0,n\.useCallback\)\((n=>\{typeof window\.paseoDesktop\?\.menu\?\.showContextMenu==="function"&&\(n\.preventDefault\(\),te\(\)\)\}),\[te\]\)/)?.[1];
  assert.ok(handler);
  let prevented = 0, desktopMenus = 0;
  const event = { preventDefault() { prevented++; } }, te = () => { desktopMenus++; };
  const vm = require('node:vm');
  vm.runInNewContext('(' + handler + ')(event)', { window: {}, event, te });
  assert.equal(prevented, 0);
  vm.runInNewContext('(' + handler + ')(event)', { window: { paseoDesktop: { menu: { showContextMenu() {} } } }, event, te });
  assert.equal(prevented, 1); assert.equal(desktopMenus, 1);
  const second = run(); assert.equal(second.status, 0, second.stderr);
  assert.equal(fs.readFileSync(path.join(web, 'index.html'), 'utf8'), html);
  assert.equal(fs.readFileSync(output, 'utf8'), bundle);
  assert.equal(fs.readFileSync(path.join(web, baseline.webEntry), 'utf8'), source);
  const published = fs.readdirSync(path.dirname(output)).sort();
  for (const changed of [source + '\nasync bootstrapInitialConnectionHint(', source.replace('connection:n,timeoutMs:fe', 'connection:n,timeoutMs:unknown')]) {
    fs.writeFileSync(path.join(web, baseline.webEntry), changed);
    const rejected = run();
    assert.notEqual(rejected.status, 0, 'unknown or duplicate bootstrap must fail closed');
    assert.match(rejected.stderr, /structure changed/);
    assert.equal(fs.readFileSync(path.join(web, 'index.html'), 'utf8'), html);
    assert.deepEqual(fs.readdirSync(path.dirname(output)).sort(), published);
  }
  fs.writeFileSync(path.join(web, baseline.webEntry), source);
  fs.writeFileSync(path.join(web, 'index.html'), html + html);
  const duplicateEntry = run();
  assert.notEqual(duplicateEntry.status, 0);
  assert.match(duplicateEntry.stderr, /unique Paseo entry asset/);
  assert.equal(fs.readFileSync(path.join(web, 'index.html'), 'utf8'), html + html);
  assert.deepEqual(fs.readdirSync(path.dirname(output)).sort(), published);
});
