import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createReader, displayAccounts, apply, createSourceReader} from '../srcs/plugins/codex-quota/index.js';
test('quota response only exposes display fields and handles missing windows', () => {
  const result = displayAccounts([{agent:'codex', user:'a', plan:'pro', token:'secret', windows:[{used:166,name:'7 days'}]}, {agent:'claude'}]);
  assert.equal(result.length, 1);
  assert.equal(result[0].windows[0].used, 100);
  assert.equal(result[0].token, undefined);
  assert.deepEqual(displayAccounts([{agent:'codex'}])[0].windows, []);
  assert.throws(() => displayAccounts({}));
});
test('concurrent queries share one bounded process and a later request refreshes', async () => {
  let calls = 0;
  const reader = createReader(async (cmd, args, options) => {
    calls++;
    assert.equal(cmd, 'magpie');
    assert.deepEqual(args, ['accounts','codex','--json']);
    assert.equal(options.timeout, 20000);
    return {stdout:'[]'};
  });
  await Promise.all([reader(),reader()]);
  assert.equal(calls, 1);
  await reader();
  assert.equal(calls, 2);
});
test('failed queries can be retried', async () => {
  let calls = 0;
  const reader = createReader(async () => {if (++calls === 1) throw new Error('failed'); return {stdout:'[]'};});
  await assert.rejects(reader());
  assert.deepEqual(await reader(), []);
});
test('endpoint uses the authenticated DSH connection registry', () => {
  let route;
  apply({connection:{fetch:{register: value => {route = value;}}}});
  assert.equal(route.path, '/api/local-codex-quota');
  assert.deepEqual(route.methods, ['GET']);
  // DSH's HTTP bridge treats any non-buffered mode as streaming.
  // A GET with a streaming body throws before the quota handler is reached.
  const bridgeRequest = new Request('http://dsh.internal' + route.path, {method:'GET', ...(route.requestBody === 'buffered' ? {} : {body:new ReadableStream(), duplex:'half'})});
  assert.equal(bridgeRequest.method, 'GET');
});

test('upstream account errors are sanitized but visible', () => {
  const [account] = displayAccounts([{agent:'codex',error:'sensitive transport detail'}]);
  assert.match(account.error, /Magpie/);
  assert.ok(!account.error.includes('sensitive'));
});

test('quota sources are isolated and unknown sources cannot execute commands', async () => {
  const calls = [];
  const read = createSourceReader(async()=>{calls.push('magpie'); return ['m'];}, async()=>{calls.push('codex'); return ['c'];});
  assert.deepEqual(await Promise.all([read('magpie'),read('codex'),read('codex')]), [['m'],['c'],['c']]);
  assert.deepEqual(calls, ['magpie','codex']);
  await assert.rejects(read('other'));
  assert.equal(calls.length, 2);
});

import {EventEmitter} from 'node:events';
import {PassThrough} from 'node:stream';
import {readCodex, normalizeCodex} from '../srcs/plugins/codex-quota/codex.js';
test('native Codex uses initialized CLI account RPC and closes its process', async () => {
  let killed = false;
  const methods = [];
  const result = await readCodex((command,args) => {
    assert.equal(command, 'codex');
    assert.deepEqual(args, ['app-server','--listen','stdio://']);
    const child = new EventEmitter();
    child.stdout = new PassThrough(); child.stdin = new PassThrough();
    child.kill = () => {killed=true;};
    child.stdin.on('data', bytes => {
      const request = JSON.parse(bytes.toString()); methods.push(request.method);
      if (!request.id) return;
      const result = request.id === 1 ? {} : request.id === 2 ? {account:{email:'native@example.com',planType:'pro'}} : {rateLimits:{primary:{usedPercent:66,windowDurationMins:10080,resetsAt:1800000000},credits:{balance:'12.5'}}};
      queueMicrotask(()=>child.stdout.write(JSON.stringify({id:request.id,result})+'\n'));
    });
    return child;
  });
  assert.deepEqual(methods, ['initialize','initialized','account/read','account/rateLimits/read']);
  assert.equal(result[0].windows[0].name, '7 days');
  assert.equal(result[0].balance, '12.5 credits');
  assert.ok(killed);
  assert.throws(()=>normalizeCodex({account:null},{}));
});
