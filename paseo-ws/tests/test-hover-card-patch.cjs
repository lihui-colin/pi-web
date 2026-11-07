const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { patchHoverCards } = require('../srcs/patches/service/patch-web-ui.cjs');

test('upstream hover cards ignore touch and pen, preserve mouse and keyboard, and close on press', t => {
  const file = path.join(__dirname, '../runtime/lib/node_modules/@getpaseo/cli/node_modules/@getpaseo/server/dist/server/web-ui/_expo/static/js/web/index-1ac09e1966ac6dd37f983e4daa1beff5.js');
  if (!fs.existsSync(file)) return t.skip('Original Paseo 0.14.0 bundle not installed');
  const original = fs.readFileSync(file, 'utf8');
  const patched = patchHoverCards(original);
  assert.equal(patchHoverCards(patched), patched);
  const start = patched.lastIndexOf('\n__d(', patched.indexOf('_e.HoverCard=function'));
  const module = patched.slice(start, patched.indexOf('\n__d(', start + 1));
  let opens = 0, closes = 0;
  const context = vm.createContext({
    s: { openNow() { opens++; } },
    _: { current: false },
    e: { contains: target => target.trigger },
    f: { current: null },
    I() { opens++; }, L() {},
  });
  const enter = vm.runInContext('(' + module.match(/onPointerEnter:(e=>\{[^}]+\}),onPointerLeave/)[1] + ')', context);
  for (const pointerType of ['touch', 'pen', '']) enter({ pointerType });
  assert.equal(opens, 0);
  enter({ pointerType: 'mouse' });
  assert.equal(opens, 1);
  const focus = vm.runInContext('(' + module.match(/n=(t=>\{const n=t.target;[^}]+\}),o=t=>/)[1] + ')', context);
  focus({ target: { trigger: true, matches: () => false } });
  assert.equal(opens, 1, 'touch focus cannot open a card');
  focus({ target: { trigger: true, matches: () => true } });
  assert.equal(opens, 2, 'visible keyboard focus still opens a card');
  const close = vm.runInNewContext('(' + module.match(/const t=(\(\)=>\{L\(\),y\(!1\)\})/)[1] + ')', {
    L() {}, y(value) { assert.equal(value, false); closes++; },
  });
  assert.ok(module.includes('document.addEventListener("pointerdown",t)'));
  assert.ok(module.includes('document.removeEventListener("pointerdown",t)'));
  close();
  assert.equal(closes, 1);
  assert.equal(patched.slice(0, start), original.slice(0, start));
  assert.throws(() => patchHoverCards(original.replace('onPointerEnter:s.openNow', 'onPointerEnter:changed')), /structure changed/);
});
