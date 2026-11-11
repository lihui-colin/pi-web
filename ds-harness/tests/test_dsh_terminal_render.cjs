'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {spawnSync}=require('node:child_process');
function transform(module,fixture){
 const p=spawnSync('python3',['-B','-c',`import sys\nfrom pathlib import Path\nsys.path.insert(0,sys.argv[1])\nfrom patches.service import ${module} as p\nprint(p.patch(Path(sys.argv[2]).read_text()))`,path.join(__dirname,'../srcs'),path.join(__dirname,'fixtures',fixture)],{encoding:'utf8'});
 assert.equal(p.status,0,p.stderr);return p.stdout;
}
const modelSource=transform('dsh_terminal_batching_apply','dsh_terminal_model_rc1.js');
const uiSource=transform('dsh_terminal_render_apply','dsh_terminal_screen_rc1.js');
const info={id:'term',state:'running',title:'shell',cols:80,rows:24};
const snap=(screen='baseline')=>({type:'snapshot',sequence:0,screen,info,writable:true});
const tick=()=>new Promise(r=>setImmediate(r));
async function until(f){for(let i=0;i<100;i++){if(f())return;await tick();}assert.fail('did not settle');}
function setup({remoteEOF=false}={}){
 let notifications=0;
 const Model=vm.runInNewContext(modelSource+'\nTerminalView',{AbortController,TextEncoder,setTimeout,remoteErrorOf:()=>undefined,_deepseek_ai_dsh_api_gateway_client:{RemoteStreamCarrierError:class extends Error{}},
 _deepseek_ai_dsh_client_store:{createSnapshotStore(initial){let value=initial;return {getSnapshot:()=>value,set(v){value=v;notifications++;}};}}});
 const model=new Model('s',{}, {},{update(){}},'term');
 let wait,ended=false;const queue=[];const controller=new AbortController();
 const stream={ [Symbol.asyncIterator](){return this;},next(){if(queue.length)return Promise.resolve({value:queue.shift()});if(ended)return Promise.resolve({done:true});return new Promise(r=>wait=r);},push(value,generation=1,signal=controller.signal){const item={value,generation,signal,accept(){}};if(wait){const r=wait;wait=undefined;r({value:item});}else queue.push(item);},dispose(){ended=true;wait?.({done:true});wait=undefined;return Promise.resolve();}};
 if(remoteEOF) stream[Symbol.asyncIterator]=async function*(){try{while(true){const item=await stream.next();if(item.done){const error=new Error('ended');error.code='terminal/view';error.details={issue:'attachmentEnded'};throw error;}yield item.value;}}finally{controller.abort();}};
 model.stream=stream;
 const logs=[],callbacks=[];
 class Xterm {constructor(){this.options={};this.textarea={setAttribute(){}};this.cols=80;this.rows=24;this.screen='';}loadAddon(){}open(){}onData(){return {dispose(){}};}write(data,callback){logs.push(['write',data,this.cols,this.rows]);callbacks.push(()=>{this.screen+=data;callback();});}reset(){logs.push(['reset']);this.screen='';}resize(cols,rows){logs.push(['resize',cols,rows]);this.cols=cols;this.rows=rows;}dispose(){logs.push(['dispose']);}focus(){}}
 const effects=[];let xterm;
 const context={queueMicrotask,react:{useRef(value){return {current:value===null?{clientWidth:0,clientHeight:0}:value};},useLayoutEffect(f){effects.push(f);},useEffect(){}},import_xterm:{Terminal:class extends Xterm{constructor(...a){super(...a);xterm=this;}}},import_addon_fit:{FitAddon:class{proposeDimensions(){return {cols:120,rows:30};}}},TerminalTheme:class{update(){}dispose(){}},observeTerminalCursor(){return {dispose(){}};},ResizeObserver:class{observe(){}disconnect(){}},getComputedStyle(){return {};},react_jsx_runtime:{jsx(){return {}; }},terminal_module_css_default:{screen:'screen'}};
 vm.createContext(context);vm.runInContext(uiSource+'\nthis.Screen=TerminalScreen;',context);
 model.patch({info,phase:'connecting',environment:{maxCols:200,maxRows:80}});
 const mountUI=()=>{effects.length=0;context.Screen({state:model.state.getSnapshot(),model,visible:false,label:'shell',theme:{fontFamilies:{terminal:''},fontSizes:{terminal:14}}});return effects[0]();};
 const cleanup=mountUI();
 const done=model.consume(stream);
 return {model,stream,controller,logs,callbacks,done,cleanup,mountUI,get xterm(){return xterm;},get notifications(){return notifications;},parse(){assert.ok(callbacks.length);callbacks.shift()();}};
}
test('actual transformed TerminalScreen sink fences snapshot, writes directly, keeps state barriers and real callbacks',async()=>{
 const h=setup();h.stream.push(snap());await until(()=>h.callbacks.length===1);
 assert.equal(h.model.pendingRender.revision,1);assert.equal(h.logs.filter(x=>x[0]==='reset').length,0);
 h.parse();assert.equal(h.model.pendingRender.revision,1);assert.equal(h.xterm.screen,'');h.parse();
 await until(()=>!h.model.pendingRender);const before=h.notifications;
 h.stream.push({type:'output',sequence:1,data:'first'});await until(()=>h.callbacks.length===1);
 assert.equal(h.notifications,before);assert.equal(h.model.state.getSnapshot().render,undefined);
 h.stream.push({type:'state',info:{...info,cols:93,rows:37},writable:false});
 h.stream.push({type:'output',sequence:2,data:'second'});await tick();assert.equal(h.xterm.cols,80);
 h.parse();await until(()=>h.callbacks.length===1);
 assert.equal(h.xterm.cols,93);assert.equal(h.xterm.options.disableStdin,true);
 assert.deepEqual(h.logs.filter(x=>x[0]==='write').at(-1),['write','second',93,37]);
 h.parse();await h.stream.dispose();await h.done;h.cleanup();
});
test('aborted write is fenced before a fresh snapshot; stale callbacks cannot ack or reset it',async()=>{
 const h=setup();h.stream.push(snap());await until(()=>h.callbacks.length);h.parse();h.parse();
 h.stream.push({type:'output',sequence:1,data:'old'});await until(()=>h.callbacks.length);
 h.controller.abort();const next=new AbortController();h.stream.push(snap('fresh'),2,next.signal);
 await until(()=>h.callbacks.length===2);const revision=h.model.pendingRender.revision;
 h.parse();assert.equal(h.model.pendingRender.revision,revision);h.parse();
 assert.equal(h.xterm.screen,'');assert.equal(h.model.pendingRender.revision,revision);h.parse();
 assert.equal(h.xterm.screen,'fresh');await h.stream.dispose();await h.done;h.cleanup();
});
test('fit is deferred across snapshot parsing and lifetime cleanup ignores late writes',async()=>{
 const h=setup();let fits=0;h.stream.push(snap());await until(()=>h.callbacks.length);
 h.xterm.dshRenderGate.visibility(true,()=>fits++);assert.equal(fits,0);h.parse();assert.equal(fits,0);h.parse();await tick();assert.equal(fits,1);
 h.xterm.dshRenderGate.visibility(true,()=>fits++);assert.equal(fits,1); // metadata dimensions must not refit between a state barrier and output
 h.xterm.dshRenderGate.visibility(false,()=>fits++);h.xterm.dshRenderGate.visibility(true,()=>fits++);assert.equal(fits,2);
 h.stream.push({type:'output',sequence:1,data:'late'});await until(()=>h.callbacks.length);h.cleanup();h.parse();await h.done;
 assert.equal(h.model.pendingRender,undefined);assert.equal(h.model.renderer,undefined);
});
test('exclusive owner, child-before-parent mount, StrictMode and remount obtain a fresh attachment once',async()=>{
 const h=setup();await h.stream.dispose();await h.done;h.model.detach();let connects=0;
 h.model.connect=function(){connects++;this.stream={dispose:()=>Promise.resolve()};};
 // Child layout registered first, then parent passive mount connects exactly once.
 const cleanupParent=h.model.mount();assert.equal(connects,1);
 assert.throws(()=>h.model.bindRenderer(()=>{}),/already owned/);
 h.cleanup();cleanupParent();assert.equal(h.model.mounted,false);
 const child=h.mountUI();assert.equal(connects,1);const parent=h.model.mount();assert.equal(connects,2);
 child();parent();child();parent();
 h.model.mounted=true;const onlyChild=h.mountUI();assert.equal(connects,3);
 // Parent mount after a child reconnect must not duplicate that attachment.
 const anotherParent=h.model.mount();assert.equal(connects,3);onlyChild();anotherParent();
 h.model.patch({phase:'closed'});const closedChild=h.mountUI();const closedParent=h.model.mount();assert.equal(connects,4);closedChild();closedParent();
});
test('direct sink does not gate original input ACK and deduplicates render revisions',async()=>{
 const h=setup();h.model.attachment={pending:new Map([[1,{inputBytes:2,frameBytes:10}]]),acknowledged:0,bytes:2,bufferedBytes:10,inFlightBytes:10};let flushed=0;h.model.flushInput=()=>flushed++;
 h.stream.push(snap());await until(()=>h.callbacks.length);h.stream.push({type:'ack',sequence:1});await until(()=>flushed===1);
 assert.equal(h.model.attachment.bytes,0);assert.equal(h.model.pendingRender.revision,1);
 const count=h.logs.length;h.model.offerFrame({revision:1,frame:snap('duplicate'),writable:true});assert.equal(h.logs.length,count);
 h.parse();h.parse();await h.stream.dispose();await h.done;h.cleanup();
});
test('normal EOF abort drains the final direct write and terminal state before closing',async()=>{
 const h=setup({remoteEOF:true});h.stream.push(snap());await until(()=>h.callbacks.length);
 h.stream.push({type:'output',sequence:1,data:'final'});h.stream.push({type:'state',info:{...info,state:'exited',cols:101},writable:false});
 await h.stream.dispose();await until(()=>h.controller.signal.aborted);assert.equal(h.model.state.getSnapshot().phase,'connected');
 h.parse();h.parse();await until(()=>h.callbacks.length);assert.equal(h.model.state.getSnapshot().info.state,'running');h.parse();await h.done;
 assert.equal(h.xterm.screen,'baselinefinal');assert.equal(h.xterm.cols,101);assert.equal(h.model.state.getSnapshot().phase,'closed');h.cleanup();
});
test('deferred fit cannot override queued readonly or exit dimensions using stale React state',async()=>{
 for(const state of ['running','exited']){
  const h=setup();h.stream.push(snap());await until(()=>h.callbacks.length);
  let staleFits=0;
  // Model a visibility effect that captured the pre-barrier writable React state.
  h.xterm.dshRenderGate.visibility(true,()=>{staleFits++;h.xterm.resize(120,30);});
  h.stream.push({type:'state',info:{...info,state,cols:91,rows:33},writable:false});
  await until(()=>h.model.state.getSnapshot().writable===false);
  h.parse();h.parse();await until(()=>h.model.state.getSnapshot().info.cols===91);await tick();
  assert.equal(staleFits,0);assert.equal(h.xterm.cols,91);assert.equal(h.xterm.rows,33);
  assert.equal(h.xterm.options.disableStdin,true);
  await h.stream.dispose();await h.done;h.cleanup();
 }
});
test('overflow detaches while a direct parser callback is pending and never acknowledges it',async()=>{
 const h=setup();h.stream.push(snap());await until(()=>h.callbacks.length);
 h.stream.push({type:'output',sequence:1,data:'x'.repeat(2*1024*1024)});await h.done;
 assert.equal(h.model.stream,undefined);assert.equal(h.model.pendingRender,undefined);assert.equal(h.model.state.getSnapshot().phase,'failed');
 h.parse();assert.equal(h.logs.some(x=>x[0]==='reset'),false);h.cleanup();
});
