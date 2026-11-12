#!/usr/bin/env node
// Publish local Git status before waiting for remote forge/PR status.
const fs = require('node:fs');
const path = require('node:path');
const { serverRoot, checkCompatibility, replaceOnce } = require('../patch-utils.cjs');

function patchSource(source) {
  const start = source.indexOf('    scheduleInitialWorkspaceRefresh(target) {');
  const end = source.indexOf('\n    scheduleWorkspaceObservationSetup(target) {', start);
  if (start < 0 || end < 0) {
    throw new Error('Upstream initial workspace refresh structure changed; review patch.');
  }

  const method = source.slice(start, end);
  if (!method.includes('reason: "initial"')) {
    throw new Error('Initial workspace refresh anchor changed; review patch.');
  }
  let patched = replaceOnce(method,
    '                includeForge: true,\n                reason: "initial",',
    '                includeForge: false,\n                reason: "initial",', 'initial forge refresh');
  const before = '            });\n        });';
  const after = `            }).then(() => {
                if (!this.isActiveObservedWorkspaceTarget(target) || !target.latestSnapshot) {
                    return;
                }
                return this.refreshWorkspaceTarget(target, {
                    origin: "demand",
                    force: false,
                    refreshStructure: false,
                    refreshWorktree: false,
                    includeForge: true,
                    reason: "initial-forge",
                    queueIfBusy: true,
                    movedRemoteRefs: new Set(),
                });
            });
        });`;
  patched = replaceOnce(patched, before, after, 'initial forge continuation');
  return source.slice(0, start) + patched + source.slice(end);
}

function main() {
  const installed = JSON.parse(fs.readFileSync(path.join(serverRoot, 'package.json'), 'utf8'));
  checkCompatibility(installed);
  const target = path.join(serverRoot, 'dist/server/server/workspace-git-service.js');
  const source = fs.readFileSync(target, 'utf8');
  const patched = patchSource(source);
  if (patched !== source) fs.writeFileSync(target, patched);

  console.log('Initial workspace Git snapshots no longer wait for forge/PR status.');
}

if (require.main === module) main();
module.exports = { main, patchSource };
