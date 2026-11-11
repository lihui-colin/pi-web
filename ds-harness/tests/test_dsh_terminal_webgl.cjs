'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../srcs/patches/service/dsh_terminal_webgl.js'),'utf8');
function setup({constructFails=false,activateFails=false}={}) {
 const scheduled=new Map();let next=0,addon,refreshes=0,loads=0;
 const attributes=new Map();
 class Addon {
  constructor(){if(constructFails)throw Error('no WebGL');addon=this;this.disposed=0;}
  onContextLoss(callback){this.loss=callback;return {dispose:()=>{this.loss=undefined}};}
  dispose(){this.disposed++;}
 }
 const create=new Function('DshTerminalWebglAddon','requestAnimationFrame','cancelAnimationFrame',source+'\nreturn createDshTerminalWebgl;')(Addon,callback=>{scheduled.set(++next,callback);return next},id=>scheduled.delete(id));
 const node={setAttribute:(name,value)=>attributes.set(name,value),removeAttribute:name=>attributes.delete(name)};
 const xterm={rows:24,loadAddon(){loads++;if(activateFails)throw Error('activation failed')},refresh(){refreshes++}};
 const controller=create(xterm,node);
 return {controller,attributes,get addon(){return addon},get loads(){return loads},get refreshes(){return refreshes},get scheduled(){return scheduled.size},run(){for(const [id,callback] of [...scheduled]){scheduled.delete(id);callback();}}};
}
test('GPU installation is optional and disposes exactly once',()=>{
 const h=setup();assert.equal(h.attributes.get('data-dsh-terminal-renderer'),'dom');assert.equal(h.loads,0);
 h.run();assert.equal(h.loads,1);assert.equal(h.attributes.get('data-dsh-terminal-renderer'),'webgl');
 h.controller.dispose();h.controller.dispose();assert.equal(h.addon.disposed,1);assert.equal(h.attributes.size,0);
});
test('unavailable GPU or activation failure preserves DOM renderer',()=>{
 for(const options of [{constructFails:true},{activateFails:true}]){
  const h=setup(options);h.run();assert.equal(h.attributes.get('data-dsh-terminal-renderer'),'dom');assert.equal(h.refreshes,1);
  if(h.addon)assert.equal(h.addon.disposed,1);h.controller.dispose();
 }
});
test('context loss falls back without changing terminal input or parsing',()=>{
 const h=setup();h.run();h.addon.loss();assert.equal(h.attributes.get('data-dsh-terminal-renderer'),'dom');assert.equal(h.addon.disposed,1);assert.equal(h.refreshes,1);assert.equal(h.addon.loss,undefined);h.controller.dispose();assert.equal(h.addon.disposed,1);
});
test('cleanup before next animation frame prevents late GPU setup',()=>{
 const h=setup();h.controller.dispose();assert.equal(h.scheduled,0);h.run();assert.equal(h.loads,0);assert.equal(h.attributes.size,0);
});
