const fs = require('node:fs');
const path = require('node:path');
const groups = {
  patches: ['patch-utils.cjs'],
  'patches/service': ['patch-workspace-git-startup.cjs', 'patch-web-ui.cjs', 'patch-web-ui.baseline.json', 'mobile-sidebar-swipe.js', 'server-directory-picker.js', 'explorer-sidebar-maximize.js', 'math-parser.js'],
  'patches/plugins/dsh': ['patch-dsh-catalog.cjs'],
};
const patches = Object.fromEntries(Object.entries(groups).flatMap(([dir, files]) => files.map(name => [name, path.join(dir, name)])));
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
