#!/usr/bin/env bash
set -euo pipefail
component_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
# Local plugin with no dependencies: link it without reinstalling the running profile.
node --input-type=module - "$component_dir" <<'NODE'
import fs from 'node:fs';
import path from 'node:path';
const root = process.argv[2];
const profile = path.join(root, 'data/.dsh/profiles/web');
const file = path.join(profile, 'package.json');
const pkg = JSON.parse(fs.readFileSync(file, 'utf8'));
const name = '@local/dsh-codex-quota';
const source = path.join(root, 'srcs/plugins/codex-quota');
const target = path.join(profile, 'node_modules', name);
const bundles = pkg.dsh?.profile?.bundles;
if (!Array.isArray(bundles)) throw new Error('web profile bundles must be an array');
fs.mkdirSync(path.dirname(target), {recursive:true});
let existing;
try { existing = fs.lstatSync(target); } catch (error) { if (error.code !== 'ENOENT') throw error; }
if (existing) {
  if (fs.realpathSync(target) !== fs.realpathSync(source)) throw new Error('Plugin path already occupied');
} else fs.symlinkSync(path.relative(path.dirname(target), source), target, 'dir');
pkg.dependencies ??= {};
pkg.dependencies[name] = 'link:' + path.relative(profile, source);
if (!bundles.includes(name)) bundles.push(name);
const temporary = file + '.codex-quota.tmp';
fs.writeFileSync(temporary, JSON.stringify(pkg, null, 2) + '\n', {mode:fs.statSync(file).mode & 0o777});
fs.renameSync(temporary, file);
console.log('Codex 额度插件已安装并启用；下次 DSH 加载 profile 时生效。');
NODE
