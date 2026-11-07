import test from 'node:test';
import assert from 'node:assert/strict';
import {resolveVersions} from '../srcs/update-install-versions.mjs';

const current = {
  dsh: '0.2.1', pnpm: '12.15.0', plugins: {
    '@deepseek-ai/dsh-subagent-codex': {version: '0.2.1'},
    'ds-bot': {version: '0.2.7'},
    mobile: {version: '3.3.1', source: 'github:owner/mobile#old'},
    composer: {version: '1.22.0', source: 'https://example.test/old.tgz'},
    '@local/quota': {version: '1.0.0', source: 'link:../../srcs/quota'},
  },
};

test('upgrade resolves upstream, aligns Codex, pins Git HEAD and preserves local links', async () => {
  const calls = [];
  const next = await resolveVersions(current, {
    npm: async spec => {
      calls.push(spec);
      return {version: spec.startsWith('pnpm') ? '12.18.0' : spec.startsWith('ds-bot') ? '0.3.1' :
        spec.startsWith('composer') ? '1.23.0' : '0.2.2-rc.1', dist: {tarball: 'https://example.test/1.23.0.tgz'}};
    },
    github: async repo => {
      assert.equal(repo, 'owner/mobile');
      return {version: '3.3.2', commit: 'a'.repeat(40)};
    },
  });
  assert.equal(next.dsh, '0.2.2-rc.1');
  assert.ok(calls.includes('@deepseek-ai/dsh-subagent-codex@0.2.2-rc.1'));
  assert.ok(!calls.includes('@deepseek-ai/dsh-subagent-codex@latest'));
  assert.equal(next.plugins.mobile.source, `github:owner/mobile#${'a'.repeat(40)}`);
  assert.equal(next.plugins.composer.source, 'https://example.test/1.23.0.tgz');
  assert.deepEqual(next.plugins['@local/quota'], current.plugins['@local/quota']);
  assert.equal(current.plugins['ds-bot'].version, '0.2.7');
});

test('lookup failure and invalid versions fail without changing saved input', async () => {
  const before = JSON.stringify(current);
  for (const npm of [async () => { throw new Error('registry unavailable'); }, async () => ({version: 'latest'})]) {
    await assert.rejects(resolveVersions(current, {npm, github: async () => ({version: '3.3.2', commit: 'a'.repeat(40)})}));
    assert.equal(JSON.stringify(current), before);
  }
});
