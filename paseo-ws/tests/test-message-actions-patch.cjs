const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { patchMessageActions } = require('../srcs/patches/service/patch-web-ui.cjs');
const { serverRoot } = require('../srcs/patches/patch-utils.cjs');
const baseline = require('../srcs/patches/service/patch-web-ui.baseline.json');

test('wide touch browsers show message actions and react to input capability changes', t => {
  const installed = fs.existsSync(path.join(serverRoot, 'package.json')) && JSON.parse(fs.readFileSync(path.join(serverRoot, 'package.json'))).version === baseline.version;
  if (process.env.PASEO_RUNTIME_PREFIX) assert.ok(installed);
  if (!installed) return t.skip(`Paseo ${baseline.version} bundle not installed`);
  const source = fs.readFileSync(path.join(serverRoot, 'dist/server/web-ui', baseline.webEntry), 'utf8');
  const patched = patchMessageActions(source);
  assert.equal(patchMessageActions(patched), patched);
  const helpers = patched.match(/const paseoMessageInputQuery=.*?function paseoMessageServerInput\(\)\{return!1\}/)[0];
  const hook = patched.match(/paseoTouchActions=(\(0,z.useSyncExternalStore\)\([^)]*\)),se=([^;]+);/);
  assert.ok(hook, 'input subscription must be called before conditional visibility checks');
  let touch = true, listener, notified = 0;
  const media = {
    get matches() { return touch; },
    addEventListener(type, callback) { assert.equal(type, 'change'); listener = callback; },
    removeEventListener(type, callback) { assert.equal(type, 'change'); assert.equal(callback, listener); listener = null; },
  };
  const context = vm.createContext({ window: { matchMedia(query) {
    assert.equal(query, '(hover: none), (pointer: coarse)'); return media;
  } } });
  vm.runInContext(helpers, context);
  const unsubscribe = vm.runInContext('paseoSubscribeMessageInput', context)(() => notified++);
  context.z = { useSyncExternalStore(subscribe, snapshot, serverSnapshot) {
    assert.equal(serverSnapshot(), false); return snapshot();
  } };
  const visible = (overrides = {}) => {
    Object.assign(context, { N: false, oe: true, X: false, L: { isNative: false }, $: false }, overrides);
    context.paseoTouchActions = vm.runInContext(hook[1], context);
    return vm.runInContext(hook[2], context);
  };
  assert.equal(visible(), true, 'wide iPad without hover shows the row');
  assert.equal(visible({ N: true }), false, 'pending messages keep actions disabled');
  assert.equal(visible({ oe: false }), false, 'attachment-only messages keep actions hidden');
  touch = false; listener();
  assert.equal(notified, 1);
  assert.equal(visible(), false, 'desktop mouse still requires hover');
  assert.equal(visible({ $: true }), true);
  assert.equal(visible({ X: true }), true, 'compact layout still shows actions');
  assert.equal(visible({ L: { isNative: true } }), true, 'native platforms still show actions');
  unsubscribe(); assert.equal(listener, null);
  // Older iPad Safari exposes only the legacy MediaQueryList listener API.
  delete media.addEventListener;
  delete media.removeEventListener;
  media.addListener = callback => { listener = callback; };
  media.removeListener = callback => { assert.equal(callback, listener); listener = null; };
  const unsubscribeLegacy = vm.runInContext('paseoSubscribeMessageInput', context)(() => notified++);
  touch = true; listener();
  assert.equal(notified, 2);
  assert.equal(visible(), true);
  unsubscribeLegacy(); assert.equal(listener, null);
  vm.runInContext('delete window.matchMedia', context);
  assert.equal(visible(), false, 'missing browser API safely preserves desktop behavior');
  assert.doesNotThrow(() => vm.runInContext('paseoSubscribeMessageInput(()=>{})()', context));
  vm.runInContext('delete globalThis.window', context);
  assert.equal(vm.runInContext('paseoTouchMessageInput()', context), false);
  assert.throws(() => patchMessageActions(source.replace('se=!N&&oe&&(X||L.isNative||$)', 'se=changed')), /structure changed/);
  assert.throws(() => patchMessageActions(source + source), /structure changed/);
});
