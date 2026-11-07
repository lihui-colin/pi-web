#!/usr/bin/env node
// Paseo 0.14.0 local compatibility patch for slow mobile TLS connections.
// Publish new content-addressed assets; retain originals for rollback.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const zlib = require('node:zlib');
const baseline = require('./patch-web-ui.baseline.json');

function checkCompatibility(installed, warn = console.warn) {
  if (installed.version !== baseline.version) {
    warn(`[WARN] Web UI 补丁版本不匹配：预期 ${baseline.package}@${baseline.version}，当前 ${installed.version ?? '未知'}；补丁基准 commit ${baseline.commit}。请重新核查补丁。`);
  }
  if (!installed.gitHead) {
    warn(`[WARN] 已安装的 ${baseline.package} 未提供 gitHead，无法核对 commit ID；补丁基准为 ${baseline.tag} (${baseline.commit})。将继续检查资源结构。`);
  } else if (installed.gitHead !== baseline.commit) {
    warn(`[WARN] Web UI 补丁 commit 不匹配：预期 ${baseline.commit}，当前 ${installed.gitHead}。请重新核查补丁；将继续检查资源结构。`);
  }
}

function patchHoverCards(source) {
  const replacements = [
    ['onPointerEnter:s.openNow,onPointerLeave:s.scheduleClose',
      'onPointerEnter:e=>{"mouse"===e.pointerType&&s.openNow()},onPointerLeave:s.scheduleClose'],
    ['_.current=n.matches(":focus-visible"),e.contains(n)?I():f.current?.contains(n)&&L()',
      '_.current=n.matches(":focus-visible"),_.current&&(e.contains(n)?I():f.current?.contains(n)&&L())'],
    ['document.addEventListener("focusin",n),document.addEventListener("focusout",o)',
      'document.addEventListener("pointerdown",t),document.addEventListener("focusin",n),document.addEventListener("focusout",o)'],
    ['document.removeEventListener("focusin",n),document.removeEventListener("focusout",o)',
      'document.removeEventListener("pointerdown",t),document.removeEventListener("focusin",n),document.removeEventListener("focusout",o)'],
  ];
  // Limit these minified anchors to the upstream HoverCard module.
  const start = source.lastIndexOf('\n__d(', source.indexOf('_e.HoverCard=function'));
  const end = source.indexOf('\n__d(', start + 1);
  if (start < 0 || end < 0) throw new Error('Upstream HoverCard module changed; review patch.');
  let module = source.slice(start, end);
  for (const [before, after] of replacements) {
    if (module.split(after).length === 2) continue;
    if (module.split(before).length !== 2) throw new Error('Upstream HoverCard structure changed; review patch: ' + before);
    module = module.replace(before, after);
  }
  return source.slice(0, start) + module + source.slice(end);
}

function main() {
  const serverRoot = path.join(__dirname, '../../../runtime/lib/node_modules/@getpaseo/cli/node_modules/@getpaseo/server');
  const installed = JSON.parse(fs.readFileSync(path.join(serverRoot, 'package.json'), 'utf8'));
  checkCompatibility(installed);
  const root = path.join(serverRoot, 'dist/server/web-ui');
  const indexPath = path.join(root, 'index.html');
  const html = fs.readFileSync(indexPath, 'utf8');
  const match = html.match(/src="(\/_expo\/static\/js\/web\/index-[a-f0-9]+\.js)"/);
  if (!match) throw new Error('Cannot find Paseo entry asset; review upstream build.');
  let patched = fs.readFileSync(path.join(root, match[1]), 'utf8');
  function replaceOnce(before, after) {
    if (patched.includes(after)) return;
    if (!patched.includes(before) || patched.indexOf(before) !== patched.lastIndexOf(before)) throw new Error('Upstream implementation changed; review patch: '+before);
    patched = patched.replace(before, after);
  }
  const start = patched.indexOf('async bootstrapInitialConnectionHint(');
  const end = patched.indexOf('}reconcileServerId(', start);
  if (start < 0 || end < 0) throw new Error('Upstream bootstrap structure changed; review patch.');
  const method = patched.slice(start, end);
  if (!method.includes('timeoutMs:20000')) {
    if (method.indexOf('timeoutMs:ge') < 0 || method.indexOf('timeoutMs:ge') !== method.lastIndexOf('timeoutMs:ge') || !patched.includes('ge=2500,fe="__PASEO_INITIAL_DAEMON_CONNECTION__"')) {
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
  // Touch devices do not reliably emit hover events; keep user-message actions visible.
  replaceOnce('re=!A&&ie&&(N||T.isNative||U)',
    're=!A&&ie&&(N||T.isNative||U||("undefined"!=typeof window&&"function"==typeof window.matchMedia&&window.matchMedia("(hover: none)").matches))');
  // Web/remote hosts reuse the daemon's listDirectory API. Electron keeps its native picker.
  replaceOnce('canBrowse:t&&(0,C.getIsElectronRuntime)()&&Z===e.serverId',
    'canBrowse:t&&(_.isWeb&&!(0,C.getIsElectronRuntime)()||(0,C.getIsElectronRuntime)()&&Z===e.serverId)');
  replaceOnce('if(me&&ke&&!He.current){He.current=!0;',
    'if(me&&(ke||_.isWeb)&&!He.current){He.current=!0;');
  replaceOnce('const e=await(0,T.pickDirectory)();',
    'const e=await(_.isWeb&&!(0,C.getIsElectronRuntime)()?globalThis.__paseoPickServerDirectory(je,{initialPath:xe[0],hostLabel:we?.label}):(0,T.pickDirectory)());');
  replaceOnce('},[me,ke,Ge]),Ve=', '},[me,ke,Ge,je,xe,we]),Ve=');
  replaceOnce('description:"Choose or create a directory in Finder"', 'description:`Choose a directory on ${t.label}`');
  // Remove the older local clipboard menu hook when upgrading an already patched bundle.
  const clipboardHook = '(0,n.useEffect)(()=>globalThis.__paseoMountTerminalClipboard(D.current,A.current),[h]);';
  if (patched.indexOf(clipboardHook) !== patched.lastIndexOf(clipboardHook)) throw new Error('Unexpected duplicate clipboard hook');
  patched = patched.replace(clipboardHook, '');
  // Only Electron owns a custom context menu; Web must allow the browser default.
  replaceOnce('oe=(0,n.useCallback)(n=>{n.preventDefault(),te()},[te])',
    'oe=(0,n.useCallback)(n=>{typeof window.paseoDesktop?.menu?.showContextMenu==="function"&&(n.preventDefault(),te())},[te])');
  const pickerStart = '/* PASEO_DIRECTORY_PICKER_START */';
  const pickerEnd = '/* PASEO_DIRECTORY_PICKER_END */';
  if (patched.startsWith(pickerStart)) {
    const markerEnd = patched.indexOf(pickerEnd);
    if (markerEnd < 0) throw new Error('Incomplete directory picker patch');
    patched = patched.slice(markerEnd + pickerEnd.length).replace(/^\n/, '');
  }
  const picker = fs.readFileSync(path.join(__dirname, 'server-directory-picker.js'), 'utf8');
  // Preserve upstream layout/animation; arbitrate only left-sidebar touch pans.
  if (!patched.includes('useOpenAgentListGesture=function') || !patched.includes('"compact-shell"')) {
    throw new Error('Upstream mobile sidebar structure changed; review swipe patch.');
  }
  const swipe = fs.readFileSync(path.join(__dirname, 'mobile-sidebar-swipe.js'), 'utf8');
  patched = patchHoverCards(patched);
  patched = pickerStart + '\n' + picker + '\n' + swipe + '\n' + pickerEnd + '\n' + patched;
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
  // Remove diagnostics injected by older local patches when publishing the HTML.
  const nextHtml = html.replace(/<script id="paseo-local-diagnostics">[\s\S]*?<\/script>\n?/g, '');
  fs.writeFileSync(indexPath, nextHtml.replaceAll(match[1], newUrl));
  console.log('Initial discovery and subsequent TLS probes patched to 20s.');
  console.log('Mobile Web sidebar edge swipe preserves upstream gesture handling.');
  console.log('Asset: '+newUrl);
}

if (require.main === module) main();
module.exports = { checkCompatibility, patchHoverCards };
