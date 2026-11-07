// Isolated browser regression. Set DSH_TEST_PLAYWRIGHT, DSH_TEST_REACT_UMD and
// DSH_TEST_REACT_DOM_UMD to installed test dependencies; never connects to DSH.
const assert = require('node:assert/strict');
const path = require('node:path');
const {chromium} = require(process.env.DSH_TEST_PLAYWRIGHT);
(async () => {
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
  try {
    for (const width of [390, 820, 1600]) {
      const page = await browser.newPage({viewport: {width, height: 900}, hasTouch: width < 1024});
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.setContent(`<style>body{margin:0;background:#171b19;color:#abb1ae;font:14px system-ui;padding:16px;box-sizing:border-box}#test{max-width:760px;margin:0 auto}.card{border:1px solid #424744;border-radius:22px;padding:14px}input{box-sizing:border-box;width:100%;border:0;background:transparent;color:inherit;outline:none;margin-bottom:28px}.trailing{display:flex;align-items:center;gap:8px}button{color:inherit;background:transparent;border:0;padding:6px}.model{margin-right:auto}.send{background:#db2626;border-radius:50%;color:white;width:36px;height:36px}[data-composer-dock]{display:flex;gap:12px;flex-wrap:wrap;padding:8px;font-size:12px}svg{display:block}</style><div id="test"></div>`);
      await page.addScriptTag({path: process.env.DSH_TEST_REACT_UMD});
      await page.addScriptTag({path: process.env.DSH_TEST_REACT_DOM_UMD});
      await page.evaluate(() => {
        window.react = React;
        window.contextOccupancy = p => p?.contextWindow ? {percent: Math.min(100, Math.round(p.projectedTokens / p.contextWindow * 100))} : null;
        const element = (type, props, key) => React.createElement(type, {...props, key});
        window.react_jsx_runtime = {jsx: element, jsxs: element};
      });
      await page.addScriptTag({path: path.join(__dirname, '../srcs/patches/service/dsh_composer_metadata.js')});
      await page.evaluate(registration => {
        const NS = 'chat';
        const slots = {
          inject(name, callback) {
            if (name !== 'conversation.input.right') throw Error('Wrong slot');
            callback();
          },
          register(options, component) {
            if (options.name !== 'conversation.input.right' || options.id !== 'dsh-session-info') throw Error('Wrong registration');
            window.SessionInfoSlot = component;
          }
        };
        eval(registration);
      }, process.argv[2]);
      await page.evaluate(() => {
        window.root = ReactDOM.createRoot(document.querySelector('#test'));
        window.render = (session = 'a', value = 10, bot = false) => {
          const h=React.createElement;
          const dock = h('div', {'data-composer-dock': true},
            bot ? h('button', {className: 'bt-btw-dock'}, 'Queued message') :
              h('span', {'data-composer-stat': 'activity'}, `${value} turns · 35 tok/s`),
            !bot && h('span', null, 'postmo-quant · 243M tok · Cache hit 97%'),
            !bot && h('button', {type:'button',onClick: () => window.originalAction = true}, 'Usage details'));
          const projection = () => ({projectedTokens:value,contextWindow:100});
          const tree = h(DshComposerFrame, {key:session},
            h('form', {onSubmit:e=>{e.preventDefault();window.submitted=true}},
              h('div',{className:'card'},h('input',{placeholder:'Message or run a task…'}),
                h('div',{className:'trailing'},h('span',{className:'model'},'GPT-6.1 · High'),
                  h(window.SessionInfoSlot,{useProjection:projection,t:()=> 'Session info'}),
                  h('button',{type:'button','aria-label':'Microphone'},'♩'),
                  h('button',{type:'button',className:'send','aria-label':'Stop'},'■'))),
              h(DshComposerMetadata,null,dock)));
          ReactDOM.flushSync(() => root.render(tree));
        };
        render();
      });
      const panel = page.locator('[data-dsh-session-info]');
      const trigger = page.getByRole('button', {name:'Session info',exact:true});
      assert.equal(await panel.isVisible(),false);
      assert.equal(await trigger.getAttribute('aria-expanded'),'false');
      assert.equal(await trigger.getAttribute('aria-controls'),await panel.getAttribute('id'));
      assert.equal(await trigger.locator('path').getAttribute('d'),'M12 11v6');
      await page.locator('input').fill('Unsent draft');
      await trigger.click();
      assert.equal(await page.locator('input').evaluate(e=>e===document.activeElement),true);
      assert.equal(await page.getByText('10 turns · 35 tok/s').isVisible(),true);
      await page.getByRole('button',{name:'Usage details'}).click();
      assert.equal(await page.evaluate(()=>window.originalAction),true);
      await page.evaluate(()=>render('a',11));
      assert.equal(await trigger.locator('svg').getAttribute('stroke'),'currentColor');
      assert.equal(await page.getByText('11 turns · 35 tok/s').isVisible(),true);
      await trigger.focus();await page.keyboard.press('Enter');
      assert.equal(await panel.isVisible(),false);
      await page.keyboard.press('Space');assert.equal(await panel.isVisible(),true);
      assert.equal(await page.locator('input').inputValue(),'Unsent draft');
      assert.equal(await page.evaluate(()=>!!window.submitted),false);
      await page.screenshot({path:`/tmp/dsh-session-info-expanded-${width}.png`});
      // Internal controls remain usable; clicks elsewhere auto-dismiss the panel.
      await page.locator('input').click();
      assert.equal(await panel.isVisible(),false);
      await trigger.click();assert.equal(await panel.isVisible(),true);
      await page.getByRole('button',{name:'Usage details'}).focus();
      await page.keyboard.press('Escape');
      assert.equal(await panel.isVisible(),false);
      assert.equal(await trigger.evaluate(e=>e===document.activeElement),true);
      await trigger.click();assert.equal(await panel.isVisible(),true);
      await page.evaluate(()=>render('b'));assert.equal(await panel.isVisible(),false);
      await page.evaluate(()=>render('b',10,true));
      await page.getByRole('button',{name:'Queued message'}).waitFor({state:'visible'});
      assert.equal(await trigger.count(),0);
      await page.evaluate(()=>render('b'));await trigger.waitFor({state:'visible'});
      assert.equal(await panel.isVisible(),false);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
      await page.screenshot({path:`/tmp/dsh-session-info-${width}.png`});
      await page.evaluate(() => ReactDOM.flushSync(() => root.unmount()));
      assert.deepEqual(errors, []);
      await page.close();
    }
    for (const width of [320, 360, 390, 820]) {
      const page=await browser.newPage({viewport:{width,height:500},hasTouch:true});
      // Reproduce mobile's compressed modes lane and upload's negative margin.
      await page.setContent(`<style>
        body{margin:16px}button{box-sizing:border-box;flex:none;height:30px;border:0;padding:0}
        [data-composer-card]{width:100%}.native_row{display:flex;flex-wrap:nowrap;gap:3px}
        .native_tools{display:flex;flex:0 1 auto;gap:8px;min-width:0}.native_modes{display:flex;flex:0 1 auto;min-width:0}
        .permission{display:flex;flex:none;width:32px}.icon{width:18px}.chevron{width:14px}
        .native_trailing{display:flex;flex:1;min-width:0;gap:3px}.native_trailing>button{width:32px}
        [data-mobile-nav=frame] [data-phase] [data-mobile-nav=file-upload]{position:relative;width:30px;margin-left:-9px!important}
        [data-mobile-nav=file-upload]::after{content:'';position:absolute;inset:-7px}
      </style><div data-mobile-nav="frame"><div data-phase="active"><div data-composer-card>
        <div class="native_row"><div class="native_tools"><button style="width:30px">+</button>
          <div class="native_modes"><span><button class="permission" onclick="window.permission=true"><span class="icon">A</span><span class="chevron">⌄</span></button></span></div>
          <button data-mobile-nav="file-upload" onclick="window.upload=true">📎</button></div>
          <div class="native_trailing"><button data-dsh-session-info-trigger>○</button><button>Mic</button><button>Send</button></div>
        </div></div></div></div>`);
      await page.evaluate(()=>{window.react={createContext:()=>null};});
      await page.addScriptTag({path:path.join(__dirname,'../srcs/patches/service/dsh_composer_metadata.js')});
      const dimensions=await page.evaluate(()=>{
        const permission=document.querySelector('.permission'),arrow=document.querySelector('.chevron'),upload=document.querySelector('[data-mobile-nav=file-upload]');
        const p=permission.getBoundingClientRect(),a=arrow.getBoundingClientRect(),u=upload.getBoundingClientRect();
        return {gap:u.left-p.right,arrowGap:u.left-a.right,permissionHit:permission.contains(document.elementFromPoint(p.right-1,p.y+15)),uploadHit:upload.contains(document.elementFromPoint(u.x+1,u.y+15)),overflow:document.documentElement.scrollWidth>innerWidth};
      });
      assert.ok(dimensions.gap>=7.5 && dimensions.arrowGap>=7.5,JSON.stringify({width,...dimensions}));
      assert.equal(dimensions.permissionHit,true);assert.equal(dimensions.uploadHit,true);assert.equal(dimensions.overflow,false);
      await page.locator('.permission').click({position:{x:31,y:15}});
      assert.equal(await page.evaluate(()=>window.permission),true);assert.equal(await page.evaluate(()=>!!window.upload),false);
      await page.locator('[data-mobile-nav=file-upload]').click({position:{x:1,y:15}});
      assert.equal(await page.evaluate(()=>window.upload),true);
      await page.close();
    }
    console.log('Session info ring: collapsed/expanded, live usage, original actions, draft/focus, keyboard, session reset and Bot queue verified at 390/820/1600px');
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
