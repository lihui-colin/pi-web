'use strict';
const assert = require('node:assert/strict');
const {source} = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const {track, renderRef} = new Function(source + '\nreturn {track: dshTrackFilesNavigator, renderRef: navigatorRefFixture};')();
const attribute = 'data-dsh-files-navigator-layout';
const parent = () => ({
  attributes: new Map(),
  setAttribute(name, value) { this.attributes.set(name, value); },
  getAttribute(name) { return this.attributes.get(name) ?? null; },
  removeAttribute(name) { this.attributes.delete(name); },
});
const layout = element => element.getAttribute(attribute);
const a = parent(), b = parent();
const first = {parentElement: a}, second = {parentElement: a};
const cleanupFirst = track(first, 'push');
assert.equal(layout(a), 'panel');
const cleanupSecond = track(second, 'fill');
assert.equal(layout(a), 'panel fill');
cleanupFirst();
assert.equal(layout(a), 'panel fill');
cleanupSecond();
assert.equal(layout(a), null);
cleanupSecond(); // repeated cleanup is harmless
assert.equal(track(first, undefined), undefined);
assert.equal(track(null, 'fill'), undefined);
assert.equal(track({parentElement: null}, 'fill'), undefined);
assert.equal(layout(a), null);
const obsolete = track(first, 'fill');
const latest = track(first, 'overlay');
obsolete();
assert.equal(layout(a), 'panel');
latest();
assert.equal(layout(a), null);

// Minimal hook/ref commit harness: useCallback identity follows dependencies,
// and a changed callback receives null before the replacement gets the node.
const ref = {current: undefined};
let memo, active;
const events = [];
const react = {
  useRef: () => ref,
  useCallback(callback, deps) {
    if (!memo || deps.some((item, index) => !Object.is(item, memo.deps[index]))) memo = {callback, deps};
    return memo.callback;
  },
};
const drawn = (...args) => events.push(args);
function commit(mode, page, element = first, paneId = 'pane') {
  const next = renderRef(react, drawn, paneId, page, mode);
  if (next !== active) {
    active?.(null);
    next(element);
    active = next;
  }
  return next;
}
const initial = commit('fill', false);
assert.equal(layout(a), 'panel fill');
assert.equal(commit('fill', false), initial);
assert.notEqual(commit('push', false), initial);
assert.equal(layout(a), 'panel');
commit('overlay', false);
assert.equal(layout(a), 'panel');
commit('fill', true);
assert.equal(layout(a), null); // wholePage must not hide siblings
assert.deepEqual(events.at(-1), ['pane', first, false]);
commit('fill', false);
assert.equal(layout(a), 'panel fill');
active(null); // hidden/no cwd/unmounted: React detaches the ref
assert.equal(layout(a), null);
first.parentElement = b;
active(first); // reparent/remount clears the old parent and marks the new one
assert.equal(layout(a), null);
assert.equal(layout(b), 'panel fill');
assert.deepEqual(events.at(-1), ['pane', first, true]);
active(null);
assert.equal(layout(b), null);
console.log('Navigator parent aggregation and callback-ref lifecycle verified.');
