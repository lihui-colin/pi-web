// Run through test_dsh_context_details.py to mount the patched native ContextMeter.
const {chromium} = require(process.env.DSH_TEST_PLAYWRIGHT);
const path = require('node:path');
const assert = require('node:assert/strict');
(async () => {
 const browser = await chromium.launch({headless:true,args:['--no-sandbox']});
 try {
  for (const width of [390, 1440]) {
   const page = await browser.newPage({viewport:{width,height:850}});
   await page.setContent(`<style>.native-panel{box-sizing:border-box;position:fixed;width:min(264px,100vw - 24px);max-height:650px;overflow:auto;padding:12px;background:#252525;color:#ddd;font:12px/20px system-ui}.native-root{display:inline-flex}</style><form id="root"></form>`);
   await page.addScriptTag({path:process.env.DSH_TEST_REACT_UMD});
   await page.addScriptTag({path:process.env.DSH_TEST_REACT_DOM_UMD});
   await page.evaluate(() => {
    window.calls = 0; window.sources = []; window.model = {next:{provider:'magpie-responses',model:'codex/gpt-6.1-sol'}};
    window.fetch = async (url, options) => {window.sources.push(url); window.calls++; window.lastSignal=options.signal; return {ok:!window.fail,status:window.fail ? 503 : 200,json:async()=>({error:window.fail ? 'Codex CLI 登录已失效，请重新登录。' : undefined,accounts:[{user:'account@example.com',plan:'pro',balance:'61833.26 credits',readAt:new Date().toISOString(),windows:[{name:'7 days',used:66,resetsAt:new Date(Date.now()+4*86400000).toISOString()}]}]})};};
    window.__ModuleLoader__ = {load({factory}) {
      const plugin = factory(name => name === 'react' ? React : ReactDOM);
      plugin.apply({effect:f=>f(), slots:{inject:(_name,f)=>f(), register:(meta, Component) => {
       window.registration=meta;window.QuotaComponent=Component;
      }}});
    }};
    window.react=React;window.react_dom=ReactDOM;
    window.react_jsx_runtime={jsx:(type,props,key)=>React.createElement(type,{...props,key}),jsxs:(type,props,key)=>React.createElement(type,{...props,key})};
    window._deepseek_ai_dsh_client_ui_primitives={
      Tooltip:({children})=>children,
      useAnchoredPosition:()=>({left:12,top:50}),
      useDismissOnOutsidePointer:(root,open,setOpen,panel)=>React.useEffect(()=>{
        if(!open)return;
        const listener=e=>{if(!root.current?.contains(e.target)&&!panel.current?.contains(e.target))setOpen(false)};
        document.addEventListener('pointerdown',listener);return()=>document.removeEventListener('pointerdown',listener);
      },[open])
    };
    window.ContextMeter_module_css_default={root:'native-root',panel:'native-panel'};
    window.contextOccupancy=p=>p;window.formatTokens=value=>String(value);window.ROWS=[];window.READING_SLOT='__READING__';window.RADIUS=5;window.CIRCUMFERENCE=31.4;
   });
   await page.addScriptTag({path:path.join(__dirname,'../srcs/plugins/codex-quota/client.js')});
   await page.addScriptTag({path:process.argv[2]});
   await page.evaluate(()=>{
    window.root=ReactDOM.createRoot(document.querySelector('#root'));
    const projection=name=>name==='modelSelection'?window.model:name==='contextPressure'?{usedTokens:3700,contextWindow:10000,percent:37}:undefined;
    const t=(key,params)=>key==='context.aria'?`${params.percent} of context used`:key==='context.used'?'Context used':key;
    window.renderModel=value=>{window.model=value;ReactDOM.flushSync(()=>root.render(React.createElement(ContextMeter,{useProjection:projection,t,renderSlot:name=>{
      if(name!=='conversation.context.details')throw Error('wrong slot');
      return React.createElement(QuotaComponent,{useProjection:projection});
    }})));};
    renderModel(window.model);
   });
   assert.equal(await page.locator('.dsh-quota-open').count(),0);
   assert.equal(await page.evaluate(()=>window.calls),0);
   assert.equal(await page.evaluate(()=>window.registration.name),'conversation.context.details');
   const context=page.getByRole('button',{name:'37% of context used',exact:true});
   await context.click();
   const dialog=page.getByRole('dialog',{name:'Context used'});
   const quota=dialog.getByRole('region',{name:'Codex 额度'});
   await quota.getByText('已使用 66%').waitFor();
   assert.equal(await quota.locator('progress').getAttribute('value'),'66');
   await quota.getByText('剩余 61,833.26').waitFor();
   await quota.getByText('account@example.com').waitFor();
   await quota.getByText('更新于 刚刚').waitFor();
   const rect=await dialog.boundingBox();assert.ok(rect.x>=0&&rect.x+rect.width<=width);
   await page.evaluate(()=>window.fail=true);await quota.getByRole('button',{name:'刷新 Codex 额度'}).click();
   await quota.getByRole('alert').waitFor();assert.equal(await quota.getByRole('alert').textContent(),'Codex CLI 登录已失效，请重新登录。');
   await page.evaluate(()=>window.fail=false);await quota.getByRole('button',{name:'刷新 Codex 额度'}).click();await quota.getByRole('alert').waitFor({state:'detached'});
   assert.ok((await page.evaluate(()=>window.sources)).every(url=>url.endsWith('source=magpie')));
   await page.keyboard.press('Escape');await dialog.waitFor({state:'detached'});
   await page.evaluate(()=>window.renderModel({next:{provider:'magpie-responses',model:'deepseek/deepseek-chat'},lastUsed:{provider:'magpie-responses',model:'codex/gpt-6.1-sol'}}));
   await context.click();assert.equal(await quota.count(),0);assert.equal(await dialog.isVisible(),true);
   await page.evaluate(()=>window.renderModel({lastUsed:{provider:'codex',model:'gpt-6.1-sol'}}));
   await quota.getByText('已使用 66%').waitFor();assert.ok((await page.evaluate(()=>window.sources)).at(-1).endsWith('source=codex'));
   await page.screenshot({path:`/tmp/dsh-context-quota-${width}.png`});
   await page.mouse.click(width-5,800);await dialog.waitFor({state:'detached'});
   await page.close();
  }
  console.log('Native context details: quota inline, no quota button, lazy reads, sources, refresh, errors, Escape/outside close passed on phone/PC');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
