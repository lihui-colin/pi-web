// paseo-dsh 0.2.17: catalog probes must await the same loader barrier as initialize.
// Upstream checked: liuxing7954/paseo-dsh@c642c604aeb5b409a6237ca3ef54fdb82801677d.
const fs = require('node:fs');
const path = require('node:path');
const before = "if (method === 'initialize') await ctx.get('loader')?.await();";
const after = "if (method === 'initialize' || method === 'paseo/catalog') await ctx.get('loader')?.await();";
function patchSource(source) {
  if (source.includes(after)) return source;
  if (source.split(before).length !== 2) throw new Error('Unsupported paseo-dsh bridge structure; refusing to patch');
  return source.replace(before, after);
}
function patchAssets(source) {
  const pattern = /("lib\/index\.js":\s*")([A-Za-z0-9+/=]+)(")/g;
  const matches = [...source.matchAll(pattern)];
  if (matches.length !== 1) throw new Error('Expected exactly one embedded bridge entry');
  const [match] = matches;
  const decoded = Buffer.from(match[2], 'base64').toString('utf8');
  const patched = patchSource(decoded);
  if (patched === decoded) return source;
  const entry = match[1] + Buffer.from(patched).toString('base64') + match[3];
  return source.slice(0, match.index) + entry + source.slice(match.index + match[0].length);
}
function patchHome(source, home) {
  if (!path.isAbsolute(home)) throw new Error('DSH home must be an absolute path');
  const anchor = 'export default function contribute(server: PluginServerContext) {';
  const marker = /\n  \/\/ PASEO_DSH_HOME\n  process\.env\.DSH_HOME \?\?= [^\n]+;\n/;
  source = source.replace(marker, '\n');
  if (source.split(anchor).length !== 2) throw new Error('Unsupported DSH plugin entry');
  return source.replace(anchor + '\n', anchor + '\n  // PASEO_DSH_HOME\n  process.env.DSH_HOME ??= ' + JSON.stringify(home) + ';\n');
}
function main() {
  const plugins = path.join(__dirname, '../../../../data/.paseo/plugins/dsh-paseo');
  const dshHome = process.env.DSH_HOME ?? path.resolve(__dirname, '../../../../../ds-harness/data/.dsh');
  if (typeof dshHome !== 'string' || !path.isAbsolute(dshHome)) throw new Error('Invalid configured DSH home');
  const targets = [];
  if (fs.existsSync(plugins)) for (const version of fs.readdirSync(plugins)) {
    const asset = path.join(plugins, version, 'node_modules/paseo-dsh/server/bridge-assets.ts');
    if (fs.existsSync(asset)) targets.push([asset, patchAssets]);
    const entry = path.join(plugins, version, 'node_modules/paseo-dsh/index.server.ts');
    if (fs.existsSync(entry)) targets.push([entry, source => patchHome(source, dshHome)]);
  }
  const bridge = path.join(dshHome, 'profiles', process.env.DSH_PASEO_PROFILE ?? 'paseo', 'node_modules/dsh-paseo-bridge/lib/index.js');
  if (fs.existsSync(bridge)) targets.push([bridge, patchSource]);
  // Validate every source before changing any of them.
  const edits = targets.map(([file, patch]) => { const old = fs.readFileSync(file, 'utf8'); return { file, old, next: patch(old) }; });
  for (const { file, old, next } of edits) if (old !== next) { fs.writeFileSync(file, next); console.log('Patched:', file); }
  console.log(`DSH catalog readiness: ${edits.length} assets checked; no service restarted.`);
}
module.exports = { patchSource, patchAssets, patchHome };
if (require.main === module) main();
