const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'paseo-node-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  fs.mkdirSync(path.join(root, 'srcs'));
  fs.copyFileSync(path.join(__dirname, '../srcs/node-runtime.sh'), path.join(root, 'srcs/node-runtime.sh'));
  const trace = path.join(root, 'executed');
  const tools = path.join(root, 'tools');
  fs.mkdirSync(tools);
  fs.symlinkSync('/usr/bin/readlink', path.join(tools, 'readlink'));
  const environment = { ...process.env, HOME: root, NVM_DIR: path.join(root, 'nvm'), TRACE: trace };
  for (const key of Object.keys(environment)) {
    if (key.startsWith('CONDA_PREFIX') || key === 'PASEO_NODE_BIN') delete environment[key];
  }
  return {
    root,
    pair(relative, version = 'v24.1.0', npmStatus = 0) {
      const bin = path.join(root, relative);
      fs.mkdirSync(bin, { recursive: true });
      for (const name of ['node', 'npm']) {
        fs.writeFileSync(path.join(bin, name), `#!/bin/bash\nprintf '%s\\n' "$0" >> "$TRACE"\nprintf '%s\\n' '${name === 'node' ? version : '10.0.0'}'\nexit ${name === 'node' ? 0 : npmStatus}\n`, { mode: 0o755 });
      }
      return bin;
    },
    run(entries = [], extra = {}) {
      return spawnSync('/bin/bash', ['-c', 'set -Eeuo pipefail; source "$1"; if paseo_select_node; then printf "%s\\n" "$PATH"; else exit 1; fi', 'test', path.join(root, 'srcs/node-runtime.sh')], {
        cwd: root, encoding: 'utf8', timeout: 5000,
        env: { ...environment, PATH: [...entries, tools].join(':'), ...extra },
      });
    },
    calls() { return fs.existsSync(trace) ? fs.readFileSync(trace, 'utf8').trim().split('\n') : []; },
  };
}

function selected(result, bin) {
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout.trim().split(':')[0], bin);
}

test('explicit override wins over private runtime and PATH', t => {
  const f = fixture(t), override = f.pair('override');
  f.pair('runtime/node/bin');
  const other = f.pair('path');
  selected(f.run([other], { PASEO_NODE_BIN: override }), override);
  assert.deepEqual(f.calls(), [path.join(override, 'node'), path.join(override, 'npm')]);
});

test('empty and invalid explicit overrides fail without fallback', t => {
  for (const value of ['', '/missing-paseo-node-override']) {
    const f = fixture(t);
    const fallback = f.pair('runtime/node/bin');
    const result = f.run([fallback], { PASEO_NODE_BIN: value });
    assert.equal(result.status, 1);
    assert.match(result.stderr, /Invalid PASEO_NODE_BIN/);
    assert.deepEqual(f.calls(), []);
  }
});

test('private runtime wins over PATH and installed NVM', t => {
  const f = fixture(t), runtime = f.pair('runtime/node/bin');
  const other = f.pair('path');
  f.pair('nvm/versions/node/v24.2.0/bin');
  selected(f.run([other]), runtime);
  assert.deepEqual(f.calls(), [path.join(runtime, 'node'), path.join(runtime, 'npm')]);
});

test('PATH preserves empty current-directory entries and paths containing spaces', t => {
  const f = fixture(t), current = f.pair('.'), spaced = f.pair('node with spaces/bin');
  selected(f.run(['', spaced]), current);
  selected(f.run([spaced, '']), spaced);
});

test('PATH skips incomplete pairs, old Node and broken npm before selecting next candidate', t => {
  const f = fixture(t), incomplete = f.pair('incomplete'), old = f.pair('old', 'v20.9.0');
  fs.unlinkSync(path.join(incomplete, 'npm'));
  const broken = f.pair('broken', 'v24.1.0', 1), good = f.pair('good');
  selected(f.run([incomplete, old, broken, good]), good);
  assert.ok(!f.calls().includes(path.join(incomplete, 'node')));
  assert.ok(!f.calls().includes(path.join(old, 'npm')));
});

test('NVM provides a fallback when PATH candidates are unusable', t => {
  const f = fixture(t), old = f.pair('old', 'v18.0.0'), nvm = f.pair('nvm/versions/node/v24.0.0/bin');
  selected(f.run([old]), nvm);
});

test('Conda names, active prefixes, metadata and executable symlinks are rejected before execution', t => {
  for (const kind of ['name', 'prefix', 'metadata', 'symlink']) {
    const f = fixture(t);
    const conda = f.pair(kind === 'name' ? 'miniconda3/bin' : 'custom-env/bin');
    let candidate = conda;
    const extra = {};
    if (kind === 'prefix') extra.CONDA_PREFIX_1 = path.dirname(conda);
    if (kind === 'metadata' || kind === 'symlink') fs.mkdirSync(path.join(path.dirname(conda), 'conda-meta'));
    if (kind === 'symlink') {
      candidate = path.join(f.root, 'linked/bin');
      fs.mkdirSync(candidate, { recursive: true });
      for (const name of ['node', 'npm']) fs.symlinkSync(path.join(conda, name), path.join(candidate, name));
    }
    const good = f.pair('good');
    selected(f.run([candidate, good], extra), good);
    assert.deepEqual(f.calls(), [path.join(good, 'node'), path.join(good, 'npm')]);
  }
});

test('selection fails when no compatible complete pair exists', t => {
  const f = fixture(t), old = f.pair('old', 'v21.0.0');
  const result = f.run([old]);
  assert.equal(result.status, 1);
  assert.match(result.stderr, /No working Node.js >=22 and npm pair/);
});
