'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require(process.env.DSH_TEST_PLAYWRIGHT);
const {bundle,guard:patchedGuard}=JSON.parse(fs.readFileSync(0,'utf8'));
const guard=fs.readFileSync(path.join(__dirname,'fixtures/mobile_focus_guard_3_3_5.cjs'),'utf8');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.DSH_TEST_CHROMIUM||undefined,args:['--no-sandbox']});
 try{
  for(const mode of ['official','restored']){
   const page=await browser.newPage({viewport:{width:393,height:851},isMobile:true,hasTouch:true,deviceScaleFactor:2});const errors=[];
   page.on('pageerror',e=>errors.push(e.message));
   await page.setContent('<meta name="viewport" content="width=device-width,initial-scale=1"><button id="toolbar">Find</button><div id="host" style="width:370px;height:600px;padding:12px;box-sizing:border-box"></div>');
   await page.evaluate(guard=>{
    const factory={exports:{}};new Function('module',guard)(factory);const module={exports:{}};
    factory.exports(()=>({installMobileEffect(_ctx,_label,setup){window.disposeGuard=setup()}}),module,module.exports);
    window.focusGuard=module.exports;module.exports.installFocusGestureGuard({});
    window.__ModuleLoader__={load({factory}){window.bundle=factory(()=>({}))}};
   },mode==='official'?guard:patchedGuard);
   await page.addScriptTag({content:bundle.replace('exports.TerminalBody = TerminalBody;','exports.__touch = {Terminal: import_xterm.Terminal, FitAddon: import_addon_fit.FitAddon}; exports.TerminalBody = TerminalBody;')});
   await page.evaluate(()=>{
    window.host=document.getElementById('host');window.term=new bundle.__touch.Terminal({cols:40,rows:24});term.open(host);
    const fit=new bundle.__touch.FitAddon();term.loadAddon(fit);fit.fit();
    window.input=[];term.onData(data=>input.push(data));
   });
   await page.evaluate(()=>new Promise(resolve=>term.write('Touch focus\r\nblank area below',resolve)));
   assert.equal(await page.locator('#host .xterm-screen > canvas').count(),0,'native renderer has no WebGL canvas');
   assert.equal(await page.locator('[data-dsh-terminal-renderer]').count(),0,'retired renderer helper is absent');
   // The mobile guard still rejects async or unrelated focus attempts.
   await page.evaluate(()=>{term.blur();term.focus()});assert.equal(await page.evaluate(()=>document.activeElement===term.textarea),false);
   const screen=await page.evaluate(()=>{const r=term.element.querySelector('.xterm-screen').getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height}});
   const points=[['text',screen.x+20,screen.y+10],['middle',screen.x+screen.width/2,screen.y+screen.height/2],['bottom',screen.x+20,screen.y+screen.height-20]];
   if(mode==='restored'){
    const rules=await page.evaluate(()=>{const v=term.element.querySelector('.xterm-viewport'),other=document.createElement('div');other.className='xterm';const screen=document.createElement('div');other.append(screen);document.body.append(other);const blocked={own:focusGuard.shouldBlockProgrammaticFocus(term.textarea,v,10),other:focusGuard.shouldBlockProgrammaticFocus(term.textarea,screen,10),stale:focusGuard.shouldBlockProgrammaticFocus(term.textarea,v,1201),missing:focusGuard.shouldBlockProgrammaticFocus(term.textarea,null,0)};other.remove();return blocked});
    assert.deepEqual(rules,{own:false,other:true,stale:true,missing:true},'focus remains scoped to a recent tap in the same terminal');
   }
   for(const [name,x,y]of points){
    await page.evaluate(()=>term.blur());await page.touchscreen.tap(x,y);
    assert.equal(await page.evaluate(()=>document.activeElement===term.textarea),true,`${mode}: ${name} tap focuses input`);
   }
   await page.keyboard.type('abc');assert.deepEqual(await page.evaluate(()=>input),['a','b','c']);
   await page.locator('#toolbar').tap();assert.equal(await page.evaluate(()=>document.activeElement===term.textarea),false,'toolbar does not redirect focus');
   const cdp=await page.context().newCDPSession(page);const x=screen.x+50,y=screen.y+200;
   await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x,y}]});
   for(let step=1;step<=5;step++)await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x,y:y-step*15}]});
   await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
   assert.equal(await page.evaluate(()=>document.activeElement===term.textarea),false,'scroll does not request keyboard');
   await page.evaluate(()=>{term.options.disableStdin=true});await page.touchscreen.tap(screen.x+20,screen.y+20);await page.keyboard.type('z');
   assert.equal(await page.evaluate(()=>term.textarea.readOnly),true);assert.deepEqual(await page.evaluate(()=>input),['a','b','c'],'read-only input stays disabled');
   await page.evaluate(()=>{term.dispose();disposeGuard()});assert.deepEqual(errors,[]);await page.close();
   console.log(mode+': native renderer, trusted taps, input, scroll, toolbar, read-only and cleanup verified.');
  }
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
