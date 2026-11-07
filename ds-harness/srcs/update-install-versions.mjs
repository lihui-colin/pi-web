#!/usr/bin/env node
// Resolve upstream versions; ordinary installs continue using the saved pins.
import fs from 'node:fs/promises';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {pathToFileURL} from 'node:url';
import {dirname, join} from 'node:path';
const exec = promisify(execFile);

export async function resolveVersions(current, {npm, github}) {
  const next = structuredClone(current);
  next.dsh = (await npm('@deepseek-ai/dsh@latest')).version;
  next.pnpm = (await npm('pnpm@latest')).version;
  await Promise.all(Object.entries(next.plugins).map(async ([name, pin]) => {
    if (name.startsWith('@local/')) return;
    if (pin.source?.startsWith('github:')) {
      const repo = pin.source.slice(7).split('#')[0];
      const value = await github(repo);
      pin.version = value.version;
      pin.source = `github:${repo}#${value.commit}`;
      return;
    }
    // npm's Codex latest tag can lag behind DSH's current release channel.
    const meta = await npm(`${name}@${name === '@deepseek-ai/dsh-subagent-codex' ? next.dsh : 'latest'}`);
    pin.version = meta.version;
    if (pin.source?.startsWith('https:')) pin.source = meta.dist.tarball;
  }));
  for (const value of [next.dsh, next.pnpm, ...Object.values(next.plugins).map(pin => pin.version)]) {
    if (!/^\d+\.\d+\.\d+(?:-[\w.-]+)?$/.test(value)) throw new Error(`Invalid resolved version: ${value}`);
  }
  return next;
}

async function run(file) {
  const before = await fs.readFile(file, 'utf8');
  const current = JSON.parse(before);
  const next = await resolveVersions(current, {
    npm: async spec => JSON.parse((await exec('npm', ['view', spec, '--json'], {timeout: 90000, maxBuffer: 8 * 1024 * 1024})).stdout),
    github: async repo => {
      if (!/^[\w.-]+\/[\w.-]+$/.test(repo)) throw new Error(`Unsupported GitHub source: ${repo}`);
      const result = await exec('git', ['ls-remote', `https://github.com/${repo}.git`, 'HEAD'], {timeout: 90000});
      const commit = result.stdout.trim().split(/\s+/)[0];
      if (!/^[a-f0-9]{40}$/.test(commit)) throw new Error(`Invalid GitHub HEAD: ${repo}`);
      const response = await exec('curl', ['-fsSL', '--connect-timeout', '15', '--max-time', '90',
        `https://api.github.com/repos/${repo}/contents/package.json?ref=${commit}`], {timeout: 95000});
      const metadata = JSON.parse(response.stdout);
      return {commit, version: JSON.parse(Buffer.from(metadata.content, 'base64').toString()).version};
    },
  });
  const rows = [['DSH', current.dsh, next.dsh], ['pnpm', current.pnpm, next.pnpm],
    ...Object.entries(next.plugins).map(([name, pin]) => [name,
      current.plugins[name].source || current.plugins[name].version, pin.source || pin.version])];
  for (const [name, oldValue, value] of rows) console.log(`${name}: ${oldValue === value ? `${value} (unchanged)` : `${oldValue} -> ${value}`}`);
  if (JSON.stringify(current) === JSON.stringify(next)) return;
  // All lookups must succeed before publishing; retain a recoverable original.
  if (await fs.readFile(file, 'utf8') !== before) throw new Error('Version file changed during resolution');
  const backups = join(dirname(file), '../data/version-backups');
  await fs.mkdir(backups, {recursive: true});
  await fs.copyFile(file, join(backups, `install-versions.${Date.now()}.json`));
  const temporary = `${file}.${process.pid}.tmp`;
  try {
    await fs.writeFile(temporary, `${JSON.stringify(next, null, 2)}\n`);
    await fs.rename(temporary, file);
  } finally { await fs.rm(temporary, {force: true}); }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  run(process.argv[2]).catch(error => { console.error(error.message); process.exitCode = 1; });
}
