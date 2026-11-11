#!/usr/bin/env node
// Publish local Git status before waiting for remote forge/PR status.
const fs = require('node:fs');
const path = require('node:path');
const { serverRoot, checkCompatibility, replaceOnce } = require('../patch-utils.cjs');

function main() {
  const installed = JSON.parse(fs.readFileSync(path.join(serverRoot, 'package.json'), 'utf8'));
  checkCompatibility(installed);

  const target = path.join(serverRoot, 'dist/server/server/workspace-git-service.js');
  let source = fs.readFileSync(target, 'utf8');
  const start = source.indexOf('    scheduleInitialWorkspaceRefresh(target) {');
  const end = source.indexOf('\n    scheduleWorkspaceObservationSetup(target) {', start);
  if (start < 0 || end < 0) {
    throw new Error('Upstream initial workspace refresh structure changed; review patch.');
  }

  const method = source.slice(start, end);
  if (!method.includes('reason: "initial"')) {
    throw new Error('Initial workspace refresh anchor changed; review patch.');
  }
  if (method.split('includeForge: ').length !== 2) throw new Error('Unexpected initial forge refresh option count.');
  const patched = replaceOnce(method, 'includeForge: true', 'includeForge: false', 'initial forge refresh');
  if (patched !== method) fs.writeFileSync(target, source.slice(0, start) + patched + source.slice(end));

  console.log('Initial workspace Git snapshots no longer wait for forge/PR status.');
}

if (require.main === module) main();
module.exports = { main };
