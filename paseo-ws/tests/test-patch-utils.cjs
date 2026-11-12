const { test } = require('node:test');
const assert = require('node:assert/strict');
const { replaceOnce } = require('../srcs/patches/patch-utils.cjs');

test('replacement accepts one original or patched implementation, including nested forms', () => {
  assert.throws(() => replaceOnce('aaaa', 'aaa', 'NEW'), /structure changed/, 'overlapping anchors are ambiguous');
  for (const [before, after] of [['OLD', 'NEW'], ['OLD', 'OLD extended'], ['OLD extended', 'OLD']]) {
    assert.equal(replaceOnce(`prefix ${before} suffix`, before, after), `prefix ${after} suffix`);
    assert.equal(replaceOnce(`prefix ${after} suffix`, before, after), `prefix ${after} suffix`);
    for (const source of ['', before + before, after + after, before + after, after + before]) {
      assert.throws(() => replaceOnce(source, before, after), /structure changed/);
    }
  }
});
