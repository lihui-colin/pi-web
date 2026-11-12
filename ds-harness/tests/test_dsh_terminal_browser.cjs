// Optional browser integration using an isolated copy of the patched DSH bundle.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require(process.env.DSH_TEST_PLAYWRIGHT);

(async () => {
  const browser = await chromium.launch({headless: true, executablePath: process.env.DSH_TEST_CHROMIUM || undefined});
  try {
    const page = await browser.newPage({viewport: {width: 1000, height: 700}});
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    await page.setContent('<style>body {--dsw-alias-bg-base:#181818;--dsw-alias-bg-l2:#333;--dsw-alias-label-primary:#ddd}</style>');
    // Execute the real component and effects with a small hook harness; no DSH
    // service, authentication, workspace or live terminal is involved.
    await page.evaluate(() => {
      const hooks = [], effects = []; let cursor = 0;
      const effect = (callback, deps) => {
        const index = cursor++, old = hooks[index];
        if (!old || deps.some((value, i) => value !== old.deps[i])) {
          hooks[index] = {deps, cleanup: old?.cleanup};
          effects.push(() => { hooks[index].cleanup?.(); hooks[index].cleanup = callback(); });
        }
      };
      const react = {useRef(value) { const index = cursor++; return hooks[index] ||= {current: value}; },
        useLayoutEffect: effect, useEffect: effect};
      const jsx = (tag, props) => {
        const node = props.ref?.current || document.createElement(tag);
        node.className = props.className || '';
        if (props.ref) props.ref.current = node;
        return node;
      };
      window.__ModuleLoader__ = {load({factory}) {
        window.bundle = factory(name => name === 'react' ? react : name === 'react/jsx-runtime' ? {jsx, jsxs: jsx} : {});
      }};
      window.sent = []; window.sizes = []; window.acks = []; window.opened = []; window.copied = [];
      Object.defineProperty(navigator, 'clipboard', {configurable: true, value: {writeText: async text => copied.push(text)}});
      window.open = (...args) => { opened.push(args); return null; };
      window.model = {write: data => sent.push(data), resize: (...size) => sizes.push(size),
        acknowledge(revision) { acks.push(revision); this.pendingRender = undefined; }};
      window.state = {phase: 'connected', writable: true, environment: {scrollback: 1000, maxCols: 300, maxRows: 100},
        info: {cols: 80, rows: 24}, render: {revision: 1, frame: {type: 'snapshot', info: {cols: 80, rows: 24}, screen: ''}}};
      window.theme = {fontFamilies: {terminal: 'monospace'}, fontSizes: {terminal: 14}};
      window.render = () => {
        cursor = 0;
        if (state.render && model.publishedRender !== state.render) {
          model.publishedRender = state.render;
          model.pendingRender = {revision: state.render.revision};
        }
        const node = bundle.__test.TerminalScreen({state, model, visible: true, label: 'Terminal', theme});
        node.style.width = '800px'; node.style.height = '450px';
        if (!node.isConnected) document.body.appendChild(node);
        while (effects.length) effects.shift()();
        window.term = hooks.map(hook => hook?.current).find(value => value?.buffer && value?.write);
      };
      window.output = data => { state = {...state, render: {revision: state.render.revision + 1, frame: {type: 'output', data}}}; render(); };
      window.cleanup = () => { for (const hook of hooks) hook?.cleanup?.(); };
    });
    const bundle = fs.readFileSync(process.env.DSH_TEST_FRONTEND, 'utf8').replace(
      'exports.TerminalBody = TerminalBody;', 'exports.__test = {TerminalScreen}; exports.TerminalBody = TerminalBody;');
    await page.addScriptTag({content: bundle});
    await page.evaluate(() => render());
    await page.waitForFunction(() => acks.includes(1) && sizes.filter(size => size[2]).length >= 2);
    const baselineResizes = await page.evaluate(() => sizes.length);
    await page.evaluate(() => output('https://example.com/path\r\nfirst needle\r\n中文 needle\r\n'));
    await page.waitForFunction(() => acks.includes(2));
    assert.equal(await page.evaluate(() => sizes.length), baselineResizes, 'ordinary output must not refit the writable terminal');
    await page.keyboard.press('Control+Shift+F');
    const search = page.getByRole('searchbox', {name: 'Find in terminal'});
    await search.fill('needle');
    await page.waitForFunction(() => document.querySelector('[role=search] [role=status]').textContent.endsWith('/ 2'));
    assert.equal(await page.evaluate(() => term.getSelection()), 'needle');
    const first = await page.evaluate(() => term.getSelectionPosition());
    await page.getByRole('button', {name: 'Next match', exact: true}).click();
    assert.notDeepEqual(await page.evaluate(() => term.getSelectionPosition()), first);
    await search.focus(); await page.keyboard.press('Escape'); assert.equal(await search.isVisible(), false);
    assert.deepEqual(await page.evaluate(() => sent), []);
    await page.evaluate(() => { term.clearSelection(); term.focus(); });
    await page.keyboard.press('Shift+Enter'); assert.deepEqual(await page.evaluate(() => sent.splice(0)), ['\r']);
    await page.evaluate(() => output('\x1b[>1u\x1b[?u\x1b[c\x1b[6n'));
    await page.waitForFunction(() => acks.includes(3));
    assert.deepEqual(await page.evaluate(() => sent.splice(0)), []);
    await page.keyboard.press('Shift+Enter'); await page.keyboard.press('Control+Enter'); await page.keyboard.press('Control+c');
    assert.deepEqual(await page.evaluate(() => sent.splice(0)), ['\x1b[13;2u', '\x1b[13;5u', '\x1b[99;5u']);
    await page.keyboard.insertText('中文'); assert.deepEqual(await page.evaluate(() => sent.splice(0)), ['中文']);
    await page.evaluate(async () => {
      term.textarea.dispatchEvent(new CompositionEvent('compositionstart', {data: '', bubbles: true}));
      term.textarea.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', shiftKey: true, isComposing: true, keyCode: 229, bubbles: true}));
      term.textarea.dispatchEvent(new CompositionEvent('compositionend', {data: '', bubbles: true}));
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    });
    assert.deepEqual(await page.evaluate(() => sent.splice(0)), []);
    await page.evaluate(() => term.select(0, 1, 5));
    await page.keyboard.press('Control+c'); assert.deepEqual(await page.evaluate(() => sent.splice(0)), []);
    await page.keyboard.press('Control+v');
    await page.waitForFunction(() => sent.length > 0);
    assert.deepEqual(await page.evaluate(() => sent.splice(0)), ['first']);
    await page.evaluate(() => {
      term.clearSelection();
      const clipboardData = new DataTransfer(); clipboardData.setData('text/plain', 'pasted text');
      term.textarea.dispatchEvent(new ClipboardEvent('paste', {clipboardData, bubbles: true, cancelable: true}));
    });
    assert.deepEqual(await page.evaluate(() => sent.splice(0)), ['pasted text']);
    // Read-only views may search, but cannot send enhanced keys or steal control.
    await page.evaluate(() => { state = {...state, writable: false}; render(); term.focus(); });
    await page.keyboard.press('Shift+Enter'); assert.deepEqual(await page.evaluate(() => sent.splice(0)), []);
    await page.keyboard.press('Control+Shift+F'); assert.equal(await search.isVisible(), true);
    await search.press('Escape');
    const point = await page.evaluate(() => {
      const rect = term.element.querySelector('.xterm-screen').getBoundingClientRect();
      const cell = term._core._renderService.dimensions.css.cell;
      return {x: rect.x + cell.width * 8, y: rect.y + cell.height / 2};
    });
    await page.mouse.move(point.x, point.y);
    await page.waitForFunction(() => !!term.element.querySelector('.xterm-cursor-pointer'));
    await page.mouse.click(point.x, point.y); assert.deepEqual(await page.evaluate(() => opened), []);
    await page.keyboard.down('Control'); await page.mouse.click(point.x, point.y); await page.keyboard.up('Control');
    assert.deepEqual(await page.evaluate(() => opened), [['https://example.com/path', '_blank', 'noopener,noreferrer']]);
    // Real xterm parsing: pending output is cancelled before the replacement snapshot.
    const freshRevision = await page.evaluate(() => {
      const revision = state.render.revision;
      // Consume xterm's immediate echo after recent keyboard input; the next
      // write then follows its normal asynchronous parser queue.
      term.write('\x1b[0m');
      output('OLD\x1b]52;c;b2xk\x07');
      model.pendingRender = undefined;
      state = {...state, phase: 'disconnected', render: undefined}; render();
      state = {...state, phase: 'connected', writable: false,
        render: {revision: revision + 2, frame: {type: 'snapshot', info: {cols: 80, rows: 24},
          screen: 'FRESH\x1b]52;c;c25hcHNob3Q=\x07'}}}; render();
      return revision + 2;
    });
    await page.waitForFunction(revision => acks.includes(revision), freshRevision);
    assert.equal(await page.evaluate(() => term.buffer.active.getLine(0).translateToString(true)), 'FRESH');
    assert.equal(await page.evaluate(revision => acks.includes(revision - 1), freshRevision), false);
    await page.evaluate(() => { state = {...state, writable: true}; render(); output('!'); });
    await page.waitForFunction(revision => acks.includes(revision + 1), freshRevision);
    assert.deepEqual(await page.evaluate(() => copied), []);
    // Hold a genuinely parsed empty-write callback, unmount, then release it.
    await page.evaluate(async () => {
      const originalWrite = term.write.bind(term), originalReset = term.reset.bind(term);
      window.heldFence = []; window.lateResets = 0;
      term.reset = () => { lateResets++; originalReset(); };
      term.write = (data, callback) => originalWrite(data, () => heldFence.push(callback));
      const revision = state.render.revision + 1;
      state = {...state, render: {revision, frame: {type: 'snapshot', info: {cols: 80, rows: 24}, screen: 'STALE'}}};
      render();
    });
    await page.waitForFunction(() => heldFence.length === 1);
    const beforeUnmount = await page.evaluate(() => ({acks: acks.slice(), sizes: sizes.length}));
    await page.evaluate(() => { cleanup(); heldFence.shift()(); });
    assert.equal(await page.evaluate(() => lateResets), 0);
    assert.deepEqual(await page.evaluate(() => acks), beforeUnmount.acks);
    assert.deepEqual(await page.evaluate(() => copied), []);
    assert.equal(await page.locator('[role=search]').count(), 0);
    assert.deepEqual(errors, []);
    console.log('Browser: component mount/cleanup, search, links, negotiated keys, copy/paste, IME and read-only view passed.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
