#!/usr/bin/env node
// Paseo 0.14.0 local compatibility patch for slow mobile TLS connections.
// Publish new content-addressed assets; retain originals for rollback.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const root = path.join(__dirname, 'runtime/lib/node_modules/@getpaseo/cli/node_modules/@getpaseo/server/dist/server/web-ui');
const indexPath = path.join(root, 'index.html');
const html = fs.readFileSync(indexPath, 'utf8');
function publishHtml(next) {
  next = next.replace(/<script id="paseo-local-diagnostics">[\s\S]*?<\/script>\n?/g, '');
  if (process.env.PASEO_DIAGNOSTICS === '1') {
    const diagnostics = fs.readFileSync(path.join(__dirname, 'browser-diagnostics.js'), 'utf8');
    next = next.replace('<head>', '<head>\n<script id="paseo-local-diagnostics">'+diagnostics+'</script>');
  }
  fs.writeFileSync(indexPath, next);
}
const match = html.match(/src="(\/_expo\/static\/js\/web\/index-[a-f0-9]+\.js)"/);
if (!match) throw new Error('Cannot find Paseo entry asset; review upstream build.');
let patched = fs.readFileSync(path.join(root, match[1]), 'utf8');
function replaceOnce(before, after) {
  if (patched.includes(after)) return;
  if (patched.split(before).length !== 2) throw new Error('Upstream implementation changed; review patch: '+before);
  patched = patched.replace(before, after);
}
const start = patched.indexOf('async bootstrapInitialConnectionHint(');
const end = patched.indexOf('}reconcileServerId(', start);
if (start < 0 || end < 0) throw new Error('Upstream bootstrap structure changed; review patch.');
const method = patched.slice(start, end);
if (!method.includes('timeoutMs:20000')) {
  if (method.split('timeoutMs:ge').length !== 2 || !patched.includes('ge=2500,fe="__PASEO_INITIAL_DAEMON_CONNECTION__"')) {
    throw new Error('Upstream initial timeout changed; review patch.');
  }
  patched = patched.slice(0, start) + method.replace('timeoutMs:ge', 'timeoutMs:20000') + patched.slice(end);
}
// Registry entries use this ordinary connection probe after refresh: previously 6s.
replaceOnce('function C(t,o){return o?.timeoutMs?o.timeoutMs:"relay"===t.type?1e4:"remoteSsh"===t.type?15e3:6e3}',
 'function C(t,o){return o?.timeoutMs?o.timeoutMs:"relay"===t.type?1e4:"remoteSsh"===t.type?15e3:"directTcp"===t.type&&t.useTls?20000:6e3}');
// Align the underlying client timeout (normally 15s) with the TLS probe's budget.
replaceOnce('if("directTcp"===t.type)return{...h,url:(0,s.buildDaemonWebSocketUrl)(t.endpoint,{useTls:t.useTls??!1})}',
 'if("directTcp"===t.type)return{...h,...t.useTls?{connectTimeoutMs:n?.timeoutMs??20000}:{},url:(0,s.buildDaemonWebSocketUrl)(t.endpoint,{useTls:t.useTls??!1})}');
const hash = crypto.createHash('sha256').update(patched).digest('hex').slice(0, 32);
const newUrl = '/_expo/static/js/web/index-' + hash + '.js';
const target = path.join(root, newUrl);
if (fs.existsSync(target) && fs.readFileSync(target, 'utf8') !== patched) throw new Error('Asset hash collision');
fs.writeFileSync(target, patched);
publishHtml(html.replaceAll(match[1], newUrl));
console.log('Initial discovery and subsequent TLS probes patched to 20s.');
console.log('Asset: '+newUrl);
