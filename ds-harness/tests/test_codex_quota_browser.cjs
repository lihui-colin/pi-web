const {chromium} = require(process.env.DSH_TEST_PLAYWRIGHT);
const path = require('node:path');
const assert = require('node:assert/strict');
(async () => {
 const browser = await chromium.launch({headless:true,args:['--no-sandbox']});
 try {
  for (const width of [390, 1440]) {
   const page = await browser.newPage({viewport:{width,height:850}});
   await page.setContent('<form id="root"></form>');
   await page.addScriptTag({path:process.env.DSH_TEST_REACT_UMD});
   await page.addScriptTag({path:process.env.DSH_TEST_REACT_DOM_UMD});
   await page.evaluate(() => {
    window.calls = 0; window.sources = []; window.model = {next:{provider:'magpie-responses',model:'codex/gpt-6.1-sol'}};
    window.fetch = async url => {window.sources.push(url); window.calls++; return {ok:!window.fail,status:window.fail ? 503 : 200,json:async()=>({error:window.fail ? 'Codex CLI 登录已失效，请重新登录。' : undefined,accounts:[{user:'account@example.com',plan:'pro',balance:'61833.26 credits',readAt:new Date().toISOString(),windows:[{name:'7 days',used:66,resetsAt:new Date(Date.now()+4*86400000).toISOString()}]}]})};};
    window.__ModuleLoader__ = {load({factory}) {
      const plugin = factory(name => name === 'react' ? React : ReactDOM);
      plugin.apply({effect:f=>f(), slots:{inject:(_name,f)=>f(), register:(meta, Component) => {
       window.registration=meta;
       window.root = ReactDOM.createRoot(document.querySelector('#root'));
       window.renderModel = value => {window.model=value; ReactDOM.flushSync(()=>window.root.render(React.createElement(Component,{useProjection:()=>window.model})));};
       window.renderModel(window.model);
      }}});
    }};
   });
   await page.addScriptTag({path:path.join(__dirname,'../srcs/plugins/codex-quota/client.js')});
   await page.getByRole('button',{name:'Codex 额度',exact:true}).click();
   assert.equal(await page.locator('.dsh-quota-open').textContent(), '');
   assert.equal(await page.locator('.dsh-quota-open svg').count(), 1);
   const dialog = page.getByRole('dialog');
   await dialog.getByText('已使用 66%').waitFor();
   assert.equal(await dialog.locator('progress').getAttribute('value'),'66');
   await dialog.getByText('剩余 61,833.26').waitFor();
   await dialog.getByText('account@example.com').waitFor();
   await dialog.getByText('更新于 刚刚').waitFor();
   const rect = await dialog.boundingBox();
   assert.ok(rect.x>=0 && rect.x+rect.width<=width);
   await page.screenshot({path:`/tmp/dsh-codex-quota-${width}.png`});
   await page.evaluate(()=>window.fail=true);
   await page.getByRole('button',{name:'刷新 Codex 额度'}).click();
   await page.getByRole('alert').waitFor();
   assert.equal(await page.getByRole('alert').textContent(), 'Codex CLI 登录已失效，请重新登录。');
   await page.evaluate(()=>window.fail=false);
   await page.getByRole('button',{name:'刷新 Codex 额度'}).click();
   await page.getByRole('alert').waitFor({state:'detached'});
   await page.keyboard.press('Escape');
   await dialog.waitFor({state:'detached'});
   assert.equal(await page.evaluate(()=>document.activeElement.getAttribute('aria-label')),'Codex 额度');
   assert.equal(await page.evaluate(()=>window.registration.name),'conversation.composer.dock');
   assert.ok((await page.evaluate(()=>window.sources)).every(url=>url.endsWith('source=magpie')));
   await page.evaluate(()=>window.renderModel({next:{provider:'magpie-responses',model:'deepseek/deepseek-chat'},lastUsed:{provider:'magpie-responses',model:'codex/gpt-6.1-sol'}}));
   assert.equal(await page.locator('.dsh-quota-open').count(), 0);
   await page.evaluate(()=>window.renderModel({next:{provider:'openai',model:'gpt-6.1'}}));
   assert.equal(await page.locator('.dsh-quota-open').count(), 0);
   await page.evaluate(()=>window.renderModel({lastUsed:{provider:'codex',model:'gpt-6.1-sol'}}));
   await page.getByRole('button',{name:'Codex 额度',exact:true}).click();
   await page.getByRole('dialog').getByText('已使用 66%').waitFor();
   assert.ok((await page.evaluate(()=>window.sources)).at(-1).endsWith('source=codex'));
   await page.evaluate(()=>window.renderModel({next:{provider:'other',model:'codex/gpt-6.1-sol'}}));
   assert.equal(await page.getByRole('dialog').count(), 0);
   assert.equal(await page.locator('.dsh-quota-open').count(), 0);
   await page.close();
  }
  console.log('Codex quota: phone/desktop, fields, refresh, error recovery, Escape passed');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
