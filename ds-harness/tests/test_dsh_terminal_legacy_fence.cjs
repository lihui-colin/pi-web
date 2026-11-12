// Execute the installed legacy effect body with the reviewed real parser API.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');
const {Terminal} = require(path.join(process.env.DSH_TEST_MODULES, '@xterm/headless'));
const {SerializeAddon} = require(path.join(process.env.DSH_TEST_MODULES, '@xterm/addon-serialize'));
const source = JSON.parse(fs.readFileSync(0, 'utf8'));
const effect = new Function('xterm', 'render', 'terminal', 'redraw', 'clipboard', 'terminalTools',
  'current', 'lastRevision', 'model', source.write);
function harness(term) {
  const events = [], acks = [], copies = [];
  const createElement = () => ({style: {}, appendChild() {}, setAttribute() {}, remove() {}});
  const context = {TextDecoder, Uint8Array, atob, setTimeout, clearTimeout,
    document: {createElement}, navigator: {clipboard: {writeText: async text => copies.push(text)}}};
  vm.runInNewContext(source.clipboard, context);
  const clip = context.createTerminalClipboard(term, {style: {}, appendChild() {}});
  let token = 0;
  const terminal = {current: term}, clipboard = {current: clip};
  const redraw = {current: {prepare() {events.push('prepare'); return ++token;}, parsed(t) {events.push(['parsed', t]);}}};
  const terminalTools = {current: {reset() {events.push('reset');}}};
  const current = {current: {visible: true, state: {phase: 'connected', writable: true}}};
  const lastRevision = {current: 0};
  let acknowledged;
  const model = {acknowledge(revision) {acks.push(revision); this.pendingRender = undefined; acknowledged?.();}};
  return {events, acks, copies, current, terminal, redraw, clipboard, model,
    run(render) {current.current.state.render = render; lastRevision.current = render.revision;
      model.pendingRender = {revision: render.revision};
      return effect(term, render, terminal, redraw, clipboard, terminalTools, current, lastRevision, model);},
    done() {return new Promise(resolve => {acknowledged = resolve;});},
    dispose() {clip.dispose(); term.dispose?.(); terminal.current = undefined;}};
}
const osc = text => '\x1b]52;c;' + Buffer.from(text).toString('base64') + '\x07';
const output = (revision, data) => ({revision, frame: {type: 'output', data}});
const snapshot = (revision, screen) => ({revision, frame: {type: 'snapshot', screen, info: {cols: 80, rows: 24}}});
const write = (term, data) => new Promise(resolve => term.write(data, resolve));

test('pending old parser output, abort and readonly serialized snapshot have a real empty-write fence', async t => {
  const host = new Terminal({allowProposedApi: true});
  const serializer = new SerializeAddon(); host.loadAddon(serializer);
  const view = new Terminal({allowProposedApi: true}); const h = harness(view);
  t.after(() => {host.dispose(); h.dispose();});
  await write(host, 'FRESH');
  const abort = h.run(output(1, 'OLD' + osc('old clipboard')));
  abort(); h.current.current.state = {phase: 'disconnected', writable: false};
  h.current.current.state = {phase: 'connected', writable: false};
  const done = h.done(); h.run(snapshot(3, serializer.serialize() + osc('snapshot clipboard')));
  assert.deepEqual(h.events, ['prepare']);
  await done;
  assert.equal(view.buffer.active.getLine(0).translateToString(true), 'FRESH');
  assert.deepEqual(h.acks, [3]); assert.deepEqual(h.copies, []);
  assert.deepEqual(h.events, ['prepare', 'reset', ['parsed', 1]]);
  // Neither snapshot OSC 52 nor stale old OSC 52 can replay on the next writable output.
  h.current.current.state.writable = true;
  const next = h.done(); h.run(output(4, '!')); await next;
  assert.deepEqual(h.copies, []);
  const live = h.done(); h.run(output(5, osc('live'))); await live;
  assert.deepEqual(h.copies, ['live']);
});

function fakeTerm() {
  const callbacks = [], writes = [], resets = [];
  return {callbacks, writes, resets, parser: {registerOscHandler: () => ({dispose() {}})},
    write(data, callback) {writes.push(data); callbacks.push(callback);},
    reset() {resets.push('reset');}, resize() {resets.push('resize');}};
}
for (const invalidate of ['revision', 'phase', 'terminal', 'unmount', 'model-cancel', 'model-generation']) {
  test(`stale fence and parse callbacks ignore ${invalidate}`, () => {
    for (const parsed of [false, true]) {
      const term = fakeTerm(), h = harness(term), cleanup = h.run(snapshot(1, 'obsolete'));
      assert.deepEqual(term.writes, ['']);
      if (parsed) term.callbacks.shift()();
      const before = {resets: term.resets.length, events: h.events.length, writes: term.writes.length};
      if (invalidate === 'revision') h.current.current.state.render = snapshot(2, 'new');
      if (invalidate === 'phase') h.current.current.state.phase = 'disconnected';
      if (invalidate === 'terminal') h.terminal.current = {};
      if (invalidate === 'unmount') cleanup();
      if (invalidate === 'model-cancel') h.model.pendingRender = undefined;
      if (invalidate === 'model-generation') h.model.pendingRender = {revision: 2};
      term.callbacks.shift()();
      assert.equal(term.resets.length, before.resets);
      assert.equal(term.writes.length, before.writes);
      assert.equal(h.events.length, before.events);
      assert.deepEqual(h.acks, []); assert.deepEqual(h.copies, []); h.dispose();
    }
  });
}
