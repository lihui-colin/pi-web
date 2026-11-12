#!/usr/bin/env node
// Paseo 0.16.0-beta.2 Web UX compatibility patch.
// Publish new content-addressed assets; retain originals for rollback.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const zlib = require('node:zlib');
const baseline = require('./patch-web-ui.baseline.json');
const { serverRoot, checkCompatibility, replaceOnce: replaceText, patchModule } = require('../patch-utils.cjs');

function patchHoverCards(source) {
  const replacements = [
    ['const t=()=>{P(),v(!1)},n=t=>',
      'const t=()=>{P(),v(!1)},paseoPointerDown=e=>{("mouse"===e.pointerType&&b.current?.contains(e.target))||t()},n=t=>'],
    ['onPointerEnter:s.openNow,onPointerLeave:s.scheduleClose',
      'onPointerEnter:e=>{"mouse"===e.pointerType&&s.openNow()},onPointerLeave:s.scheduleClose'],
    ['S.current=n.matches(":focus-visible"),e.contains(n)?T():b.current?.contains(n)&&P()',
      'S.current=n.matches(":focus-visible"),S.current&&(e.contains(n)?T():b.current?.contains(n)&&P())'],
    ['document.addEventListener("focusin",n),document.addEventListener("focusout",o)',
      'document.addEventListener("pointerdown",paseoPointerDown),document.addEventListener("focusin",n),document.addEventListener("focusout",o)'],
    ['document.removeEventListener("focusin",n),document.removeEventListener("focusout",o)',
      'document.removeEventListener("pointerdown",paseoPointerDown),document.removeEventListener("focusin",n),document.removeEventListener("focusout",o)'],
  ];
  return patchModule(source, '_e.HoverCard=function', module =>
    replacements.reduce((text, [before, after]) => replaceText(text, before, after, 'HoverCard'), module));
}

function main() {
  const installed = JSON.parse(fs.readFileSync(path.join(serverRoot, 'package.json'), 'utf8'));
  checkCompatibility(installed);
  const root = path.join(serverRoot, 'dist/server/web-ui');
  const indexPath = path.join(root, 'index.html');
  const html = fs.readFileSync(indexPath, 'utf8');
  const entries = [...html.matchAll(/src="(\/_expo\/static\/js\/web\/index-[a-f0-9]+\.js)"/g)];
  if (entries.length !== 1) throw new Error('Cannot find unique Paseo entry asset; review upstream build.');
  const match = entries[0];
  // Rebuild from the official asset so removed patches disappear on republish.
  let patched = fs.readFileSync(path.join(root, baseline.webEntry), 'utf8');
  function replaceOnce(before, after) { patched = replaceText(patched, before, after); }
  const start = patched.indexOf('async bootstrapInitialConnectionHint(');
  const end = patched.indexOf('}reconcileServerId(', start);
  const nextModule = patched.indexOf('\n__d(', start);
  if (start < 0 || end < 0 || start !== patched.lastIndexOf('async bootstrapInitialConnectionHint(') ||
      (nextModule >= 0 && end >= nextModule)) throw new Error('Upstream bootstrap structure changed; review patch.');
  const method = patched.slice(start, end);
  if (!method.includes('timeoutMs:20000') && !patched.includes('fe=2500,Ce="__PASEO_INITIAL_DAEMON_CONNECTION__"')) {
    throw new Error('Upstream initial timeout changed; review patch.');
  }
  patched = patched.slice(0, start) + replaceText(method, 'timeoutMs:fe', 'timeoutMs:20000', 'initial timeout') + patched.slice(end);
  // Registry entries use this ordinary connection probe after refresh: previously 6s.
  replaceOnce('function k(t,o){return o?.timeoutMs?o.timeoutMs:"relay"===t.type?1e4:"remoteSsh"===t.type?15e3:6e3}',
   'function k(t,o){return o?.timeoutMs?o.timeoutMs:"relay"===t.type?1e4:"remoteSsh"===t.type?15e3:"directTcp"===t.type&&t.useTls?20000:6e3}');
  // Align the underlying client timeout (normally 15s) with the TLS probe's budget.
  replaceOnce('if("directTcp"===t.type)return{...b,url:(0,l.buildDaemonWebSocketUrl)(t.endpoint,{useTls:t.useTls??!1})}',
   'if("directTcp"===t.type)return{...b,...t.useTls?{connectTimeoutMs:s.timeoutMs??20000}:{},url:(0,l.buildDaemonWebSocketUrl)(t.endpoint,{useTls:t.useTls??!1})}');
  // Only Electron owns a custom context menu; Web must allow the browser default.
  replaceOnce('oe=(0,n.useCallback)(n=>{n.preventDefault(),te()},[te])',
    'oe=(0,n.useCallback)(n=>{typeof window.paseoDesktop?.menu?.showContextMenu==="function"&&(n.preventDefault(),te())},[te])');
  // Preserve upstream layout/animation; arbitrate only left-sidebar touch pans.
  if (!patched.includes('useOpenAgentListGesture=function') || !patched.includes('"compact-shell"')) {
    throw new Error('Upstream mobile sidebar structure changed; review swipe patch.');
  }
  const swipe = fs.readFileSync(path.join(__dirname, 'mobile-sidebar-swipe.js'), 'utf8');
  patched = patchHoverCards(patched);
  // Keep the official binary diff stream and its connection ownership unchanged.
  patched = swipe + '\n' + patched;
  // Validate syntax before publishing either the bundle or HTML.
  new (require('node:vm').Script)(patched);
  const hash = crypto.createHash('sha256').update(patched).digest('hex').slice(0, 32);
  const newUrl = '/_expo/static/js/web/index-' + hash + '.js';
  const target = path.join(root, newUrl);
  if (fs.existsSync(target) && fs.readFileSync(target, 'utf8') !== patched) throw new Error('Asset hash collision');
  const source = Buffer.from(patched);
  fs.writeFileSync(target, source);
  fs.writeFileSync(target + '.br', zlib.brotliCompressSync(source, {
    params: { [zlib.constants.BROTLI_PARAM_QUALITY]: 6 }
  }));
  fs.writeFileSync(target + '.gz', zlib.gzipSync(source));
  fs.writeFileSync(indexPath, html.replaceAll(match[1], newUrl));
  console.log('Web UI patched:', newUrl);
}

if (require.main === module) main();
module.exports = { checkCompatibility, patchHoverCards };
