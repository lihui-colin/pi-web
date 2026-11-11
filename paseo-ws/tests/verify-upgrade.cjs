#!/usr/bin/env node
'use strict';
// Run only AFTER the upgraded daemon starts. No agent operations or repository writes.
// PASEO_RUNTIME_PREFIX selects its SDK; PASEO_HOME selects local-credential.
// Optional: PASEO_SMOKE_BASE_REF, PASEO_SMOKE_TIMEOUT_MS (default 120000).
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const { pathToFileURL } = require('node:url');
const { randomUUID } = require('node:crypto');
const { performance } = require('node:perf_hooks');

const serviceRoot = path.resolve(__dirname, '..');
const prefix = path.resolve(process.env.PASEO_RUNTIME_PREFIX || path.join(serviceRoot, 'runtime'));
const home = path.resolve(process.env.PASEO_HOME || path.join(serviceRoot, 'data/.paseo'));
const cwd = '/home/lihui/pi-web-opt';
const workspaceId = 'wks_115fe2278ca0a297';
const terminalName = `upgrade-smoke-${randomUUID()}`;
const timeoutMs = Number(process.env.PASEO_SMOKE_TIMEOUT_MS || 120000);
const report = {
  ok: false, stage: 'initialize',
  target: '127.0.0.1:25226', cwd, workspaceId,
  transport: { connections: 0, binaryFrames: 0, binaryPayloadBytes: 0, diffFrames: 0, diffPayloadBytes: 0, diffBeginFrames: 0, diffBodyFrames: 0, diffEndFrames: 0 },
  diff: { mode: 'all', firstEntriesMs: null, entries: null, readyMs: null, files: null },
  terminal: { name: terminalName, createMs: null, subscribeMs: null, outputMs: null, outputBytes: 0, createStartedBeforeDiffReady: null, createCompletedBeforeDiffReady: null, outputVerified: false },
  cleanup: { terminalKilled: false, terminalAbsent: false, errors: [] },
};
const sockets = [];
const abort = new AbortController();
const signalHandler = () => abort.abort();
process.once('SIGINT', signalHandler);
process.once('SIGTERM', signalHandler);
function failure(code) { return Object.assign(new Error(code), { smokeCode: code }); }
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  promise.catch(() => {});
  return { promise, resolve, reject };
}
async function bounded(promise, ms, code, withAbort = true) {
  let timer, onAbort;
  try {
    return await Promise.race([
      promise,
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(failure(code)), ms);
        if (withAbort) {
          onAbort = () => reject(failure('INTERRUPTED'));
          abort.signal.addEventListener('abort', onAbort, { once: true });
          if (abort.signal.aborted) onAbort();
        }
      }),
    ]);
  } finally {
    clearTimeout(timer);
    if (onAbort) abort.signal.removeEventListener('abort', onAbort);
  }
}

async function main() {
  let client, diffHandle, terminalHandle, createdTerminalId, creation;
  let diffReady = false;
  try {
    if (!Number.isFinite(timeoutMs) || timeoutMs < 1000 || timeoutMs > 300000) throw failure('INVALID_TIMEOUT');
    const runtimeRequire = createRequire(path.join(prefix, 'lib/node_modules/@getpaseo/cli/package.json'));
    const clientPath = runtimeRequire.resolve('@getpaseo/client/internal/daemon-client');
    const sdkRequire = createRequire(clientPath);
    const sdkVersion = JSON.parse(fs.readFileSync(path.join(path.dirname(clientPath), '../package.json'), 'utf8')).version;
    report.sdkVersion = sdkVersion;
    if (!/^0\.16\./.test(sdkVersion)) throw failure('SDK_NOT_0_16');
    const { DaemonClient } = await import(pathToFileURL(clientPath).href);
    const { WebSocket } = sdkRequire('ws');
    const credential = fs.readFileSync(path.join(home, 'local-credential'), 'utf8').trim();
    if (!/^[A-Za-z0-9_-]{43}$/.test(credential)) throw failure('INVALID_LOCAL_CREDENTIAL');
    const noop = () => {};
    client = new DaemonClient({
      url: 'ws://127.0.0.1:25226/ws', clientId: `upgrade-smoke-${randomUUID()}`,
      clientType: 'cli', appVersion: sdkVersion,
      localCredential: () => credential, reconnect: { enabled: false },
      connectTimeoutMs: 20000, suppressSendErrors: true,
      logger: { debug: noop, info: noop, warn: noop, error: noop },
      webSocketFactory: (url, options) => {
        const socket = new WebSocket(url, options?.protocols, { headers: options?.headers, maxPayload: 100 * 1024 * 1024 });
        sockets.push(socket);
        report.transport.connections++;
        socket.on('message', (data, isBinary) => {
          if (!isBinary) return;
          const bytes = data instanceof ArrayBuffer ? Buffer.from(data) : ArrayBuffer.isView(data) ? Buffer.from(data.buffer, data.byteOffset, data.byteLength) : Buffer.concat(data);
          const stats = report.transport;
          stats.binaryFrames++;
          stats.binaryPayloadBytes += bytes.byteLength;
          if (bytes[0] >= 0x40 && bytes[0] <= 0x4f) {
            stats.diffFrames++;
            stats.diffPayloadBytes += bytes.byteLength;
            if (bytes[0] === 0x40) stats.diffBeginFrames++;
            if (bytes[0] === 0x41) stats.diffBodyFrames++;
            if (bytes[0] === 0x42) stats.diffEndFrames++;
          }
        });
        return socket;
      },
    });
    report.stage = 'connect';
    const connectedAt = performance.now();
    await bounded(client.connect(), 25000, 'CONNECT_TIMEOUT');
    report.connectMs = Math.round(performance.now() - connectedAt);
    const info = client.getLastServerInfoMessage();
    report.serverVersion = info?.version ?? null;
    report.diffSubscription = info?.features?.diffSubscription === true;
    if (!/^0\.16\./.test(info?.version || '')) throw failure('DAEMON_NOT_0_16');
    if (!report.diffSubscription) throw failure('DIFF_SUBSCRIPTION_UNAVAILABLE');

    report.stage = 'checkout-status';
    const checkout = await bounded(client.getCheckoutStatus(cwd), 30000, 'CHECKOUT_STATUS_TIMEOUT');
    if (!checkout.isGit || checkout.error) throw failure('CHECKOUT_STATUS_FAILED');
    const baseRef = process.env.PASEO_SMOKE_BASE_REF || checkout.baseRef;
    if (!baseRef) throw failure('ALL_COMPARE_BASE_REF_MISSING');
    const entries = deferred(), ready = deferred();
    const diffStarted = performance.now();
    report.stage = 'diff';
    diffHandle = client.observeDiff({ cwd, base: { kind: 'rev', rev: baseRef }, head: { kind: 'worktree' }, mergeBase: true, highlight: true, ignoreWhitespace: false });
    diffHandle.subscribe({
      snapshot(state) {
        if (state.phase === 'loading' && report.diff.firstEntriesMs === null && report.transport.diffBeginFrames > 0) {
          report.diff.firstEntriesMs = Math.round(performance.now() - diffStarted);
          report.diff.entries = state.entries.length;
          entries.resolve();
        } else if (state.phase === 'ready') {
          if (!diffReady) {
            diffReady = true;
            report.diff.readyMs = Math.round(performance.now() - diffStarted);
            report.diff.files = state.files.length;
            report.diff.diffTooLarge = state.diffTooLarge;
            report.diff.omittedFiles = state.files.filter(file => file.status === 'too_large').length;
            report.diff.binaryFiles = state.files.filter(file => file.status === 'binary').length;
          }
          ready.resolve();
        } else if (state.phase === 'error') {
          report.diff.errorCode = state.error.code;
          entries.reject(failure('DIFF_FAILED'));
          ready.reject(failure('DIFF_FAILED'));
        }
      },
      update() {},
      error() { entries.reject(failure('DIFF_OBSERVER_FAILED')); ready.reject(failure('DIFF_OBSERVER_FAILED')); },
    });
    await bounded(entries.promise, timeoutMs, 'DIFF_ENTRIES_TIMEOUT');
    report.stage = 'terminal-create-during-diff';
    const createStarted = performance.now();
    report.terminal.createStartedBeforeDiffReady = !diffReady;
    // Track late successful responses too, so finally can clean up after a timeout.
    creation = client.createTerminal(cwd, terminalName, undefined, { workspaceId, command: '/bin/sh', args: ['-s'], size: { rows: 24, cols: 100 } }).then(payload => {
      if (payload.terminal?.id) createdTerminalId = payload.terminal.id;
      return payload;
    });
    const created = await bounded(creation, 30000, 'TERMINAL_CREATE_TIMEOUT');
    report.terminal.createMs = Math.round(performance.now() - createStarted);
    report.terminal.createCompletedBeforeDiffReady = !diffReady;
    if (created.error || !createdTerminalId) throw failure('TERMINAL_CREATE_FAILED');
    if (created.terminal.name !== terminalName || created.terminal.workspaceId !== workspaceId) throw failure('TERMINAL_METADATA_MISMATCH');

    report.stage = 'terminal-subscribe';
    const marker = `PASEO_UPGRADE_OK_${randomUUID().replaceAll('-', '')}`;
    const output = deferred();
    let tail = '';
    let inputStarted;
    terminalHandle = client.observeTerminal(createdTerminalId, event => {
      const data = event.type === 'output' ? event.data : event.type === 'replay' && event.replay.type === 'data' ? event.replay.data : null;
      if (!data) return;
      report.terminal.outputBytes += data.byteLength;
      tail = (tail + Buffer.from(data).toString('utf8')).slice(-16384);
      if (inputStarted !== undefined && tail.includes(marker)) {
        report.terminal.outputVerified = true;
        report.terminal.outputMs = Math.round(performance.now() - inputStarted);
        output.resolve();
      }
    });
    terminalHandle.subscribe({ snapshot() {}, update(message) { if (message.type === 'terminal_stream_exit' && !report.terminal.outputVerified) output.reject(failure('TERMINAL_EXIT_BEFORE_OUTPUT')); }, error() { output.reject(failure('TERMINAL_OBSERVER_FAILED')); } });
    const subscribeStarted = performance.now();
    const subscription = await bounded(terminalHandle.ready, 20000, 'TERMINAL_SUBSCRIBE_TIMEOUT');
    if (subscription.error) throw failure('TERMINAL_SUBSCRIBE_FAILED');
    report.terminal.subscribeMs = Math.round(performance.now() - subscribeStarted);
    report.stage = 'terminal-output-and-diff-ready';
    // Octal-encode marker: a PTY echo of our command cannot masquerade as shell output.
    const encodedMarker = [...Buffer.from(marker)].map(value => `\\${value.toString(8).padStart(3, '0')}`).join('');
    inputStarted = performance.now();
    client.sendTerminalInput(createdTerminalId, { type: 'input', data: `printf '${encodedMarker}\\n'\n` });
    await Promise.all([
      bounded(output.promise, 20000, 'TERMINAL_OUTPUT_TIMEOUT'),
      bounded(ready.promise, timeoutMs, 'DIFF_READY_TIMEOUT'),
    ]);
    if (!report.transport.diffBeginFrames || !report.transport.diffEndFrames) throw failure('BINARY_DIFF_NOT_OBSERVED');
    if (report.diff.firstEntriesMs === null || report.diff.readyMs === null) throw failure('DIFF_PHASES_MISSING');
    report.ok = true;
    report.stage = 'complete';
  } catch (error) {
    report.error = error.smokeCode || 'SDK_OR_IO_FAILURE';
    report.errorType = error.name;
  } finally {
    // Release only our subscriptions and kill only our terminal ID/unique name.
    if (creation) await bounded(creation.catch(() => {}), 30000, 'LATE_CREATE_TIMEOUT', false).catch(() => report.cleanup.errors.push('LATE_CREATE_TIMEOUT'));
    if (terminalHandle) await bounded(terminalHandle.release(), 5000, 'TERMINAL_RELEASE_TIMEOUT', false).catch(() => report.cleanup.errors.push('TERMINAL_RELEASE_FAILED'));
    if (diffHandle) await bounded(diffHandle.release(), 5000, 'DIFF_RELEASE_TIMEOUT', false).catch(() => report.cleanup.errors.push('DIFF_RELEASE_FAILED'));
    if (client && creation) {
      // Recover an ID if the create response was lost; never select another name.
      let ownIds = createdTerminalId ? [createdTerminalId] : [];
      try {
        const listed = await bounded(client.listTerminals(cwd, undefined, { workspaceId }), 10000, 'TERMINAL_CLEANUP_LIST_TIMEOUT', false);
        ownIds = [...new Set([...ownIds, ...listed.terminals.filter(item => item.name === terminalName && item.workspaceId === workspaceId).map(item => item.id)])];
        if (!ownIds.length) report.cleanup.terminalAbsent = true;
      } catch { report.cleanup.errors.push('TERMINAL_CLEANUP_LIST_FAILED'); }
      for (const id of ownIds) {
        try {
          const killed = await bounded(client.killTerminal(id), 10000, 'TERMINAL_KILL_TIMEOUT', false);
          if (!killed.success) throw failure('TERMINAL_KILL_FAILED');
          report.cleanup.terminalKilled = true;
        } catch { report.cleanup.errors.push('TERMINAL_KILL_FAILED'); }
      }
    }
    if (client) await bounded(client.close(), 5000, 'CLIENT_CLOSE_TIMEOUT', false).catch(() => report.cleanup.errors.push('CLIENT_CLOSE_FAILED'));
    for (const socket of sockets) if (socket.readyState !== 3) socket.terminate();
    process.removeListener('SIGINT', signalHandler);
    process.removeListener('SIGTERM', signalHandler);
    if (report.cleanup.errors.length) report.ok = false;
    process.stdout.write(JSON.stringify(report, null, 2) + '\n');
    process.exitCode = report.ok ? 0 : 1;
  }
}
void main();
