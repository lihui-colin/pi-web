const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { patchHoverCards } = require('../srcs/patches/service/patch-web-ui.cjs');

// Optional browser dependency: reuse an existing installation, never install one here.
// This exercises the real patched handlers against native DOM events, not React rendering,
// the hover safe zone, overlays, or the full application.
test('patched HoverCard handlers preserve native browser mouse, touch, focus and link behavior', async t => {
  if (!process.env.PASEO_PLAYWRIGHT_MODULE) return t.skip('Set PASEO_PLAYWRIGHT_MODULE to an installed Playwright module');
  const { serverRoot } = require('../srcs/patches/patch-utils.cjs');
  const baseline = require('../srcs/patches/service/patch-web-ui.baseline.json');
  assert.equal(JSON.parse(fs.readFileSync(path.join(serverRoot, 'package.json'))).version, baseline.version);
  const source = fs.readFileSync(path.join(serverRoot, 'dist/server/web-ui', baseline.webEntry), 'utf8');
  const patched = patchHoverCards(source);
  const start = patched.lastIndexOf('\n__d(', patched.indexOf('_e.HoverCard=function'));
  const module = patched.slice(start, patched.indexOf('\n__d(', start + 1));
  const handlers = {
    enter: module.match(/onPointerEnter:(e=>\{[^}]+\}),onPointerLeave/)[1],
    focus: module.match(/n=(t=>\{const n=t.target;[^}]+\}),o=t=>/)[1],
    close: module.match(/const t=(\(\)=>\{P\(\),v\(!1\)\})/)[1],
    press: module.match(/paseoPointerDown=(e=>\{[^}]+\}),n=t=>/)[1],
  };
  const { chromium } = require(process.env.PASEO_PLAYWRIGHT_MODULE);
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  t.after(() => browser.close());
  const context = await browser.newContext({ viewport: { width: 600, height: 500 }, hasTouch: true });
  const page = await context.newPage();
  await page.setContent('<button id="outside">Outside</button><button id="trigger" style="margin:60px">Trigger</button><div id="card" hidden style="padding:30px"><a id="link" href="#activated">Follow link</a></div>');
  await page.evaluate(handlers => {
    const trigger = document.querySelector('#trigger');
    const card = document.querySelector('#card');
    const state = window.hoverState = { opens: 0, closes: 0, clicks: 0, focusVisible: [], pointerTypes: [] };
    const open = () => { state.opens++; card.hidden = false; };
    const clearTimer = () => {};
    const close = new Function('P', 'v', `return (${handlers.close})`)(clearTimer, value => { card.hidden = !value; state.closes++; });
    const enter = new Function('s', `return (${handlers.enter})`)({ openNow: open });
    const focus = new Function('S', 'e', 'b', 'T', 'P', `return (${handlers.focus})`)({ current: false }, trigger, { current: card }, open, clearTimer);
    const press = new Function('b', 't', `return (${handlers.press})`)({ current: card }, close);
    trigger.addEventListener('pointerenter', enter);
    document.addEventListener('focusin', event => { state.focusVisible.push(event.target.matches(':focus-visible')); focus(event); });
    document.addEventListener('pointerdown', event => { state.pointerTypes.push(event.pointerType); press(event); });
    document.querySelector('#link').addEventListener('click', () => { state.clicks++; });
  }, handlers);
  const state = () => page.evaluate(() => ({ ...window.hoverState, open: !document.querySelector('#card').hidden }));

  await page.locator('#trigger').hover();
  assert.equal((await state()).open, true, 'native mouse enter opens the card');
  const beforeLink = await state();
  await page.locator('#link').click();
  const afterLink = await state();
  assert.equal(afterLink.open, true, 'internal mouse press preserves the card through click');
  assert.equal(afterLink.closes, beforeLink.closes);
  assert.equal(afterLink.clicks, 1);
  assert.equal(await page.evaluate(() => location.hash), '#activated');

  await page.locator('#outside').click();
  assert.equal((await state()).open, false, 'outside mouse press dismisses');
  await page.keyboard.press('Tab');
  assert.equal(await page.locator('#trigger').evaluate(node => node.matches(':focus-visible')), true);
  assert.equal((await state()).open, true, 'native keyboard focus opens');

  const beforeTouch = await state();
  await page.locator('#trigger').tap();
  const afterTouch = await state();
  assert.equal(afterTouch.open, false, 'native touch press dismisses without reopening');
  assert.equal(afterTouch.opens, beforeTouch.opens, 'touch enter does not open');
  assert.ok(afterTouch.pointerTypes.includes('touch'));
  await page.locator('#outside').tap();
  const beforeTouchFocus = await state();
  await page.locator('#trigger').tap();
  const afterTouchFocus = await state();
  assert.equal(afterTouchFocus.open, false);
  assert.equal(afterTouchFocus.opens, beforeTouchFocus.opens, 'touch focus does not open');
  assert.equal(await page.locator('#trigger').evaluate(node => node.matches(':focus-visible')), false);

  await page.mouse.move(580, 480);
  await page.locator('#trigger').hover();
  assert.equal((await state()).open, true);
  await page.locator('#link').tap();
  assert.equal((await state()).open, false, 'native touch inside dismisses a lingering card');
  await page.locator('#trigger').dispatchEvent('pointerenter', { pointerType: 'pen' });
  assert.equal((await state()).open, false, 'pen enter does not open');
});
