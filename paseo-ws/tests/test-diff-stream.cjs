'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const { serverRoot } = require('../srcs/patches/patch-utils.cjs');
const baseline = require('../srcs/patches/service/patch-web-ui.baseline.json');

test('Web UX patch delegates diff transport entirely to upstream', () => {
  const patch = fs.readFileSync(path.join(__dirname, '../srcs/patches/service/patch-web-ui.cjs'), 'utf8');
  assert.equal(patch.includes('patchDiffTransport'), false);
  assert.equal(patch.includes("require('./diff-transport.cjs')"), false);
});

test('selected release client exposes entries first and commits bodies only at End', t => {
  if (!fs.existsSync(path.join(serverRoot, 'package.json')) || JSON.parse(fs.readFileSync(path.join(serverRoot, 'package.json'))).version !== baseline.version) return t.skip(`Paseo ${baseline.version} bundle not installed`);
  const web = path.join(serverRoot, 'dist/server/web-ui');
  const entry = fs.readFileSync(path.join(web, 'index.html'), 'utf8').match(/src="(\/_expo\/static\/js\/web\/index-[a-f0-9]+\.js)"/)?.[1];
  assert.ok(entry);
  const source = fs.readFileSync(path.join(web, entry), 'utf8');
  assert.ok(source.includes('observeDiff(e){return this.diffStreams.observe(e)}'));
  assert.equal(source.includes('__paseoGetBulkDiffTransport'), false);
  const line = source.split('\n').find(line => line.includes('"Duplicate diff entry"'));
  assert.ok(line, 'official revision assembly is included in the served bundle');
  let factory;
  vm.runInNewContext(line, { __d(value) { factory = value; } });
  const exported = {};
  const DiffOpcode = { Begin: 64, Bodies: 65, End: 66 };
  factory(null, () => ({ DiffOpcode, materializeDiffFile: (entry, body) => ({ path: entry.path, hunks: body?.hunks ?? [], status: 'ok' }) }), null, null, null, exported, [0]);
  const published = [];
  const stream = new exported.DiffStream(value => published.push(value));
  stream.receive({ opcode: 64, revision: 1, baseRevision: 0, entries: [{ path: 'a.txt', content: 'text', body: true }] });
  assert.equal(published.length, 1);
  assert.equal(published[0].phase, 'loading');
  assert.equal(published[0].entries[0].path, 'a.txt');
  stream.receive({ opcode: 65, revision: 1, files: [{ path: 'a.txt', hunks: [{ lines: [] }] }] });
  assert.equal(published.length, 1, 'body batches do not publish incomplete revisions');
  stream.receive({ opcode: 66, revision: 1, omitted: [], diffTooLarge: false, error: null });
  assert.equal(published.length, 2);
  assert.equal(published[1].phase, 'ready');
  const committedFile = published[1].files[0];
  stream.receive({ opcode: 64, revision: 2, baseRevision: 1, entries: [{ path: 'a.txt', content: 'text', body: false }] });
  assert.equal(published.length, 2, 'subsequent updates retain the committed view');
  stream.receive({ opcode: 66, revision: 2, omitted: [], diffTooLarge: false, error: null });
  assert.equal(published[2].files[0], committedFile, 'unchanged body retains object identity');
});
