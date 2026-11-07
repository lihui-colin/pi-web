const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../srcs/patches/service/mobile-sidebar-swipe.js'),'utf8');
function setup({compact=true,editable=false,open=false,leftHost=false}={}) {
  const listeners=new Map();
  const shell={isConnected:true,getAttribute:()=>compact?'compact-shell':'wide-shell'};
  const target={closest:selector=>selector.includes('compact-shell')?(compact?shell:null):
    selector.includes('gesture-host')?(leftHost?{}:null):(editable?{}:null)};
  const document={
    querySelector:selector=>selector.includes('compact-shell')?(compact?shell:null):(open?{}:null),
    addEventListener:(type,fn)=>{assert.ok(!listeners.has(type));listeners.set(type,fn)},
    removeEventListener:(type,fn)=>{assert.equal(listeners.get(type),fn);listeners.delete(type)},
  };
  const context=vm.createContext({document});vm.runInContext(source,context);
  const point=(x,y,id=1)=>({clientX:x,clientY:y,identifier:id});
  function emit(type,points,cancelable=true){
    let prevented=false;
    listeners.get(type)?.({target,touches:points,cancelable,preventDefault:()=>{prevented=true}});
    return prevented;
  }
  return {emit,point,context,listeners,shell};
}
test('left-edge rightward pan is reserved for the native sidebar handler',()=>{
  const {emit,point}=setup();
  emit('touchstart',[point(12,100)]);
  assert.equal(emit('touchmove',[point(14,101)]),false);
  assert.equal(emit('touchmove',[point(24,102)]),true);
  assert.equal(emit('touchmove',[point(100,103)]),true);
  emit('touchend',[]);
  assert.equal(emit('touchmove',[point(120,103)]),false);
});
test('vertical, leftward, center and diagonal pans remain browser-owned',()=>{
  for(const [start,move] of [[[12,100],[13,120]],[[12,100],[1,100]],[[80,100],[160,100]],[[12,100],[18,112]]]){
    const {emit,point}=setup();emit('touchstart',[point(...start)]);
    assert.equal(emit('touchmove',[point(...move)]),false);
    if(start[0]<=32) assert.equal(emit('touchmove',[point(150,move[1])]),false);
  }
});
test('desktop, editors, dialogs and open panels are not intercepted',()=>{
  for(const options of [{compact:false},{editable:true},{open:true}]){
    const {emit,point}=setup(options);emit('touchstart',[point(12,100)]);
    assert.equal(emit('touchmove',[point(100,100)]),false);
  }
});
test('open left sidebar reserves leftward swipes across its list, not rightward or vertical pans',()=>{
  for(const [x,y,expected] of [[140,100,true],[290,100,false],[240,140,false]]){
    const {emit,point}=setup({open:true,leftHost:true});
    emit('touchstart',[point(240,100)]);
    assert.equal(emit('touchmove',[point(x,y)]),expected);
  }
});
test('multitouch, cancellation, changed pointer and layout changes cancel arbitration',()=>{
  for(const kind of ['multi','cancel','pointer','layout','disconnect']){
    const {emit,point,shell}=setup();emit('touchstart',[point(12,100)]);
    if(kind==='multi')emit('touchmove',[point(20,100),point(30,100,2)]);
    if(kind==='cancel')emit('touchcancel',[]);
    if(kind==='pointer')emit('touchmove',[point(20,100,2)]);
    if(kind==='layout')shell.getAttribute=()=> 'wide-shell';
    if(kind==='disconnect')shell.isConnected=false;
    assert.equal(emit('touchmove',[point(100,100)]),false);
  }
});
test('reinstall cleans listeners, and noncancelable events stay untouched',()=>{
  const {context,listeners,emit,point}=setup();
  vm.runInContext(source,context);assert.equal(listeners.size,4);
  emit('touchstart',[point(12,100)]);
  assert.equal(emit('touchmove',[point(100,100)],false),false);
  context.__paseoMobileSidebarSwipeCleanup();assert.equal(listeners.size,0);
});
