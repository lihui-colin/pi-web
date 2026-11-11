'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {chromium}=require(process.env.DSH_TEST_PLAYWRIGHT);
const {bundle}=JSON.parse(fs.readFileSync(0,'utf8'));
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.DSH_TEST_CHROMIUM||undefined,args:['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 try{
  for(const forceUnavailable of [false,true]){
   const page=await browser.newPage({viewport:{width:1000,height:700}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
   await page.setContent('<div id="host" style="width:900px;height:600px"></div>');
   await page.evaluate(forceUnavailable=>{
    if(forceUnavailable){const original=HTMLCanvasElement.prototype.getContext;HTMLCanvasElement.prototype.getContext=function(type,...args){return type==='webgl2'?null:original.call(this,type,...args)}}
    window.gpuAvailable=!!document.createElement('canvas').getContext('webgl2');
    window.__ModuleLoader__={load({factory}){window.bundle=factory(()=>({}))}};
   },forceUnavailable);
   await page.addScriptTag({content:bundle.replace('exports.TerminalBody = TerminalBody;','exports.__test = {Terminal: import_xterm.Terminal, createWebgl: createDshTerminalWebgl}; exports.TerminalBody = TerminalBody;')});
   await page.evaluate(()=>{
    window.host=document.getElementById('host');window.term=new bundle.__test.Terminal({cols:80,rows:24});term.open(host);window.renderer=bundle.__test.createWebgl(term,host);window.input=[];term.onData(data=>input.push(data));
   });
   const expected=await page.evaluate(()=>gpuAvailable?'webgl':'dom');
   if(expected==='webgl')await page.waitForFunction(()=>host.getAttribute('data-dsh-terminal-renderer')==='webgl',null,{timeout:10000});
   else await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
   assert.equal(await page.evaluate(()=>host.getAttribute('data-dsh-terminal-renderer')),expected);
   await page.evaluate(()=>new Promise(resolve=>term.write('\x1b[31mGPU界\x1b[0m\r\nend',resolve)));
   assert.equal(await page.evaluate(()=>term.buffer.active.getLine(0).translateToString(true)),'GPU界');
   assert.equal(await page.evaluate(()=>term.buffer.active.getLine(1).translateToString(true)),'end');
   await page.evaluate(()=>term.focus());await page.keyboard.type('abc');assert.deepEqual(await page.evaluate(()=>input),['a','b','c']);
   if(expected==='webgl'){
    assert.ok(await page.locator('#host canvas').count()>0);
    const lost=await page.evaluate(()=>{const gl=host.querySelector('canvas')?.getContext('webgl2');const extension=gl?.getExtension('WEBGL_lose_context');if(!extension)return false;extension.loseContext();return true});
    if(lost){await page.waitForFunction(()=>host.getAttribute('data-dsh-terminal-renderer')==='dom',null,{timeout:10000});await page.evaluate(()=>new Promise(resolve=>term.write('\r\nDOM fallback',resolve)));assert.equal(await page.evaluate(()=>term.buffer.active.getLine(2).translateToString(true)),'DOM fallback');}
   }
   await page.evaluate(()=>{renderer.dispose();term.dispose()});assert.equal(await page.locator('[data-dsh-terminal-renderer]').count(),0);assert.deepEqual(errors,[]);await page.close();
  }
  console.log('Real xterm: WebGL rendering, unavailable-GPU fallback, context loss, keyboard input and cleanup verified.');
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
