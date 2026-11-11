'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const vm = require('node:vm');
// Transform the reviewed pristine rc.1 consumer fixture, then extract the actual
// production helper AND injected method. No installed files are required or written.
const transformed = spawnSync('python3', ['-B', '-c', `
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from patches.service import dsh_terminal_batching_apply as p
original = Path(sys.argv[2]).read_text()
print(p.patch(p.ANCHOR + '\\n' + original + p.END + '\\n}'))
`, path.join(__dirname, '../srcs'), path.join(__dirname, 'fixtures/dsh_terminal_consume_rc1.js')], {encoding:'utf8'});
assert.equal(transformed.status, 0, transformed.stderr);
const source = transformed.stdout.slice(0, transformed.stdout.indexOf('\t\tvar TerminalView = class {'));
const method = transformed.stdout.match(/async consume\(stream\) \{[\s\S]*?(?=\n\t\t\tpatch\(patch\))/)[0];
class TerminalViewError extends Error { constructor(issue, message = issue) { super(message); this.issue = issue; this.code = 'terminal/view'; this.details = {issue}; } }
const consume = vm.runInNewContext(source + '\n({' + method + '}).consume',
    {TerminalViewError, TextEncoder, setTimeout});
const info = {state:'running', title:'shell', cols:80, rows:24};
const snapshot = (sequence = 0) => ({type:'snapshot', sequence, screen:'baseline', info, writable:true});
const output = (sequence, data) => ({type:'output', sequence, data});
const tick = () => new Promise(resolve => setImmediate(resolve));
async function until(check) { for (let i=0;i<300;i++) { if(check()) return; await tick(); } assert.fail('condition did not settle'); }
function setup({remoteEOF = false} = {}) {
    let waiting, ended = false;
    const items = [], renders = [], patches = [], controller = new AbortController();
    const stream = {
        [Symbol.asyncIterator]() { return this; },
        next() { if (items.length) return Promise.resolve({value:items.shift(),done:false}); if(ended) return Promise.resolve({done:true}); return new Promise(resolve=>waiting=resolve); },
        push(value, generation=1, signal=controller.signal) { const item={value,generation,signal,accept(){}}; if(waiting) { const wake=waiting; waiting=undefined; wake({value:item,done:false}); } else items.push(item); },
        end() { ended=true; if(waiting) { waiting({done:true}); waiting=undefined; } },
        dispose() { this.end(); return Promise.resolve(); },
        return() { this.end(); return Promise.resolve({done:true}); }
    };
    const model = {
        stream, revision:0, current:{phase:'connecting',writable:false}, inventory:{update(){}},
        state:{getSnapshot(){return model.current;}},
        attachment:{pending:new Map([[1,{inputBytes:3,frameBytes:12}]]),acknowledged:0,bytes:3,bufferedBytes:12,inFlightBytes:12},
        patch(p) { Object.assign(this.current,p); patches.push({...p}); if(p.render) renders.push(p.render); },
        acknowledge(revision) { if(this.pendingRender?.revision!==revision) return; this.pendingRender.resolve(); this.pendingRender=undefined; },
        flushInput() { this.flushed=(this.flushed||0)+1; },
        fail(error) { this.error=error; this.patch({phase:'failed',writable:false}); },
        detach() { this.stream=undefined; this.attachment=undefined; this.pendingRender?.resolve(); this.pendingRender=undefined; stream.end(); }
    };
    if (remoteEOF) {
        // Match RemoteStream.read: normal options.open completion throws ended(),
        // then its finally aborts the generation before the consumer catches it.
        stream[Symbol.asyncIterator] = async function* () {
            try {
                while (true) {
                    const next = await stream.next();
                    if (next.done) throw new TerminalViewError('attachmentEnded');
                    yield next.value;
                }
            } finally { controller.abort(); }
        };
    }
    const done=consume.call(model,stream);
    return {model,stream,controller,renders,patches,done,ack(){model.acknowledge(model.pendingRender?.revision);}};
}
test('slow parser does not delay input ACK; adjacent queued output retains every byte', async()=>{
    const h=setup(); h.stream.push(snapshot()); await until(()=>h.renders.length===1);
    h.stream.push({type:'ack',sequence:1});
    for(let i=1;i<=30;i++) h.stream.push(output(i,`字${i}\x1b[31m\r\n`));
    await until(()=>h.model.flushed===1);
    assert.equal(h.model.attachment.bytes,0); assert.equal(h.renders.length,1);
    await tick(); h.ack(); await until(()=>h.renders.length===2);
    assert.equal(h.renders[1].frame.data,Array.from({length:30},(_,i)=>`字${i+1}\x1b[31m\r\n`).join(''));
    h.ack(); h.stream.end(); await h.done;
});
test('state and ACK are adjacency barriers; state metadata follows previous parse',async()=>{
    const h=setup(); h.stream.push(snapshot()); await until(()=>h.renders.length===1);
    h.stream.push(output(1,'a')); h.stream.push({type:'ack',sequence:1}); h.stream.push(output(2,'b'));
    h.stream.push({type:'state',info:{...info,cols:100},writable:false}); h.stream.push(output(3,'c'));
    await until(()=>h.model.flushed===1); await tick();
    assert.equal(h.model.current.info.cols,80); assert.equal(h.model.current.writable,false);
    h.ack(); await until(()=>h.renders.length===2); assert.equal(h.renders[1].frame.data,'a');
    h.ack(); await until(()=>h.renders.length===3); assert.equal(h.renders[2].frame.data,'b'); assert.equal(h.model.current.info.cols,80);
    h.ack(); await until(()=>h.renders.length===4); assert.equal(h.model.current.info.cols,100); assert.equal(h.renders[3].frame.data,'c');
    h.ack();h.stream.end();await h.done;
});
test('merging validates every raw sequence and rejects a gap before parsing',async()=>{
    const h=setup();h.stream.push(snapshot());await until(()=>h.renders.length===1);
    h.stream.push(output(1,'first'));h.stream.push(output(3,'gap'));
    await h.done;assert.equal(h.model.error.issue,'invalidOutput');assert.equal(h.model.current.writable,false);assert.equal(h.renders.length,1);
});
test('generation requires snapshot and duplicate snapshot is rejected',async()=>{
    for(const next of [{value:output(1,'bad'),generation:2},{value:snapshot(),generation:1}]) {
        const h=setup();h.stream.push(snapshot());await until(()=>h.renders.length===1);
        h.stream.push(next.value,next.generation);await h.done;assert.equal(h.model.error.issue,'invalidOutput');
    }
});
test('abort drops old queued output; old callback cannot acknowledge a new snapshot',async()=>{
    const h=setup();h.stream.push(snapshot());await until(()=>h.renders.length===1);
    const oldRevision=h.renders[0].revision;h.stream.push(output(1,'discard'));await tick();
    h.controller.abort();const next=new AbortController();h.stream.push(snapshot(19),2,next.signal);
    await until(()=>h.renders.length===2);
    assert.equal(h.renders[1].frame.type,'snapshot');assert.equal(h.renders[1].frame.sequence,19);
    h.model.acknowledge(oldRevision);assert.equal(h.model.pendingRender.revision,h.renders[1].revision);
    h.ack();h.stream.end();await h.done;assert.equal(h.renders.length,2);
});
test('inflight bytes count against hard cap; overflow fails and detaches without replay',async()=>{
    const h=setup();h.stream.push(snapshot());await until(()=>h.renders.length===1);
    h.stream.push(output(1,'a'.repeat(1100*1024)));await tick();
    h.stream.push(output(2,'b'.repeat(1100*1024)));
    await h.done;assert.match(h.model.error.message,/exceeded its render buffer/);assert.equal(h.model.current.phase,'failed');assert.equal(h.model.stream,undefined);assert.equal(h.model.pendingRender,undefined);assert.equal(h.model.error.issue,undefined);assert.equal(h.renders.length,1);
    // A single oversized active raw output also cannot bypass the budget.
    const g=setup();g.stream.push(snapshot());await until(()=>g.renders.length===1);g.ack();await tick();
    g.stream.push(output(1,'x'.repeat(1500*1024)));await until(()=>g.renders.length===2);
    g.stream.push(output(2,'y'.repeat(600*1024)));await g.done;assert.match(g.model.error.message,/exceeded its render buffer/);
});
test('oversized snapshot of an exited process still fails explicitly and detaches',async()=>{
    const h=setup();h.model.current.info={...info,state:'exited'};
    h.stream.push({...snapshot(),screen:'x'.repeat(2*1024*1024)});
    await h.done;assert.match(h.model.error.message,/exceeded its render buffer/);
    assert.equal(h.model.current.phase,'failed');assert.equal(h.model.stream,undefined);
    assert.equal(h.model.pendingRender,undefined);
});
test('real RemoteStream EOF abort preserves final bytes until parsed, then closes',async()=>{
    const h=setup({remoteEOF:true});h.stream.push(snapshot());await until(()=>h.renders.length===1);
    h.stream.push(output(1,'final 字\x1b[0m'));h.stream.push(output(2,'\r\nlast line'));
    h.stream.push({type:'state',info:{...info,state:'exited',exitCode:0},writable:false});
    h.stream.end();await until(()=>h.controller.signal.aborted);
    let finished=false;h.done.then(()=>finished=true);await tick();
    assert.equal(finished,false);assert.equal(h.renders.length,1);assert.equal(h.model.current.info.state,'running');
    assert.equal(h.model.current.writable,false);assert.equal(h.model.error,undefined);
    h.ack();await until(()=>h.renders.length===2);
    assert.equal(h.renders[1].frame.data,'final 字\x1b[0m\r\nlast line');
    assert.equal(h.model.current.info.state,'running');assert.equal(finished,false);
    h.ack();await h.done;assert.equal(h.model.current.info.state,'exited');
    assert.equal(h.model.current.phase,'closed');assert.equal(h.model.error,undefined);
});
test('real failed EOF drains final bytes before exposing the process failure',async()=>{
    const h=setup({remoteEOF:true});h.stream.push(snapshot());await until(()=>h.renders.length===1);
    h.stream.push(output(1,'last diagnostic'));h.stream.push({type:'state',info:{...info,state:'failed',error:'PTY read failed'},writable:false});
    h.stream.end();await until(()=>h.controller.signal.aborted);assert.equal(h.model.error,undefined);
    h.ack();await until(()=>h.renders.length===2);assert.equal(h.renders[1].frame.data,'last diagnostic');
    assert.equal(h.model.error,undefined);h.ack();await h.done;
    assert.equal(h.model.current.info.state,'failed');assert.equal(h.model.current.phase,'failed');
    assert.equal(h.model.error.message,'PTY read failed');assert.equal(h.model.stream,undefined);
});
test('external detach releases a frozen terminal EOF drain without confirming queued renders',async()=>{
    const h=setup({remoteEOF:true});h.stream.push(snapshot());await until(()=>h.renders.length===1);
    h.stream.push(output(1,'last'));h.stream.push({type:'state',info:{...info,state:'exited'},writable:false});
    h.stream.end();await until(()=>h.controller.signal.aborted);h.model.detach();await h.done;
    assert.equal(h.model.pendingRender,undefined);assert.equal(h.renders.length,1);
});
test('protocol errors after ingress exit are not hidden by the terminal state',async()=>{
    const h=setup({remoteEOF:true});h.stream.push(snapshot());await until(()=>h.renders.length===1);
    h.stream.push(output(1,'last'));h.stream.push({type:'state',info:{...info,state:'exited'},writable:false});
    h.stream.push(output(3,'gap'));await h.done;
    assert.equal(h.model.error.issue,'invalidOutput');assert.equal(h.model.current.phase,'failed');
    assert.equal(h.model.stream,undefined);assert.equal(h.model.pendingRender,undefined);
});
test('raw record cap bounds tiny frames, and batches stay within 64KiB',async()=>{
    const h=setup();h.stream.push(snapshot());await until(()=>h.renders.length===1);
    for(let i=1;i<=4096;i++) h.stream.push(output(i,''));
    await h.done;assert.match(h.model.error.message,/exceeded its render buffer/);
    const g=setup();g.stream.push(snapshot());await until(()=>g.renders.length===1);
    for(let i=1;i<=4;i++) g.stream.push(output(i,'z'.repeat(20*1024)));
    await tick();g.ack();await until(()=>g.renders.length===2);assert.equal(g.renders[1].frame.data.length,60*1024);
    g.ack();await until(()=>g.renders.length===3);assert.equal(g.renders[2].frame.data.length,20*1024);
    g.ack();g.stream.end();await g.done;
});
