import { spawnSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, readFileSync, existsSync, symlinkSync, readlinkSync, statSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const helper = resolve('scripts/install-system-deps.sh');
const quote = value => `'${value.replaceAll("'", "'\\''")}'`;
function run(code, env = {}) {
  return spawnSync('bash', ['-c', `source ${quote(helper)}\n${code}`], { encoding: 'utf8', env: { ...process.env, ...env } });
}

for (const original of ['absent', 'file', 'symlink']) {
  for (const failure of ['', 'update', 'install']) {
    test(`package install restores ${original} service policy after ${failure || 'success'}`, () => {
      const root = mkdtempSync(join(tmpdir(), 'pi-web dependencies '));
      try {
        const policy = join(root, 'policy-rc.d');
        const target = join(root, 'original-policy');
        const content = '#!/bin/sh\nexit 0\n';
        if (original === 'file') writeFileSync(policy, content, { mode: 0o751 });
        if (original === 'symlink') { writeFileSync(target, content); symlinkSync(target, policy); }
        const log = join(root, 'calls');
        const result = run(`
apt-get() {
  printf '%s|%s|%s\\n' "$*" "$DEBIAN_FRONTEND" "$NEEDRESTART_MODE" >> "$TEST_LOG"
  if bash "$TEST_POLICY"; then return 99; else [[ "$?" == 101 ]] || return 98; fi
  [[ "$1" != "$TEST_FAILURE" ]] || return 17
}
install_debian_packages ${quote(policy)} ${quote(join(root, 'lock'))} nginx openssl
`, { TEST_LOG: log, TEST_POLICY: policy, TEST_FAILURE: failure });
        assert.equal(result.status, failure ? 17 : 0, result.stderr);
        const calls = readFileSync(log, 'utf8');
        assert.match(calls, /update\|noninteractive\|l/);
        if (failure !== 'update') assert.match(calls, /install -y --no-install-recommends --no-upgrade -o Dpkg::Options::=--force-confold nginx openssl\|noninteractive\|l/);
        if (original === 'absent') assert.equal(existsSync(policy), false);
        else assert.equal(readFileSync(policy, 'utf8'), content);
        if (original === 'file') assert.equal(statSync(policy).mode & 0o777, 0o751);
        if (original === 'symlink') assert.equal(readlinkSync(policy), target);
      } finally { rmSync(root, { recursive: true, force: true }); }
    });
  }
}

test('check and dry-run report missing dependencies without privilege or package calls', () => {
  const code = `missing_system_packages() { printf 'nginx\\nopenssl\\n'; }
sudo() { exit 99; }
apt-get() { exit 98; }
`;
  const checked = run(`${code}system_deps_main --check`);
  assert.equal(checked.status, 1);
  assert.match(checked.stdout, /nginx openssl/);
  assert.equal(run(`${code}system_deps_main --dry-run`).status, 0);
  assert.equal(run(`missing_system_packages() { :; }; sudo() { exit 99; }; system_deps_main`).status, 0);
});

test('rejects arbitrary package arguments before acquiring locks or changing policy', () => {
  const result = run('install_debian_packages /does-not-exist/policy /does-not-exist/lock --allow-unauthenticated');
  assert.equal(result.status, 2);
  assert.match(result.stderr, /Unsupported package/);
});
