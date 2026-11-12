'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const vm = require('node:vm');
const {spawnSync} = require('node:child_process');
const transformed = spawnSync('python3', ['-B', '-c', `
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from patches.service import dsh_terminal_host_batching_apply as p
print(p.patch(Path(sys.argv[2]).read_text()))
`, path.join(__dirname, '../srcs'), path.join(__dirname, 'fixtures/dsh_terminal_host_rc1.js')], {encoding:'utf8'});
assert.equal(transformed.status, 0, transformed.stderr);
const tick = () => new Promise(resolve => setImmediate(resolve));
async function until(predicate) { for (let i=0; i<100; i++) { if(predicate()) return; await tick(); } assert.fail('condition did not settle'); }
function deferred() { let resolve, reject; const promise = new Promise((a,b)=>{resolve=a;reject=b;}); return {promise,resolve,reject}; }
function channel() {
    const items=[]; let waiter, ended=false;
    return { [Symbol.asyncIterator]() { return this; },
        next() { if(items.length) return Promise.resolve({value:items.shift(),done:false}); if(ended)return Promise.resolve({done:true}); return new Promise(resolve=>waiter=resolve); },
        push(value) { if(waiter){const w=waiter;waiter=undefined;w({value,done:false});}else items.push(value); },
        end() { ended=true;if(waiter){waiter({done:true});waiter=undefined;} },
        return() { this.end(); return Promise.resolve({done:true}); }
    };
}
function setup({manual=false,maxBufferedBytes=1000000}={}) {
    let now=0, next=0;
    const timers=new Map(), callbacks=[], events=[];
    const done=deferred(), output=channel();
    const handle={done:done.promise,output, async write(data){events.push(['write',data]);},async resize(cols,rows){events.push(['resize',cols,rows]);},async terminate(){output.end();done.resolve({exitCode:0});}};
    class Screen {
        text=''; disposed=false;
        loadAddon(addon){addon.screen=this;}
        write(data,callback){const finish=()=>{this.text+=data;events.push(['parsed',data]);callback();};if(manual) callbacks.push(finish);else finish();}
        resize(cols,rows){events.push(['screen-resize',cols,rows]);}
        dispose(){this.disposed=true;assert.equal(timers.size,0);events.push(['disposed']);}
    }
    class Serializer { serialize(){return this.screen.text;} }
    class RemoteError extends Error {constructor(code,message,details){super(message);this.code=code;this.details=details;}}
    class Follower {
        active=true; frames=[];
        push(frame){this.frames.push(frame);events.push(['frame',frame]);}
        fail(error){this.error=error;}
        finish(){this.finished=true;}
        close(){this.active=false;}
        async *read(){ }
    }
    const BrowserTerminal=vm.runInNewContext(transformed.stdout+'\nBrowserTerminal', {
        Buffer,TextDecoder,Error,Date:{now:()=>now},
        setTimeout(fn,delay){const id=++next;timers.set(id,{fn,at:now+delay});return id;},clearTimeout(id){timers.delete(id);},
        requireHeadless:()=>({Terminal:Screen}),requireSerialize:()=>({SerializeAddon:Serializer}),
        RemoteError,remoteErrorOf:e=>e,TerminalFollower:Follower,assertNever(){throw new Error('unexpected command');}
    });
    const terminal=new BrowserTerminal(handle,{state:'running',cols:80,rows:24,title:'test'},100,maxBufferedBytes);
    const follower=new Follower();terminal.followers.add(follower);terminal.controller=follower;
    return {terminal,handle,output,done,follower,timers,callbacks,events,Follower,
        async advance(ms){now+=ms;const due=[...timers].filter(([,t])=>t.at<=now);for(const [id,t]of due){timers.delete(id);t.fn();}await tick();},
        async close(){await terminal.closeProcess();},
        frames(){return follower.frames.filter(f=>f.type==='output');}
    };
}
function budgetCase(parts,{limit=1024,sequence=0}={}) {
 const frames=[],timers=new Map();let nextTimer=0,stringEncodes=0;
 const context={Buffer,JSON:{stringify(value){if(typeof value==='string')stringEncodes++;return JSON.stringify(value)}},Date:{now:()=>0},setTimeout(fn){const id=++nextTimer;timers.set(id,fn);return id},clearTimeout:id=>timers.delete(id),
  Deque:class {items=[];pushBack(value){this.items.push(value)}popFront(){return this.items.shift()}clear(){this.items=[]}}};
 vm.createContext(context);
 vm.runInContext(fs.readFileSync(path.join(__dirname,'fixtures/dsh_terminal_follower_rc1.js'),'utf8')+'\n'+fs.readFileSync(path.join(__dirname,'../srcs/patches/service/dsh_terminal_host_batching.js'),'utf8'),context);
 const follower=new context.TerminalFollower(limit);
 const host={sequence,maxBufferedBytes:limit,followers:new Set([follower]),enqueue:fn=>Promise.resolve().then(fn),broadcast(frame){
  frames.push(frame);follower.push(frame);
  // Match the native iterator's accounting while consuming every frame immediately.
  let item;while((item=follower.queue.popFront())!==undefined)follower.bytes-=item.bytes;
 }};
 const batch=context.createDshHostOutputBatcher(host);for(const part of parts)batch.handle(part);batch.dispose();
 assert.equal(timers.size,0);return {frames,follower,stringEncodes};
}
test('real class initializer reads the budget after constructor assignment',async()=>{
 const h=setup({maxBufferedBytes:1024}),parts=['prime',...Array(4).fill('x'.repeat(300))];
 for(const part of parts)await h.terminal.output(part);await h.advance(5);
 assert.equal(h.frames().map(f=>f.data).join(''),parts.join(''));
 assert.ok(h.frames().every(f=>Buffer.byteLength(JSON.stringify(f))<=1024));
 assert.deepEqual(h.frames().map(f=>f.sequence),[1,2,3]);await h.close();
});
test('minimum legal follower budget permits fast consumers of several individually valid chunks',()=>{
 const parts=['prime',...Array(4).fill('x'.repeat(300))];const {frames,follower}=budgetCase(parts);
 assert.equal(follower.failure,undefined);assert.equal(frames.map(f=>f.data).join(''),parts.join(''));
 assert.ok(frames.every(frame=>Buffer.byteLength(JSON.stringify(frame),'utf8')<=1024));
 assert.deepEqual(frames.map(f=>f.sequence),[1,2,3]);assert.ok(frames.length<parts.length);
});
test('transport budget includes JSON escaping, UTF-8 and split surrogate boundaries',()=>{
 const parts=['prime',...Array(4).fill('\x00\x1b"\\\\中😀'.repeat(30)),'\ud83d'.repeat(50),'\ude00'.repeat(50)];
 const {frames,follower}=budgetCase(parts);assert.equal(follower.failure,undefined);
 assert.equal(frames.map(f=>f.data).join(''),parts.join(''));assert.ok(frames.every(f=>Buffer.byteLength(JSON.stringify(f))<=1024));
});
test('normal large budgets avoid serializing every input chunk again',()=>{
 const parts=['prime','\x00'.repeat(100),'x'.repeat(30000)];const {frames,follower,stringEncodes}=budgetCase(parts,{limit:1000000});
 assert.equal(follower.failure,undefined);assert.equal(frames.map(f=>f.data).join(''),parts.join(''));assert.equal(stringEncodes,0);
});
test('transport budget accounts for sequence header digit growth',()=>{
 const parts=['prime','x'.repeat(492),'y'.repeat(492)];const {frames,follower}=budgetCase(parts,{sequence:8});
 assert.equal(follower.failure,undefined);assert.deepEqual(frames.map(f=>f.sequence),[9,10,11]);
 assert.equal(frames.map(f=>f.data).join(''),parts.join(''));assert.ok(frames.every(f=>Buffer.byteLength(JSON.stringify(f))<=1024));
});
test('mixed chunk streams preserve order within native frame limits across budget thresholds',()=>{
 let seed=19;const random=()=>{seed=(seed*1664525+1013904223)>>>0;return seed};const alphabet=['a','\x00','\x1b','"','\\\\','中','😀','\ud83d','\ude00'];
 for(const limit of [1024,4096,393279,393280,1000000])for(const sequence of [8,998,1000000000000000]){
  const parts=Array.from({length:160},()=>Array.from({length:20+random()%40},()=>alphabet[random()%alphabet.length]).join(''));
  assert.ok(parts.every((data,i)=>Buffer.byteLength(JSON.stringify({type:'output',sequence:sequence+i+1,data}))<=limit));
  const {frames,follower}=budgetCase(parts,{limit,sequence});assert.equal(follower.failure,undefined,`budget ${limit}`);
  assert.equal(frames.map(f=>f.data).join(''),parts.join(''));assert.ok(frames.every(f=>Buffer.byteLength(JSON.stringify(f))<=limit));
  assert.deepEqual(frames.map(f=>f.sequence),frames.map((_,i)=>sequence+i+1));
 }
});
test('one originally oversized chunk retains native follower failure without splitting or dropping it',()=>{
 for(const data of ['x'.repeat(2000),'\x00'.repeat(300)]){
  const {frames,follower}=budgetCase([data]);assert.match(follower.failure.message,/exceeded its buffer/);
  assert.equal(frames.length,1);assert.equal(frames[0].data,data);
 }
});
test('idle echo is immediate; burst returns before timer and preserves UTF-8/ANSI byte order',async()=>{
    const h=setup();await h.terminal.output('a');assert.equal(h.frames()[0].data,'a');assert.equal(h.timers.size,0);
    const parts=['中','\x1b[31m','\r\n','😀'];for(const p of parts)await h.terminal.output(p);
    assert.equal(h.frames().length,1);assert.equal(h.timers.size,1);
    await h.advance(4);assert.equal(h.frames().length,1);await h.advance(1);
    assert.equal(h.frames()[1].data,parts.join(''));assert.equal(h.frames()[1].sequence,2);
    await h.advance(10);await h.terminal.output('key');assert.equal(h.frames().at(-1).data,'key');assert.equal(h.timers.size,0);
    await h.close();
});
test('provider consume aggregates consecutive chunks instead of waiting on each timer',async()=>{
    const h=setup();for(const text of ['a','b','c','d'])h.output.push(Buffer.from(text));
    await until(()=>h.terminal.screen.text==='abcd');assert.equal(h.frames().length,1);
    await h.advance(5);assert.equal(h.frames()[1].data,'bcd');await h.close();
});
test('chunk and byte bounds flush synchronously, including a single huge original chunk',async()=>{
    const h=setup();await h.terminal.output('a');for(let i=0;i<128;i++)await h.terminal.output('x');
    assert.equal(h.frames()[1].data,'x'.repeat(128));assert.equal(h.timers.size,0);
    await h.terminal.output('中'.repeat(10000));await h.terminal.output('字'.repeat(12000));
    assert.equal(h.frames()[2].data,'中'.repeat(10000));
    await h.terminal.output('z'.repeat(100000));assert.equal(h.frames()[3].data,'字'.repeat(12000));assert.equal(h.frames()[4].data.length,100000);assert.equal(h.timers.size,0);
    await h.close();
});
test('attach flushes before controller transition and baseline sequence; snapshot does not replay bytes',async()=>{
    const h=setup();await h.terminal.output('a');await h.terminal.output('b');
    const commands=channel(),signal=new AbortController().signal;
    const attachment=h.terminal.attach(commands,{},signal);const {value:snapshot}=await attachment.next();
    assert.equal(snapshot.screen,'ab');assert.equal(snapshot.sequence,2);assert.equal(h.frames()[1].data,'b');
    const before=h.follower.frames.map(f=>f.type);assert.deepEqual(before,['output','output','state']);assert.equal(h.timers.size,0);
    await h.terminal.output('c');await h.advance(5);
    assert.equal(h.frames().at(-1).sequence,3);assert.equal(h.frames().at(-1).data,'c');
    commands.end();await attachment.return();await h.close();
});
test('aborted attach does not flush or change controller before the queued signal check',async()=>{
    const h=setup();await h.terminal.output('a');await h.terminal.output('b');
    const blocker=deferred();h.terminal.enqueue(()=>blocker.promise);
    const signal=new AbortController(),commands=channel();
    const attach=h.terminal.attach(commands,{},signal.signal);const baseline=attach.next();
    signal.abort();blocker.resolve();await assert.rejects(baseline);
    assert.equal(h.terminal.controller,h.follower);assert.equal(h.frames().length,1);assert.equal(h.timers.size,1);
    await h.close();assert.equal(h.frames()[1].data,'b');
});
test('rename, resize, controller loss and all success/refusal ACKs are output barriers',async()=>{
    const h=setup();await h.terminal.output('a');await h.terminal.output('b');h.terminal.rename('new');
    assert.deepEqual(h.follower.frames.map(f=>f.type),['output','output','state']);
    const limits={maxInputBytes:100,maxCols:200,maxRows:100};const signal=new AbortController().signal;
    async function command(value){const input=channel();input.push({sequence:1,...value});input.end();await h.terminal.consumeInput(input,h.follower,limits,signal);}
    await h.terminal.output('c');await command({type:'resize',cols:90,rows:25});
    assert.deepEqual(h.follower.frames.slice(-3).map(f=>f.type),['output','state','ack']);assert.equal(h.follower.frames.at(-2).info.cols,90);
    await h.terminal.output('d');await command({type:'write',data:'key'});assert.deepEqual(h.follower.frames.slice(-2).map(f=>f.type),['output','ack']);
    await h.terminal.output('e');h.terminal.controller=undefined;await command({type:'write',data:'key'});
    assert.deepEqual(h.follower.frames.slice(-2).map(f=>f.type),['output','ack']);assert.equal(h.follower.frames.at(-1).refusal,'read-only');
    await h.terminal.output('f');h.terminal.broadcastState();assert.deepEqual(h.follower.frames.slice(-2).map(f=>f.type),['output','state']);
    await h.terminal.output('g');h.terminal.exited=true;await command({type:'write',data:'key'});assert.equal(h.follower.frames.at(-1).refusal,'not-running');
    assert.equal(h.follower.frames.at(-2).data,'g');await h.close();
});
test('timer waits behind unfinished headless writes and never publishes unparsed data',async()=>{
    const h=setup({manual:true});const a=h.terminal.output('a');await until(()=>h.callbacks.length===1);assert.equal(h.frames().length,0);h.callbacks.shift()();await a;
    const b=h.terminal.output('b');await until(()=>h.callbacks.length===1);h.callbacks.shift()();await b;
    const c=h.terminal.output('c');await until(()=>h.callbacks.length===1);await h.advance(5);assert.equal(h.frames().length,1);
    h.callbacks.shift()();await c;await tick();assert.equal(h.frames().slice(1).map(f=>f.data).join(''),'bc');
    assert.equal(h.terminal.screen.text,'abc');await h.close();
});
test('exit, provider failure and close publish final output before state/finish and cancel timer',async()=>{
    for(const failed of [false,true]){
        const h=setup();h.output.push(Buffer.from('a'));h.output.push(Buffer.from('final'));
        await until(()=>h.terminal.screen.text==='afinal');h.output.end();if(failed)h.done.reject(new Error('provider failed'));else h.done.resolve({exitCode:7});
        await h.terminal.drained;assert.deepEqual(h.follower.frames.map(f=>f.type),['output','output','state']);
        assert.equal(h.frames().at(-1).data,'final');assert.equal(h.follower.frames.at(-1).info.state,failed?'failed':'exited');assert.equal(h.timers.size,0);
        await h.close();assert.equal(h.terminal.screen.disposed,true);assert.equal(h.follower.finished,true);await h.advance(100);assert.equal(h.frames().length,2);
    }
    const h=setup();h.output.push(Buffer.from('start'));h.output.push(Buffer.from('tail'));await until(()=>h.terminal.screen.text==='starttail');await h.close();assert.equal(h.frames().at(-1).data,'tail');assert.equal(h.timers.size,0);
});
test('timer broadcast errors reach followers and subsequent barriers rather than disappearing',async()=>{
    const h=setup();await h.terminal.output('a');await h.terminal.output('b');
    h.terminal.broadcast=()=>{throw new Error('broadcast failed');};await h.advance(5);
    assert.equal(h.follower.error.message,'broadcast failed');assert.equal(h.terminal.info.state,'failed');
    assert.throws(()=>h.terminal.broadcastState(),/broadcast failed/);
    // A broken publisher makes drainage fail explicitly; observe it during cleanup.
    h.output.end();h.done.resolve({exitCode:0});await assert.rejects(h.terminal.drained,/broadcast failed/);
    await assert.rejects(h.close(),/broadcast failed/);
    assert.equal(h.terminal.screen.disposed,true);assert.equal(h.follower.finished,true);assert.equal(h.terminal.followers.size,0);
    assert.equal(h.timers.size,0);
});
test('attach return interrupts pending command reads despite a poisoned output notification',async()=>{
    const h=setup(), input=channel();let returned=0,commandsFinished=false;
    const originalReturn=input.return.bind(input);input.return=()=>{returned++;return originalReturn();};
    const consume=h.terminal.consumeInput.bind(h.terminal);
    h.terminal.consumeInput=(...args)=>consume(...args).finally(()=>{commandsFinished=true;});
    const attachment=h.terminal.attach(input,{},new AbortController().signal);
    const baseline=await attachment.next();assert.equal(baseline.value.type,'snapshot');
    await h.terminal.output('first');await h.terminal.output('tail');
    const broadcast=h.terminal.broadcast.bind(h.terminal);let first=true;
    h.terminal.broadcast=frame=>{if(first){first=false;throw new Error('transient attach broadcast error');}return broadcast(frame);};
    await h.advance(5);
    await assert.rejects(attachment.return(),/transient attach broadcast error/);
    assert.equal(returned,1);assert.equal(commandsFinished,true);assert.equal(h.terminal.controller,undefined);
    assert.equal(h.terminal.followers.size,1);assert.equal(h.timers.size,0);
    await assert.rejects(h.close(),/transient attach broadcast error/);
    assert.equal(h.terminal.screen.disposed,true);assert.equal(h.terminal.followers.size,0);
});
test('transient timer broadcast failure still releases resources and preserves the same close rejection',async()=>{
    const h=setup();await h.terminal.output('a');await h.terminal.output('tail');
    const broadcast=h.terminal.broadcast.bind(h.terminal);let first=true;
    h.terminal.broadcast=frame=>{if(first){first=false;throw new Error('temporary broadcast error');}return broadcast(frame);};
    await h.advance(5);assert.equal(h.follower.error.message,'temporary broadcast error');
    let failure;try{await h.close();assert.fail('close must report output error');}catch(error){failure=error;assert.match(error.message,/temporary broadcast error/);}
    assert.equal(h.terminal.screen.disposed,true);assert.equal(h.follower.finished,true);assert.equal(h.terminal.followers.size,0);assert.equal(h.timers.size,0);
    await assert.rejects(h.close(),error=>error===failure);
    assert.equal(h.events.filter(event=>event[0]==='disposed').length,1);
});
