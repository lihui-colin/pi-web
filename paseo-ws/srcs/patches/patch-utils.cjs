'use strict';
const path = require('node:path');
const baseline = require('./service/patch-web-ui.baseline.json');
const serverRoot = path.join(process.env.PASEO_RUNTIME_PREFIX || path.join(__dirname, '../../runtime'), 'lib/node_modules/@getpaseo/cli/node_modules/@getpaseo/server');

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

function replaceOnce(source, before, after, label = 'implementation') {
  const found = source.includes(after) ? after : before;
  if (!source.includes(found) || source.indexOf(found) !== source.lastIndexOf(found)) {
    throw new Error(`Upstream ${label} structure changed; review patch: ${before}`);
  }
  return found === after ? source : source.replace(before, after);
}

function patchModule(source, marker, transform) {
  const at = source.indexOf(marker), start = source.lastIndexOf('__d(', at);
  if (at < 0 || at !== source.lastIndexOf(marker) || start < 0 || (start > 0 && source[start - 1] !== '\n')) {
    throw new Error(`Upstream module structure changed; review patch: ${marker}`);
  }
  const next = source.indexOf('\n__d(', at), end = next < 0 ? source.length : next;
  return source.slice(0, start) + transform(source.slice(start, end)) + source.slice(end);
}

module.exports = { serverRoot, checkCompatibility, replaceOnce, patchModule };
