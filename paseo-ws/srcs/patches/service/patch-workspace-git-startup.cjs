#!/usr/bin/env node
// Publish local Git status before waiting for remote forge/PR status.
const fs = require('node:fs');
const path = require('node:path');
const { checkCompatibility } = require('./patch-web-ui.cjs');

function main() {
  const serverRoot = path.join(__dirname, '../../../runtime/lib/node_modules/@getpaseo/cli/node_modules/@getpaseo/server');
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
  if (method.includes('includeForge: true')) {
    if (method.indexOf('includeForge: true') !== method.lastIndexOf('includeForge: true')) {
      throw new Error('Unexpected duplicate initial forge refresh option.');
    }
    source = source.slice(0, start) + method.replace('includeForge: true', 'includeForge: false') + source.slice(end);
    fs.writeFileSync(target, source);
  } else if (!method.includes('includeForge: false')) {
    throw new Error('Initial forge refresh option changed; review patch.');
  }

  console.log('Initial workspace Git snapshots no longer wait for forge/PR status.');
}

if (require.main === module) main();
module.exports = { main };
