const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { patchHoverCards } = require('../srcs/patches/service/patch-web-ui.cjs');

test('upstream hover cards ignore touch and pen, preserve mouse and keyboard, and close on press', t => {
  const { serverRoot } = require('../srcs/patches/patch-utils.cjs');
  const baseline = require('../srcs/patches/service/patch-web-ui.baseline.json');
  if (!fs.existsSync(path.join(serverRoot, 'package.json')) || JSON.parse(fs.readFileSync(path.join(serverRoot, 'package.json'))).version !== baseline.version) return t.skip(`Paseo ${baseline.version} bundle not installed`);
  const web = path.join(serverRoot, 'dist/server/web-ui');
  const original = fs.readFileSync(path.join(web, baseline.webEntry), 'utf8');
  const patched = patchHoverCards(original);
  assert.equal(patchHoverCards(patched), patched);
  const start = patched.lastIndexOf('\n__d(', patched.indexOf('_e.HoverCard=function'));
  const module = patched.slice(start, patched.indexOf('\n__d(', start + 1));
  let opens = 0, closes = 0;
  const context = vm.createContext({
    s: { openNow() { opens++; } },
    S: { current: false },
    e: { contains: target => target.trigger },
    b: { current: null },
    T() { opens++; }, P() {},
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
  const close = vm.runInNewContext('(' + module.match(/const t=(\(\)=>\{P\(\),v\(!1\)\})/)[1] + ')', {
    P() {}, v(value) { assert.equal(value, false); closes++; },
  });
  assert.ok(module.includes('document.addEventListener("pointerdown",paseoPointerDown)'));
  assert.ok(module.includes('document.removeEventListener("pointerdown",paseoPointerDown)'));
  const press = vm.runInNewContext('(' + module.match(/paseoPointerDown=(e=>\{[^}]+\}),n=t=>/)[1] + ')', {
    b: { current: { contains: target => target.inside } }, t: close,
  });
  press({ pointerType: 'mouse', target: { inside: true } });
  assert.equal(closes, 0, 'internal mouse press preserves links until click');
  press({ pointerType: 'mouse', target: { inside: false } });
  assert.equal(closes, 1, 'outside mouse press closes the card');
  for (const pointerType of ['touch', 'pen']) {
    press({ pointerType, target: { inside: true } });
  }
  assert.equal(closes, 3, 'touch and pen dismiss lingering hover cards');
  assert.equal(patched.slice(0, start), original.slice(0, start));
  assert.throws(() => patchHoverCards(original.replace('onPointerLeave:s.scheduleClose', 'onPointerLeave:changed')), /structure changed/);
});
