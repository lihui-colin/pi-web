// Run through test_dsh_terminal_apply.py, which resolves the pinned DSH modules.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {Terminal} = require(path.join(process.env.DSH_TEST_MODULES, '@xterm/headless'));
const {SerializeAddon} = require(path.join(process.env.DSH_TEST_MODULES, '@xterm/addon-serialize'));
const source = name => fs.readFileSync(path.join(__dirname, 'patches', name), 'utf8');
const api = {};
vm.runInNewContext(source('dsh_terminal_keyboard.js') + source('dsh_terminal_queries.js') + source('dsh_terminal_snapshot.js'), api);
const write = (term, data) => new Promise(resolve => term.write(data, resolve));
const terminal = () => new Terminal({cols: 80, rows: 24, allowProposedApi: true});

test('headless replies work without a browser; attached views never duplicate them', async t => {
  const host = terminal(), a = terminal(), b = terminal();
  const sent = [], browserInput = [];
  const protocol = api.createTerminalHostProtocol(host, {write: async data => sent.push(data)}, () => true);
  t.after(() => { protocol.dispose(); host.dispose(); a.dispose(); b.dispose(); });
  for (const view of [a, b]) {
    const queries = api.suppressTerminalQueries(view), keyboard = api.createTerminalKeyboardState(view);
    t.after(() => { queries.dispose(); keyboard.dispose(); });
    view.onData(data => browserInput.push(data));
  }
  const chunks = ['hello\x1b[?', 'u\x1b[c\x1b[>c\x1b[5n\x1b[6n\x1b[?6n',
    '\x1b[?2004h\x1b[?2004$p\x1b[4$p\x1bP$qm\x1b\\'];
  for (const chunk of chunks) {
    await write(host, chunk); await protocol.flush();
    await write(a, chunk); await write(b, chunk);
  }
  assert.equal(sent.join(''), '\x1b[?0u\x1b[?1;2c\x1b[>0;276;0c\x1b[0n\x1b[1;6R\x1b[?1;6R'
    + '\x1b[?2004;1$y\x1b[4;2$y\x1bP1$r0m\x1b\\');
  assert.deepEqual(browserInput, []);
  assert.equal(a.buffer.active.getLine(0).translateToString(true), 'hello');
});

test('query replies are bounded, awaited, and discarded after exit/disposal', async t => {
  const host = terminal(); t.after(() => host.dispose());
  const sent = []; let running = true, fail = false;
  const protocol = api.createTerminalHostProtocol(host, {write: async data => {
    if (fail) throw Error('write failed'); sent.push(data);
  }}, () => running);
  t.after(() => protocol.dispose());
  await write(host, '\x1b[5n'.repeat(20000)); await protocol.flush();
  assert.equal(sent.length, 1); assert.equal(sent[0].length, 65536);
  running = false; await write(host, '\x1b[5n'); await protocol.flush(); assert.equal(sent.length, 1);
  running = true; fail = true; await write(host, '\x1b[5n');
  await assert.rejects(protocol.flush(), /write failed/);
  protocol.dispose(); await write(host, '\x1b[5n'); await protocol.flush(); assert.equal(sent.length, 1);
});

test('Kitty negotiation is parser ordered, bounded and independent per buffer', async t => {
  const term = terminal(), replies = [], keys = api.createTerminalKeyboardState(term, data => replies.push(data));
  t.after(() => { keys.dispose(); term.dispose(); });
  await write(term, '\x1b[>'); assert.equal(keys.flags(), 0);
  await write(term, '31u\x1b[?u'); assert.equal(keys.flags(), 1); assert.deepEqual(replies, ['\x1b[?1u']);
  await write(term, '\x1b[>u'); assert.equal(keys.flags(), 0);
  await write(term, '\x1b[<u'); assert.equal(keys.flags(), 1);
  await write(term, '\x1b[=1;3u'); assert.equal(keys.flags(), 0);
  await write(term, '\x1b[=1;2u'); assert.equal(keys.flags(), 1);
  await write(term, '\x1b[=0;2u'); assert.equal(keys.flags(), 1);
  await write(term, '\x1b[?1049h'); assert.equal(keys.flags(), 0);
  await write(term, '\x1b[>1u\x1b[>0u'); assert.equal(keys.flags(), 0);
  await write(term, '\x1b[?1049l'); assert.equal(keys.flags(), 1);
  await write(term, '\x1b[>1u'.repeat(100));
  assert.ok(keys.snapshot('').length < 400);
  await write(term, '\x1b[<32u'); assert.equal(keys.flags(), 0);
  await write(term, '\x1b[>1u\x1bc'); assert.equal(keys.flags(), 0);
});

test('reconnect restores nested keyboard stacks and both screen contents', async t => {
  for (const alternate of [false, true]) {
    const host = terminal(), view = terminal(), serializer = new SerializeAddon(); host.loadAddon(serializer);
    const keys = api.createTerminalKeyboardState(host), restored = api.createTerminalKeyboardState(view);
    t.after(() => { keys.dispose(); restored.dispose(); host.dispose(); view.dispose(); });
    await write(host, '\x1b[>1u\x1b[>0uMain\x1b[?1049h\x1b[>0u\x1b[>1uAlternate');
    if (!alternate) await write(host, '\x1b[?1049l');
    const snapshot = keys.snapshot(serializer.serialize() + api.terminalSnapshotModes(host));
    await write(view, snapshot);
    assert.equal(restored.flags(), keys.flags()); assert.equal(view.buffer.active.type, host.buffer.active.type);
    for (let row = 0; row < 24; row++) {
      assert.equal(view.buffer.active.getLine(row).translateToString(), host.buffer.active.getLine(row).translateToString());
    }
    for (const operation of ['\x1b[<u', '\x1b[?1047h', '\x1b[<u', '\x1b[?1047l', '\x1b[<u']) {
      await write(host, operation); await write(view, operation); assert.equal(restored.flags(), keys.flags());
    }
  }
});

test('negotiated keys distinguish Enter modifiers and preserve text/IME', () => {
  const event = (key, extra = {}) => ({type: 'keydown', key, ...extra});
  for (const [extra, modifier] of [[{shiftKey: true}, 2], [{altKey: true}, 3], [{ctrlKey: true}, 5],
    [{ctrlKey: true, shiftKey: true}, 6]]) {
    assert.equal(api.encodeTerminalKey(event('Enter', extra), 1), `\x1b[13;${modifier}u`);
    assert.equal(api.encodeTerminalKey(event('Enter', extra), 0), undefined);
  }
  assert.equal(api.encodeTerminalKey(event('c', {ctrlKey: true}), 1), '\x1b[99;5u');
  assert.equal(api.encodeTerminalKey(event('I', {ctrlKey: true, shiftKey: true}), 1), '\x1b[105;6u');
  assert.equal(api.encodeTerminalKey(event('Escape'), 1), '\x1b[27;1u');
  assert.equal(api.encodeTerminalKey(event('F3', {ctrlKey: true}), 1), '\x1b[13;5~');
  assert.equal(api.encodeTerminalKey(event('ArrowUp', {ctrlKey: true}), 1), '\x1b[1;5A');
  assert.equal(api.encodeTerminalKey(event('F1'), 1), '\x1b[1;1P');
  for (const value of [event('Enter'), event('文'), event('a'), event('A', {shiftKey: true}),
    event('Enter', {shiftKey: true, isComposing: true}), event('Enter', {ctrlKey: true, keyCode: 229}),
    event('@', {ctrlKey: true, altKey: true, getModifierState: key => key === 'AltGraph'}),
    event('c', {metaKey: true}), event('Enter', {shiftKey: true, type: 'keyup'})]) {
    assert.equal(api.encodeTerminalKey(value, 1), undefined);
  }
});

function events(target = {}) {
  const listeners = new Map();
  return Object.assign(target, {
    addEventListener(name, fn) { if (!listeners.has(name)) listeners.set(name, new Set()); listeners.get(name).add(fn); },
    removeEventListener(name, fn) { listeners.get(name)?.delete(fn); },
    emit(name, event = {}) { for (const fn of listeners.get(name) || []) fn(event); },
    listenerCount() { return [...listeners.values()].reduce((sum, set) => sum + set.size, 0); }
  });
}

test('focus, visibility, viewport and fonts refit only a parsed controllable view and clean up', async () => {
  let fontReady, frame, pulse, fits = 0, refreshes = 0, resizes = 0;
  const fonts = events({ready: new Promise(resolve => { fontReady = resolve; })});
  const window = events({visualViewport: events(), requestAnimationFrame(fn) { frame = fn; return 1; }, cancelAnimationFrame() { frame = undefined; }});
  const document = events({defaultView: window, fonts, visibilityState: 'visible'});
  const node = {ownerDocument: document, clientWidth: 800, clientHeight: 600};
  const term = {rows: 24, resize() { resizes++; }, refresh() { refreshes++; }};
  const live = {visible: true, state: {phase: 'connected', writable: true, environment: {maxCols: 100, maxRows: 50}}};
  const runtime = {fitScreen() { fits++; }, setTimeout(fn) { pulse = fn; return 1; }, clearTimeout() { pulse = undefined; }};
  vm.runInNewContext(source('dsh_terminal_runtime.js'), runtime);
  const redraw = runtime.createTerminalRedraw(term, {proposeDimensions: () => ({cols: 80, rows: 24})}, node, {resize() {}}, () => live);
  window.emit('focus'); assert.equal(fits, 0); assert.equal(refreshes, 0);
  redraw.parsed(redraw.prepare()); pulse();
  for (const [target, event] of [[window, 'focus'], [window, 'resize'], [window.visualViewport, 'resize'],
    [document, 'visibilitychange'], [fonts, 'loadingdone']]) {
    const before = fits; target.emit(event); assert.ok(fits > before);
  }
  const beforeFont = fits; fontReady(); await Promise.resolve(); assert.ok(fits > beforeFont);
  assert.ok(frame); frame();
  const beforeHidden = [fits, resizes, refreshes]; document.visibilityState = 'hidden'; window.emit('focus');
  assert.deepEqual([fits, resizes, refreshes], beforeHidden);
  document.visibilityState = 'visible'; live.state.writable = false; window.emit('focus'); assert.equal(fits, beforeHidden[0]);
  live.state.writable = true; live.state.phase = 'disconnected'; window.emit('focus'); assert.equal(fits, beforeHidden[0]);
  live.state.phase = 'connected'; window.emit('focus'); assert.equal(fits, beforeHidden[0]);
  redraw.parsed(redraw.prepare()); pulse();
  redraw.dispose();
  const beforeDispose = fits; window.emit('focus'); fonts.emit('loadingdone'); assert.equal(fits, beforeDispose);
  for (const target of [window, window.visualViewport, document, fonts]) assert.equal(target.listenerCount(), 0);
  assert.equal(frame, undefined);
});
