// Uses the installed frontend's React, ReactDOM and native positioning/dismiss
// hooks in an isolated page. No request reaches a service or user session.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require(process.env.DSH_TEST_PLAYWRIGHT);
const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
(async () => {
  const assets = process.env.DSH_TEST_FRONTEND_ASSETS;
  const indexName = fs.readdirSync(assets).find(name => /^index-.*\.js$/.test(name));
  assert.ok(indexName, 'Native frontend entry is required');
  const entry = fs.readFileSync(path.join(assets, indexName), 'utf8');
  const boundary = 'const XZ="data-window-drag"';
  assert.ok(entry.includes(boundary), 'Review frontend capture boundary after upstream changes');
  const browser = await chromium.launch({headless:true, args:['--no-sandbox', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']});
  try {
    const page = await browser.newPage({viewport:{width:390,height:844},hasTouch:true});
    const errors = [];
    page.on('pageerror', error => { if (error.message !== 'ISOLATED_UI_CAPTURE') errors.push(error.message); });
    await page.route('**/*', route => {
      const url = new URL(route.request().url());
      if (url.origin !== 'https://isolated-ui.invalid') return route.abort();
      const name = path.basename(url.pathname);
      if (name === indexName) return route.fulfill({contentType:'application/javascript',body:entry.replace(boundary,'window.__vendors=YZ();throw new Error("ISOLATED_UI_CAPTURE");'+boundary)});
      if (/^vendor-[\w-]+\.js$/.test(name)) return route.fulfill({contentType:'application/javascript',body:fs.readFileSync(path.join(assets,name),'utf8')});
      if (route.request().resourceType() === 'document') return route.fulfill({contentType:'text/html',body:`<style>body{margin:0;height:1800px}#test{position:fixed;left:30px;bottom:40px}[data-composer-input]{width:280px;height:40px}.context-panel{position:fixed;box-sizing:border-box;width:240px;background:#eee;padding:10px}.context-root{display:inline-flex}</style><div id="test"></div><button id="outside" style="position:fixed;right:10px;top:10px">Outside</button><script type="module" src="/${indexName}"></script>`});
      return route.abort();
    });
    await page.goto('https://isolated-ui.invalid/');
    await page.waitForFunction(() => window.__vendors);
    await page.evaluate(() => {
      window.react = __vendors.react;
      window.react_jsx_runtime = __vendors['react/jsx-runtime'];
      window.react_dom = __vendors['react-dom'];
      window.react_dom_client = __vendors['react-dom/client'];
      window._deepseek_ai_dsh_client_ui_primitives = {...__vendors['@deepseek-ai/dsh-client-ui-primitives'], Tooltip:({children})=>children};
      window.contextOccupancy = p => p ? {percent:30,usedTokens:30,contextWindow:100} : null;
      window.ContextMeter_module_css_default = new Proxy({}, {get:(_,key)=>'context-'+key});
      window.READING_SLOT = '__READING__'; window.ROWS=[]; window.RADIUS=6; window.CIRCUMFERENCE=38; window.formatTokens=String;
      // Track the actual hooks' global listeners, including capture identity.
      window.listeners = [];
      window.observers = new Map();
      for (const name of ['MutationObserver','ResizeObserver']) {
        const NativeObserver = window[name];
        window[name] = class extends NativeObserver {
          observe(target,options) { if (!observers.has(this)) observers.set(this,new Set()); observers.get(this).add(target); return super.observe(target,options); }
          unobserve(target) { observers.get(this)?.delete(target); return super.unobserve(target); }
          disconnect() { observers.delete(this); return super.disconnect(); }
        };
      }
      const add = EventTarget.prototype.addEventListener, remove = EventTarget.prototype.removeEventListener;
      const tracked = (target,type) => (target === document || target === window) && ['pointerdown','keydown','resize','scroll'].includes(type);
      const capture = options => typeof options === 'boolean' ? options : !!options?.capture;
      EventTarget.prototype.addEventListener = function(type,callback,options) {
        if (tracked(this,type) && !listeners.some(l=>l.target===this && l.type===type && l.callback===callback && l.capture===capture(options))) listeners.push({target:this,type,callback,capture:capture(options)});
        return add.call(this,type,callback,options);
      };
      EventTarget.prototype.removeEventListener = function(type,callback,options) {
        if (tracked(this,type)) listeners = listeners.filter(l=>!(l.target===this && l.type===type && l.callback===callback && l.capture===capture(options)));
        return remove.call(this,type,callback,options);
      };
    });
    await page.addScriptTag({path:path.join(__dirname,'../srcs/patches/service/dsh_composer_metadata.js')});
    await page.addScriptTag({path:path.join(__dirname,'fixtures/composer_contenteditable_rc1.js')});
    await page.evaluate(({wrapper,meter}) => {
      window.eval(meter);
      const h = react.createElement;
      window.mounts=0;window.unmounts=0;window.actions=0;window.compositions=[];
      window.editor={setRootElement:()=>{},setEditable:()=>{}};
      const projection=key=>key==='contextPressure'?{projectedTokens:30,contextWindow:100}:undefined;
      const t=(key,args)=>key==='context.aria'?'Context '+args.percent:key;
      window.DshInputBar=function DshInputBar({sessionId}) {
        react.useEffect(()=>{mounts++;return()=>unmounts++;},[]);
        return h('div',null,
          h(ComposerContentEditable,{editor:sessionId===undefined?null:editor,editable:true,tabIndex:0,onCompositionStart:()=>compositions.push('start'),onCompositionEnd:()=>compositions.push('end')}),
          h(DshSessionInfoTrigger,{useProjection:projection,t}),
          h(DshComposerMetadata,{key:sessionId},h('div',{'data-composer-dock':true},
            h('span',{'data-composer-stat':'usage'},'Usage'),
            h(DshContextMeter,{useProjection:projection,t,renderSlot:()=>h('button',{id:'quota-action',onClick:()=>actions++},'Quota action')}))));
      };
      window.eval(wrapper+'\nwindow.ReviewInputBar=InputBar;');
      window.root=react_dom_client.createRoot(document.querySelector('#test'));
      window.render=(sessionId,rendererKey='adoption')=>react_dom.flushSync(()=>root.render(h(ReviewInputBar,{sessionId,key:rendererKey})));
      window.unrelated=()=>react_dom.flushSync(()=>root.render(h('div',null,h(ReviewInputBar,{sessionId:'b',key:'b'}),react_dom.createPortal(h('div',{role:'dialog','data-dsh-session-info-owner':'another-composer'},h('button',{id:'unrelated'},'Unrelated dialog')),document.body))));
      render(undefined);
    },config);
    const trigger=page.locator('[data-dsh-session-info-trigger]');
    const panel=page.locator('[data-dsh-session-info]');
    const input=page.locator('[data-composer-input]');
    await input.focus();
    await trigger.click();
    await page.evaluate(() => {
      window.oldInput=document.querySelector('[data-composer-input]');
      oldInput.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true,data:'中'}));
      window.beforeMounts=mounts;
      render('a');
      oldInput.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true,data:'中文'}));
    });
    const adoption=await page.evaluate(()=>({sameNode:oldInput===document.querySelector('[data-composer-input]'),focused:document.activeElement===oldInput,additionalMounts:mounts-beforeMounts,compositions}));
    assert.deepEqual(adoption,{sameNode:true,focused:true,additionalMounts:0,compositions:['start','end']});
    assert.equal(await panel.getAttribute('data-open'),'false');
    await trigger.click();
    // Even without the renderer remount, disclosure state alone resets.
    await page.evaluate(()=>render('b'));
    assert.equal(await panel.getAttribute('data-open'),'false');
    assert.equal(await input.evaluate(e=>e===oldInput),true);
    await trigger.click();
    // Ordinary established-session switching follows the native renderer key.
    await page.evaluate(()=>render('c','c'));
    assert.equal(await panel.getAttribute('data-open'),'false');
    assert.equal(await input.evaluate(e=>e===oldInput),false);
    assert.equal(await page.evaluate(()=>mounts),2);
    const openMeter=async()=>{await trigger.click();await page.getByRole('button',{name:'Context 30%'}).click();await page.locator('#quota-action').waitFor({state:'visible'});};
    await openMeter();
    const owned=page.locator('[role=dialog][data-dsh-session-info-owner]');
    assert.equal(await owned.getAttribute('data-dsh-session-info-owner'),await panel.getAttribute('id'));
    await page.locator('#quota-action').click();
    assert.equal(await page.evaluate(()=>actions),1);
    assert.equal(await panel.getAttribute('data-open'),'true');
    const initial=await owned.boundingBox();
    await page.setViewportSize({width:412,height:900});
    await page.evaluate(()=>{window.scrollTo(0,120);window.dispatchEvent(new Event('resize'));window.dispatchEvent(new Event('scroll'));});
    await page.evaluate(async()=>{await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame);});
    const geometry=await page.evaluate(()=>{
      const anchor=document.querySelector('.context-root').getBoundingClientRect(), popup=document.querySelector('[role=dialog]').getBoundingClientRect();
      return {anchorVisible:anchor.width>0,gap:anchor.top-popup.bottom,left:popup.left,top:popup.top};
    });
    assert.equal(geometry.anchorVisible,true);
    assert.ok(Math.abs(geometry.gap-8)<1,JSON.stringify(geometry));
    assert.ok(Math.abs(geometry.left-initial.x)<1,JSON.stringify({initial,geometry}));
    assert.ok(geometry.top>100,JSON.stringify(geometry));
    await page.locator('#quota-action').focus();await page.keyboard.press('Escape');
    assert.equal(await panel.getAttribute('data-open'),'false');
    assert.equal(await owned.count(),0);
    assert.equal(await trigger.evaluate(e=>e===document.activeElement),true);
    await openMeter();
    // Keyboard collapse has no outside pointer event to close the native meter.
    await trigger.focus();await page.keyboard.press('Enter');
    assert.equal(await panel.getAttribute('data-open'),'false');
    assert.equal(await owned.count(),0);
    await trigger.click();
    assert.equal(await owned.count(),0, 'Reopening disclosure must not resurrect its old popup');
    await page.getByRole('button',{name:'Context 30%'}).click();
    await page.locator('#quota-action').waitFor({state:'visible'});
    await page.evaluate(()=>render('session-after-popup','session-after-popup'));
    assert.equal(await panel.getAttribute('data-open'),'false');
    assert.equal(await owned.count(),0);
    // Desktop metadata remains visible even when the mobile disclosure is closed.
    await page.setViewportSize({width:1280,height:900});
    await page.getByRole('button',{name:'Context 30%'}).click();
    await page.locator('#quota-action').click();
    assert.equal(await owned.count(),1);
    await page.setViewportSize({width:390,height:844});
    await page.waitForFunction(()=>!document.querySelector('[role=dialog]'));
    await openMeter();await page.locator('#outside').click();
    assert.equal(await panel.getAttribute('data-open'),'false');
    assert.equal(await owned.count(),0);
    await page.evaluate(()=>unrelated());
    await trigger.click();await page.locator('#unrelated').click();
    assert.equal(await panel.getAttribute('data-open'),'false');
    await page.evaluate(()=>react_dom.flushSync(()=>root.unmount()));
    assert.equal(await page.locator('[role=dialog]').count(),0);
    assert.equal(await page.evaluate(()=>listeners.length),0);
    assert.equal(await page.evaluate(()=>Array.from(observers.values()).reduce((sum,targets)=>sum+targets.size,0)),0);
    // Unmount with both overlays open must remove native popup and listeners too.
    await page.evaluate(()=>{root=react_dom_client.createRoot(document.querySelector('#test'));render('cleanup','cleanup');});
    await openMeter();
    assert.ok(await page.evaluate(()=>listeners.length)>0);
    await page.evaluate(()=>react_dom.flushSync(()=>root.unmount()));
    assert.equal(await page.locator('[role=dialog]').count(),0);
    assert.equal(await page.evaluate(()=>listeners.length),0);
    assert.equal(await page.evaluate(()=>Array.from(observers.values()).reduce((sum,targets)=>sum+targets.size,0)),0);
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({adoption,sessionReset:true,ownedPortal:true,unrelatedPortalDismissed:true,outsideDismissed:true,escape:true,geometry,cleanup:true}));
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
