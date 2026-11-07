const fs = require('node:fs');
const path = require('node:path');
const patches = {"patch-web-ui.cjs": "patches/service/patch-web-ui.cjs", "patch-web-ui.baseline.json": "patches/service/patch-web-ui.baseline.json", "server-directory-picker.js": "patches/service/server-directory-picker.js", "mobile-sidebar-swipe.js": "patches/service/mobile-sidebar-swipe.js", "patch-dsh-catalog.cjs": "patches/plugins/dsh/patch-dsh-catalog.cjs"};
function relativeFile(name) {
  return ['install.sh', 'paseo_web_run.sh', 'paseo-proxy.sh'].includes(name) ? name : path.join('srcs', patches[name] || name);
}
function sourceFile(name) { return path.join(__dirname, '..', relativeFile(name)); }
function fixtureFile(root, name) {
  const target = path.join(root, relativeFile(name));
  fs.mkdirSync(path.dirname(target), {recursive:true});
  return target;
}
module.exports = {sourceFile, fixtureFile};
