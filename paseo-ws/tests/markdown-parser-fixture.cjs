const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { sourceFile } = require('./support.cjs');
const { serverRoot } = require('../srcs/patches/patch-utils.cjs');
const baseline = require('../srcs/patches/service/patch-web-ui.baseline.json');
const { patchMarkdownMath } = require('../srcs/patches/service/patch-web-ui.cjs');

// Run the actual bundled md4c WASM, not a second Markdown implementation. Load
// only its Metro dependency tree; never execute the app entry or React modules.
const parsers = new Map();
function upstreamParser(t, patched = false) {
  const packageFile = path.join(serverRoot, 'package.json');
  const installed = fs.existsSync(packageFile)
    && JSON.parse(fs.readFileSync(packageFile, 'utf8')).version === baseline.version;
  if (process.env.PASEO_RUNTIME_PREFIX) assert.ok(installed, 'explicit runtime must match the baseline');
  if (!installed) { t.skip(`Paseo ${baseline.version} bundle not installed`); return null; }
  if (parsers.has(patched)) return parsers.get(patched);
  const source = fs.readFileSync(path.join(serverRoot, 'dist/server/web-ui', baseline.webEntry), 'utf8');
  const lines = (patched ? patchMarkdownMath(source) : source).split('\n');
  const definitions = new Map(), cache = new Map();
  const context = vm.createContext({
    console, TextDecoder, TextEncoder, URL, atob, setTimeout, clearTimeout,
    __d: (factory, id, deps) => definitions.set(id, { factory, deps }),
  });
  if (patched) vm.runInContext(fs.readFileSync(sourceFile('math-parser.js'), 'utf8'), context);
  const candidates = lines.filter(line => line.startsWith('__d(') && line.includes('.parseMarkdownSync='));
  assert.equal(candidates.length, 1, 'unique upstream parser module');
  vm.runInContext(candidates[0], context);
  const parserId = [...definitions.keys()][0];
  function load(id) {
    if (cache.has(id)) return cache.get(id).exports;
    if (!definitions.has(id)) {
      const modules = lines.filter(line => line.startsWith('__d(') && new RegExp('},' + id + ',\\[').test(line));
      assert.equal(modules.length, 1, `unique Metro module ${id}`);
      vm.runInContext(modules[0], context);
    }
    const { factory, deps } = definitions.get(id);
    const module = { exports: {} };
    cache.set(id, module);
    factory(context, load, load, load, module, module.exports, deps);
    return module.exports;
  }
  const parser = load(parserId);
  parsers.set(patched, parser);
  return parser;
}

function nodes(ast, type) {
  return [...(ast.type === type ? [ast] : []), ...(ast.children || []).flatMap(child => nodes(child, type))];
}
const text = node => node.content ?? (node.children || []).map(text).join('');
const math = ast => nodes(ast, 'LatexMathInline').concat(nodes(ast, 'LatexMathDisplay')).map(text);

module.exports = { upstreamParser, nodes, text, math };
