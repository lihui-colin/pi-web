const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { patchTerminalTouchKeys } = require('../srcs/patches/service/patch-web-ui.cjs');
const { serverRoot } = require('../srcs/patches/patch-utils.cjs');
const baseline = require('../srcs/patches/service/patch-web-ui.baseline.json');

function moduleAt(text, marker) {
  const at = text.indexOf(marker);
  assert.ok(at >= 0, marker);
  return text.slice(text.lastIndexOf('\n__d(', at), text.indexOf('\n__d(', at));
}
function loadModule(source, imports, globals = {}) {
  const exports = {};
  vm.runInNewContext(source, { ...globals, __d(factory, id, deps) {
    factory({}, imports, undefined, undefined, { exports }, exports, deps);
  } });
  return exports;
}

test('all touch terminals show upstream virtual keys, including wide and hybrid devices', t => {
  const installed = fs.existsSync(path.join(serverRoot, 'package.json')) && JSON.parse(fs.readFileSync(path.join(serverRoot, 'package.json'))).version === baseline.version;
  if (process.env.PASEO_RUNTIME_PREFIX) assert.ok(installed);
  if (!installed) return t.skip(`Paseo ${baseline.version} bundle not installed`);
  const source = fs.readFileSync(path.join(serverRoot, 'dist/server/web-ui', baseline.webEntry), 'utf8');
  const patched = patchTerminalTouchKeys(source);
  assert.equal(patchTerminalTouchKeys(patched), patched);
  const pointerModule = moduleAt(source, 'e.usePointerCapabilities=function');
  assert.equal(moduleAt(patched, 'e.usePointerCapabilities=function'), pointerModule);
  const runtimeMarker = 'e.shouldShowTerminalVirtualKeyBar=function';
  const runtime = moduleAt(patched, runtimeMarker);
  const visibilityBefore = 'e.shouldShowTerminalVirtualKeyBar=function(t){return t.isNative||t.isCompact}';
  const visibilityAfter = 'e.shouldShowTerminalVirtualKeyBar=function(t){return t.isNative||t.isCompact||!!t.isTouchScreen}';
  assert.equal(runtime.replace(visibilityAfter, visibilityBefore), moduleAt(source, runtimeMarker), 'key definitions, adaptive rows and clipboard policy remain upstream');
  const keys = loadModule(runtime, () => ({ TERMINAL_VIRTUAL_KEY_BUTTONS: new Proxy({}, { get: (_, key) => key }) }));
  let coarse = true, fine = false, changed, snapshot, unsubscribe;
  const navigator = { maxTouchPoints: 0 };
  const pointers = loadModule(pointerModule, id => id === 35 ? {
    useSyncExternalStore(subscribe, getSnapshot) {
      snapshot = getSnapshot;
      if (!unsubscribe) unsubscribe = subscribe(() => { context.paseoTerminalInput = snapshot(); });
      return getSnapshot();
    },
  } : { isWeb: true }, { window: { navigator, matchMedia(query) {
    assert.ok(['(any-pointer: coarse)', '(hover: hover) and (pointer: fine)'].includes(query));
    return { get matches() { return query === '(any-pointer: coarse)' ? coarse : fine; },
      addEventListener(type, callback) { assert.equal(type, 'change'); changed = callback; },
      removeEventListener(type, callback) { assert.equal(type, 'change'); assert.equal(callback, changed); },
    };
  } } });
  const pane = moduleAt(patched, '_e.TerminalPane=function');
  const expression = pane.match(/paseoTerminalInput=(\(0,paseoTerminalPointerCapabilities.usePointerCapabilities\)\(\)),we=(\(0,x.shouldShowTerminalVirtualKeyBar\)\(\{[^}]+\}\))/);
  assert.ok(expression, 'reactive input detection is called unconditionally');
  const context = vm.createContext({ paseoTerminalPointerCapabilities: pointers, x: keys, G: { isNative: false }, Te: false });
  const visible = () => {
    context.paseoTerminalInput = vm.runInContext(expression[1], context);
    context.we = vm.runInContext(expression[2], context);
    return context.we;
  };
  const paddingOptions = pane.match(/useKeyboardShiftStyle\)\((\{mode:"padding",enabled:[^}]+\})\)/)[1];
  const insetHandler = pane.match(/Ht=\(0,d.useCallback\)\((e=>\{ze\(we\?e:0\),Oe\(e>0\),Wt\(\)\}),\[we,Wt\]\)/)?.[1];
  assert.ok(insetHandler, 'inset callback must update when touch keyboard eligibility changes');
  const keyboardModule = moduleAt(source, 'e.useKeyboardShiftStyle=function');
  const styleAt = keyboardModule.indexOf('e.useKeyboardShiftStyle=');
  const styleHook = keyboardModule.slice(styleAt + 'e.useKeyboardShiftStyle='.length, keyboardModule.indexOf(';var t=', styleAt));
  let keyboardInset = -1, keyboardVisible = false;
  Object.assign(context, { ze: value => { keyboardInset = value; }, Oe: value => { keyboardVisible = value; }, Wt() {} });
  const keyboardChange = vm.runInContext('(' + insetHandler + ')', context);
  const checkKeyboard = expected => {
    keyboardChange(300);
    const options = vm.runInContext('(' + paddingOptions + ')', context);
    const padding = vm.runInNewContext('(' + styleHook + ')(options)', {
      options, t: { c: () => Array(3).fill(Symbol.for('react.memo_cache_sentinel')) },
      I: { useKeyboardShift: () => ({ shift: { value: 300 }, bottomInset: { value: 0 } }) },
      _: { useAnimatedStyle: fn => fn() }, y: {},
    });
    assert.equal(keyboardInset, expected);
    assert.equal(padding.style.paddingBottom, expected, 'upstream padding and renderer inset agree');
    assert.equal(keyboardVisible, true);
  };
  assert.equal(visible(), true, 'wide tablet');
  checkKeyboard(300);
  fine = true;
  assert.equal(visible(), true, 'touchscreen computer with a mouse still has keys');
  coarse = false; changed();
  assert.equal(vm.runInContext(expression[2], context), false, 'capability changes update the existing pane');
  assert.equal(visible(), false, 'desktop without touch');
  checkKeyboard(0);
  navigator.maxTouchPoints = 5;
  assert.equal(visible(), true, 'touch-point fallback covers devices reporting only a fine pointer');
  checkKeyboard(300);
  navigator.maxTouchPoints = 0;
  context.Te = true;
  assert.equal(visible(), true, 'compact terminal');
  checkKeyboard(300);
  context.Te = false; context.G.isNative = true;
  assert.equal(visible(), true, 'native terminal');
  checkKeyboard(300);
  unsubscribe();
  for (const isCompact of [true, false]) {
    for (const availableWidth of [0, 250, 500, 800]) {
      const original = loadModule(moduleAt(source, runtimeMarker), () => ({ TERMINAL_VIRTUAL_KEY_BUTTONS: new Proxy({}, { get: (_, key) => key }) }));
      assert.equal(JSON.stringify(keys.resolveTerminalVirtualKeyboardRows({ isCompact, availableWidth })), JSON.stringify(original.resolveTerminalVirtualKeyboardRows({ isCompact, availableWidth })));
    }
  }
  assert.throws(() => patchTerminalTouchKeys(source.replace(visibilityBefore, 'e.shouldShowTerminalVirtualKeyBar=changed')), /structure changed/);
  assert.throws(() => patchTerminalTouchKeys(source + pointerModule), /structure changed/);
});
