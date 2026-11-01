// paseo-dsh 0.2.17: catalog probes must await the same loader barrier as initialize.
// Upstream checked: liuxing7954/paseo-dsh@c642c604aeb5b409a6237ca3ef54fdb82801677d.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
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
  return source.replace(pattern, (_, prefix, data, suffix) => prefix + Buffer.from(patchSource(Buffer.from(data, 'base64').toString('utf8'))).toString('base64') + suffix);
}
function main() {
  const plugins = path.join(__dirname, 'data/.paseo/plugins/dsh-paseo');
  const dshHome = process.env.DSH_HOME ?? path.join(os.homedir(), '.dsh');
  const targets = [];
  if (fs.existsSync(plugins)) for (const version of fs.readdirSync(plugins)) {
    const asset = path.join(plugins, version, 'node_modules/paseo-dsh/server/bridge-assets.ts');
    if (fs.existsSync(asset)) targets.push([asset, patchAssets]);
  }
  const bridge = path.join(dshHome, 'profiles', process.env.DSH_PASEO_PROFILE ?? 'paseo', 'node_modules/dsh-paseo-bridge/lib/index.js');
  if (fs.existsSync(bridge)) targets.push([bridge, patchSource]);
  // Validate every source before changing any of them.
  const edits = targets.map(([file, patch]) => { const old = fs.readFileSync(file, 'utf8'); return { file, old, next: patch(old) }; });
  for (const { file, old, next } of edits) if (old !== next) { fs.writeFileSync(file, next); console.log('Patched:', file); }
  console.log(`DSH catalog readiness: ${edits.length} assets checked; no service restarted.`);
}
module.exports = { patchSource, patchAssets };
if (require.main === module) main();
