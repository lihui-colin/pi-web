'use strict';
// Called by test_dsh_sidebar_render.py with the actual transformed fixture.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require(process.env.DSH_TEST_PLAYWRIGHT);
const {original, fixed, helper} = JSON.parse(fs.readFileSync(0, 'utf8'));

(async () => {
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.DSH_TEST_CHROMIUM ? {executablePath: process.env.DSH_TEST_CHROMIUM} : {}),
  });
  try {
    const page = await browser.newPage();
    for (const width of [390, 767, 768, 1600]) {
      await page.setViewportSize({width, height: 800});
      for (const mode of ['normal', 'fill', 'wholePage']) {
        const navigatorClass = 'k-1LKG_navigator' + (mode === 'normal' ? '' : ` k-1LKG_${mode}`);
        const markup = ['data-files-content', 'data-textpreview-content'].map(attribute => `
          <div ${attribute}>
            <section data-body><span>preview</span></section><aside data-other>other sibling</aside>
            <nav class="${navigatorClass}"><span data-tree>tree</span></nav>
          </div>`).join('') + `
          <div class="xterm"><div class="xterm-screen"><div class="xterm-rows"><div><span>glyph</span></div></div></div></div>
          <div data-unrelated><section>unrelated sibling</section><nav class="${navigatorClass}"></nav></div>`;
        const snapshot = async (css, mark) => {
          await page.setContent(`<style>${css}</style>${markup}`);
          if (mark) {
            await page.addScriptTag({content: '(function(){' + helper + '\nwindow.trackNavigator = dshTrackFilesNavigator;})();'});
            await page.evaluate(mode => {
              for (const parent of document.querySelectorAll('[data-files-content],[data-textpreview-content]')) {
                window.trackNavigator(parent.querySelector('nav'), mode === 'wholePage' ? undefined : mode);
              }
            }, mode);
          }
          return page.evaluate(() => ({
            parents: [...document.querySelectorAll('[data-files-content],[data-textpreview-content]')].map(parent =>
              [...parent.querySelectorAll('[data-body], [data-body] span, [data-other], nav, [data-tree]')]
                .map(node => getComputedStyle(node).visibility)),
            terminal: [...document.querySelectorAll('.xterm, .xterm div, .xterm span')]
              .map(node => getComputedStyle(node).visibility),
            unrelated: getComputedStyle(document.querySelector('[data-unrelated] section')).visibility,
          }));
        };
        const before = await snapshot(original);
        const after = await snapshot(fixed, true);
        const hidden = mode === 'fill' || (width < 768 && mode !== 'wholePage');
        assert.deepEqual(after.parents, before.parents, `${width}px ${mode}: parent semantics`);
        for (const visibility of after.parents) {
          assert.deepEqual(visibility, [hidden ? 'hidden' : 'visible', hidden ? 'hidden' : 'visible',
            hidden ? 'hidden' : 'visible', 'visible', 'visible']);
        }
        assert.ok(after.terminal.every(value => value === 'visible'));
        assert.deepEqual(after.terminal, before.terminal);
        assert.equal(after.unrelated, 'visible');
        assert.equal(before.unrelated, hidden ? 'hidden' : 'visible');
      }
    }
    // Three classes tie both the original and replacement selectors. A later
    // rule must still win, preserving their specificity.
    for (const css of [original, fixed]) {
      await page.setViewportSize({width: 390, height: 800});
      await page.setContent(`<style>${css}.priority.priority.priority{visibility:visible}</style>
        <div data-textpreview-content data-dsh-files-navigator-layout="panel fill"><section class="priority">content</section>
        <nav class="k-1LKG_navigator k-1LKG_fill"></nav></div>`);
      assert.equal(await page.locator('.priority').evaluate(node => getComputedStyle(node).visibility), 'visible');
    }
    console.log('Navigator CSS: both parents, modes, breakpoints, siblings, xterm, and specificity verified.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
