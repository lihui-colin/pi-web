const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { patchExplorerSidebarMaximize } = require('../srcs/patches/service/patch-web-ui.cjs');
const { serverRoot } = require('../srcs/patches/patch-utils.cjs');
const baseline = require('../srcs/patches/service/patch-web-ui.baseline.json');
const helper = fs.readFileSync(path.join(__dirname, '../srcs/patches/service/explorer-sidebar-maximize.js'), 'utf8');
function official(t) {
  const installed = fs.existsSync(path.join(serverRoot, 'package.json')) && JSON.parse(fs.readFileSync(path.join(serverRoot, 'package.json'))).version === baseline.version;
  if (process.env.PASEO_RUNTIME_PREFIX) assert.ok(installed);
  if (!installed) { t.skip(`Paseo ${baseline.version} bundle not installed`); return null; }
  return fs.readFileSync(path.join(serverRoot, 'dist/server/web-ui', baseline.webEntry), 'utf8');
}
function moduleAt(text, marker) {
  const at = text.indexOf(marker); assert.ok(at >= 0, marker);
  return text.slice(text.lastIndexOf('\n__d(', at), text.indexOf('\n__d(', at));
}
function collect(node, type) {
  if (!node) return null;
  if (Array.isArray(node)) return node.map(child => collect(child, type)).find(Boolean);
  return node.type === type ? node : collect(node.props?.children, type);
}

test('Explorer maximization changes the frame geometry and leaves terminal/native panes intact', t => {
  const source = official(t); if (!source) return;
  const patched = patchExplorerSidebarMaximize(source);
  assert.equal(patchExplorerSidebarMaximize(patched), patched);
  assert.equal(moduleAt(patched, '_e.TerminalPane=function'), moduleAt(source, '_e.TerminalPane=function'));
  const mainWrapper = ';_e.SplitContainer=createPaseoExplorerAwareMain(s,_e.SplitContainer,C.RetainedPanelActivity)';
  assert.equal(moduleAt(patched, '_e.SplitContainer=function').replace(mainWrapper, ''), moduleAt(source, '_e.SplitContainer=function'), 'the original main pane and maximize implementation are retained');
  const module = moduleAt(patched, 'Object.defineProperty(e,"ExplorerFrame",');
  const at = module.indexOf('function(n){const x=(0,l.c)(35)');
  const component = module.slice(at, module.indexOf('},t=>({surfaceColor:', at) + 1);
  const cache = Array(35).fill(Symbol.for('react.memo_cache_sentinel'));
  const jsx = (type, props) => ({ type, props });
  const geometry = { frameStyle: { width: 370 }, panelStyle: null, resizeHandle: { type: 'resize' } };
  const maxStyle = { position: 'absolute', top: 0, right: 0, bottom: 0, left: 0, width: '100%', zIndex: 20 };
  const context = vm.createContext({
    l: { c: () => cache }, s: { useIsMobilePanelActive: () => false },
    o: { useCloseFileExplorerGesture: () => ({ gesture: null, gestureRef: null }), FileExplorerCloseGestureContext: 'gesture' },
    y: { useWorkspaceLayoutStore: selector => selector({ explorerSidebarWidthByWorkspace: { workspace: 370 }, resizeExplorerSidebar() {} }) },
    h: state => state.resizeExplorerSidebar,
    p: { resolveExplorerSidebarWidth: ({ requestedWidth }) => requestedWidth },
    f: { useExplorerGeometry: () => geometry }, b: { content: {}, maximizedFrame: maxStyle },
    t: { View: 'view' }, c: { MobilePanelOverlay: 'overlay' }, u: { RetainedPanelActivity: 'activity' }, S: { jsx, jsxs: jsx },
  });
  const render = vm.runInContext('(' + component + ')', context);
  const props = { persistenceKey: 'workspace', presentation: 'dock', isOpen: true, isWorkspaceActive: true, containerWidth: 1200, children: 'all sidebar tabs' };
  let result = render(props), frame = collect(result, 'overlay');
  assert.equal(frame.props.frameStyle, geometry.frameStyle);
  assert.equal(collect(frame, 'resize').type, 'resize');
  result = render({ ...props, paseoExplorerMaximized: true }); frame = collect(result, 'overlay');
  assert.equal(frame.props.frameStyle, maxStyle, 'saved inline pixel width must not override the maximized CSS width');
  assert.equal(collect(frame, 'resize'), undefined);
  assert.equal(frame.props.presentation, 'dock', 'presentation stays mounted in the same native dock');
  result = render(props); frame = collect(result, 'overlay');
  assert.equal(frame.props.frameStyle, geometry.frameStyle, 'restores the original saved width');
  assert.ok(collect(frame, 'resize'));
  assert.throws(() => patchExplorerSidebarMaximize(source.replace('const B=(0,f.useExplorerGeometry)(q);', 'const B=unknown;')), /structure changed/);
  assert.throws(() => patchExplorerSidebarMaximize(source + module), /structure changed/);
});

test('sidebar header controls cover Files, Changes and Terminal without remounting their content', async t => {
  if (!process.env.PASEO_PLAYWRIGHT_MODULE) return t.skip('Set PASEO_PLAYWRIGHT_MODULE to an installed Playwright module');
  const source = official(t); if (!source) return;
  const toolbar = moduleAt(source, '_e.WorkspaceTabMeasurementScope=function');
  const at = toolbar.indexOf('function Pe(e){');
  const toolbarSource = toolbar.slice(at, toolbar.indexOf('function Me(', at));
  const frameModule = moduleAt(patchExplorerSidebarMaximize(source), 'Object.defineProperty(e,"ExplorerFrame",');
  const frameAt = frameModule.indexOf('function(n){const x=(0,l.c)(35)');
  const frameSource = frameModule.slice(frameAt, frameModule.indexOf('},t=>({surfaceColor:', frameAt) + 1);
  const styleSource = frameModule.match(/b=(n.StyleSheet.create\(\{content:.*?\}\}\))/)[1];
  const { chromium } = require(process.env.PASEO_PLAYWRIGHT_MODULE);
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  t.after(() => browser.close());
  const page = await browser.newPage({ viewport: { width: 1200, height: 800 }, hasTouch: true });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setContent('<style>body{margin:0}#application{height:100vh;display:flex}#navigation{width:200px;flex-shrink:0;background:#333}#root{flex:1;min-width:0;height:100%;display:flex;position:relative}button{min-width:40px;min-height:40px}header{display:flex;align-items:center;flex-shrink:0}header .tabs{display:flex;flex:1;min-width:0}textarea{flex:1;min-height:0}</style><div id="application"><aside id="navigation">Workspaces</aside><div id="root"></div></div>');
  await page.addScriptTag({ content: source.replace(/\n__r\(\d+\);\s*/g, '\n') });
  await page.addScriptTag({ content: helper });
  await page.evaluate(({ toolbarSource, frameSource, styleSource }) => {
    __r(159); // Initialize the official Unistyles themes and breakpoints.
    const React = __r(35), ReactDOM = __r(87), jsx = React.createElement;
    const NativeView = __r(1013).View, Sheet = __r(160).StyleSheet;
    const inline = __r(3389).inlineUnistylesStyle;
    const nativeStyles = Sheet.create({ dock: { flexShrink: 0, minHeight: 0 }, panel: { flex: 1, minHeight: 0, overflow: 'hidden' }, hidden: { display: 'none' } });
    const frameStyles = new Function('n', 'return ' + styleSource)({ StyleSheet: Sheet });
    // Execute the actual patched frame with real RN Web/Unistyles styles. Only
    // gesture/store/animation boundaries are replaced; the previous HTML frame
    // substitute could not catch inline pixel widths overriding static classes.
    const Frame = new Function('l', 's', 'o', 'y', 'h', 'p', 'f', 'b', 't', 'c', 'u', 'S', 'return (' + frameSource + ')')(
      { c: count => React.useRef(Array(count).fill(Symbol.for('react.memo_cache_sentinel'))).current },
      { useIsMobilePanelActive: () => false },
      { useCloseFileExplorerGesture: () => ({ gesture: null, gestureRef: null }), FileExplorerCloseGestureContext: props => props.children },
      { useWorkspaceLayoutStore: selector => selector({ explorerSidebarWidthByWorkspace: { one: 370, two: 410 }, resizeExplorerSidebar() {} }) },
      state => state.resizeExplorerSidebar,
      { resolveExplorerSidebarWidth: ({ requestedWidth }) => requestedWidth },
      { useExplorerGeometry: props => ({ frameStyle: inline({ width: props.width }), panelStyle: undefined, resizeHandle: jsx('span', { 'data-testid': 'resize' }) }) },
      frameStyles, { View: NativeView },
      { MobilePanelOverlay: props => jsx(NativeView, { testID: 'sidebar', style: [nativeStyles.dock, props.frameStyle, !props.dockVisible && nativeStyles.hidden] },
        jsx(NativeView, { style: [nativeStyles.panel, props.panelStyle] }, props.children)) },
      { RetainedPanelActivity: props => props.children }, { jsx, jsxs: jsx });
    const MaximizeButton = new Function('n', 'w', 'T', 'U', 'O', 'fe', 'we', 'ke', 'Ie', 'Te', 'oe', 'Je', toolbarSource + ';return Pe')(
      { c: count => React.useRef(Array(count).fill(Symbol.for('react.memo_cache_sentinel'))).current },
      { useTranslation: () => ({ t: key => key }) }, { useShortcutKeys: () => null },
      { jsx, jsxs: jsx },
      { ToolbarControls: props => jsx('span', { style: { display: 'flex' } }, props.children),
        ToolbarButton: props => jsx('button', { onClick: props.onPress, title: props.label, 'aria-label': props.label, 'data-testid': props.testID }, props.selected ? 'Restore' : 'Maximize') },
      'span', 'span', 'span', 'span', {}, 14, {});
    window.mounts = 0; window.unmounts = 0;
    function Content() {
      const [text, setText] = React.useState('running terminal');
      React.useEffect(() => { window.mounts++; return () => window.unmounts++; }, []);
      return jsx('textarea', { id: 'terminal-input', value: text, onChange: event => setText(event.target.value) });
    }
    function Dock(props) {
      const [tab, setTab] = React.useState('Files');
      return jsx('section', { style: { display: 'flex', flexDirection: 'column', height: '100%', background: '#ddd' } },
        jsx('header', {}, jsx('div', { className: 'tabs' }, ['Files', 'Changes', 'Terminal'].map(name => jsx('button', { key: name, onClick: () => setTab(name) }, name))), props.headerAction),
        jsx('div', { id: 'active-tab' }, tab), jsx(Content));
    }
    const WrappedDock = createPaseoExplorerDock(React, Dock, MaximizeButton, props => jsx('span', { style: props.style, 'data-testid': props.testID }, props.children));
    const WrappedFrame = createPaseoExplorerFrame(React, Frame, __r(1026).useRetainedPanelActive);
    const RetainedPanelActivity = __r(1026).RetainedPanelActivity;
    window.chatKeyActions = 0;
    function Chat(props) {
      const active = __r(1026).useRetainedPanelActive() && props.isWorkspaceFocused;
      React.useEffect(() => {
        if (!active) return;
        const key = event => { if (event.ctrlKey && event.key === 'Enter') window.chatKeyActions++; };
        window.addEventListener('keydown', key);
        return () => window.removeEventListener('keydown', key);
      }, [active]);
      return jsx('main', { id: props.id, style: { flex: 1 } },
        jsx('button', { className: 'chat-action' }, 'Send'),
        jsx('input', { className: 'chat-draft', defaultValue: 'unsent chat draft' }));
    }
    const WrappedMain = createPaseoExplorerAwareMain(React, Chat, RetainedPanelActivity);
    function App() {
      const [open, setOpen] = React.useState(true), [workspaceKey, setWorkspaceKey] = React.useState('one');
      const [presentation, setPresentation] = React.useState('dock');
      window.reopen = () => setOpen(true); window.changeWorkspace = () => setWorkspaceKey('two');
      window.changePresentation = setPresentation;
      return jsx(React.Fragment, {}, jsx(WrappedMain, { id: 'chat', workspaceKey, isWorkspaceFocused: true }),
        jsx(WrappedFrame, { persistenceKey: workspaceKey, isOpen: open, isWorkspaceActive: true, presentation, containerWidth: 1200 },
          jsx(WrappedDock, { headerAction: jsx('button', { 'data-testid': 'sidebar-collapse', onClick: () => setOpen(false) }, 'Collapse') })));
    }
    const root = ReactDOM.createRoot(document.getElementById('root'));
    root.render(jsx(App));
    const RetainedPanel = __r(1026).RetainedPanel;
    const retainedStyles = Sheet.create({ row: { flex: 1, flexDirection: 'row', minWidth: 0 } });
    function DeckEntry({ name, active }) {
      return jsx(RetainedPanel, { active, testID: `retained-${name}` },
        jsx(NativeView, { style: retainedStyles.row }, jsx(WrappedMain, { workspaceKey: name, isWorkspaceFocused: active }),
          // A retained activity may deactivate before the screen's route-focus
          // prop catches up. Exercise the real activity context independently.
          jsx(WrappedFrame, { persistenceKey: name, isOpen: true, isWorkspaceActive: true, presentation: 'dock', containerWidth: 1000 },
            jsx(WrappedDock, { headerAction: jsx('button', {}, 'Collapse') }))));
    }
    function Deck() {
      const [active, setActive] = React.useState('one');
      window.switchRetainedWorkspace = setActive;
      return jsx(React.Fragment, {}, ['one', 'two'].map(name => jsx(DeckEntry, { key: name, name, active: name === active })));
    }
    window.mountRetainedDeck = () => root.render(jsx(Deck));
  }, { toolbarSource, frameSource, styleSource });
  await page.waitForFunction(() => window.mounts === 1);
  await page.locator('#terminal-input').fill('keep this session');
  await page.evaluate(() => { window.originalInput = document.getElementById('terminal-input'); });
  await page.locator('#chat .chat-draft').fill('keep unsent draft');
  await page.evaluate(() => { window.originalDraft = document.querySelector('#chat .chat-draft'); });
  const sidebar = page.getByTestId('sidebar');
  const navigation = await page.locator('#navigation').boundingBox();
  assert.equal((await sidebar.boundingBox()).width, 370);
  await page.getByTestId('workspace-maximize-pane').tap();
  await page.waitForFunction(() => document.querySelector('[data-testid="sidebar"]').getBoundingClientRect().width === 1000, null, { timeout: 5000 });
  assert.equal((await sidebar.boundingBox()).x, 200, 'left navigation remains outside the maximized sidebar');
  assert.deepEqual(await page.locator('#navigation').boundingBox(), navigation);
  assert.equal(await page.evaluate(() => document.elementFromPoint(250, 150).closest('[data-testid="sidebar"]') !== null), true, 'right sidebar covers the center chat area');
  assert.ok(await page.getByTestId('workspace-restore-pane').isVisible());
  assert.ok(await page.getByTestId('sidebar-collapse').isVisible());
  await page.waitForFunction(() => document.getElementById('chat').closest('[inert]'));
  await page.getByTestId('workspace-restore-pane').focus();
  for (let step = 0; step < 10; step++) {
    await page.keyboard.press('Shift+Tab');
    assert.equal(await page.evaluate(() => document.activeElement.closest('#chat') !== null), false, 'covered chat controls are excluded from keyboard focus');
  }
  await page.evaluate(() => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', ctrlKey: true })));
  assert.equal(await page.evaluate(() => window.chatKeyActions), 0, 'covered chat keyboard scope is suspended');
  const collapse = await page.getByTestId('sidebar-collapse').boundingBox();
  assert.ok(collapse.x > 1100 && collapse.y < 50, 'both controls sit at the header right edge');
  for (const tab of ['Changes', 'Terminal', 'Files']) {
    await page.getByRole('button', { name: tab, exact: true }).tap();
    assert.equal(await page.locator('#active-tab').textContent(), tab);
    assert.equal((await sidebar.boundingBox()).width, 1000, 'all sidebar views share the same maximized state');
  }
  await page.setViewportSize({ width: 800, height: 1000 });
  assert.equal((await sidebar.boundingBox()).width, 600);
  assert.equal((await sidebar.boundingBox()).x, 200);
  await page.getByTestId('workspace-restore-pane').tap();
  await page.waitForFunction(() => document.querySelector('[data-testid="sidebar"]').getBoundingClientRect().width === 370);
  assert.equal(await page.evaluate(() => document.elementFromPoint(220, 150).closest('#chat') !== null), true, 'restoring reveals chat again');
  assert.equal(await page.locator('#chat .chat-draft').evaluate(node => node === window.originalDraft), true);
  assert.equal(await page.locator('#chat .chat-draft').inputValue(), 'keep unsent draft');
  assert.equal(await page.locator('#chat').evaluate(node => node.closest('[inert]') !== null), false);
  await page.evaluate(() => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', ctrlKey: true })));
  assert.equal(await page.evaluate(() => window.chatKeyActions), 1, 'restoring enables the chat keyboard scope again');
  assert.equal(await page.locator('#terminal-input').inputValue(), 'keep this session');
  assert.equal(await page.evaluate(() => originalInput === document.getElementById('terminal-input')), true);
  await page.getByTestId('workspace-maximize-pane').tap();
  await page.setViewportSize({ width: 500, height: 900 });
  await page.evaluate(() => changePresentation('overlay'));
  await page.waitForFunction(() => !document.querySelector('[data-testid="workspace-maximize-pane"],[data-testid="workspace-restore-pane"]'));
  assert.ok(await page.getByTestId('sidebar-collapse').isVisible(), 'overlay keeps the native collapse action');
  await page.setViewportSize({ width: 1200, height: 800 });
  await page.evaluate(() => changePresentation('dock'));
  await page.waitForFunction(() => document.querySelector('[data-testid="workspace-maximize-pane"]'));
  assert.equal(await page.getByTestId('workspace-restore-pane').count(), 0);
  assert.equal((await sidebar.boundingBox()).width, 370, 'returning to a split layout starts at normal width');
  await page.getByTestId('workspace-maximize-pane').tap();
  await page.getByTestId('sidebar-collapse').tap();
  await page.waitForFunction(() => getComputedStyle(document.querySelector('[data-testid="sidebar"]')).display === 'none');
  await page.evaluate(() => reopen());
  await page.waitForFunction(() => document.querySelector('[data-testid="sidebar"]').getBoundingClientRect().width === 370);
  await page.getByTestId('workspace-maximize-pane').tap();
  await page.evaluate(() => changeWorkspace());
  await page.waitForFunction(() => document.querySelector('[data-testid="sidebar"]').getBoundingClientRect().width === 410);
  assert.deepEqual(await page.evaluate(() => [mounts, unmounts]), [1, 0]);
  await page.evaluate(() => mountRetainedDeck());
  const one = page.getByTestId('retained-one'), two = page.getByTestId('retained-two');
  await one.locator('textarea').fill('workspace one session');
  await page.waitForFunction(() => window.mounts === 3 && window.unmounts === 1);
  await one.locator('textarea').evaluate(node => { window.retainedOneInput = node; });
  await one.getByTestId('workspace-maximize-pane').tap();
  assert.equal((await one.getByTestId('sidebar').boundingBox()).width, 1000);
  await page.evaluate(() => switchRetainedWorkspace('two'));
  await two.locator('textarea').fill('workspace two session');
  assert.equal((await two.getByTestId('sidebar').boundingBox()).width, 410);
  await page.evaluate(() => switchRetainedWorkspace('one'));
  await one.locator('textarea').waitFor({ state: 'visible' });
  assert.equal((await one.getByTestId('sidebar').boundingBox()).width, 370, 'returning to a retained workspace restores its saved width');
  assert.equal(await one.getByTestId('workspace-restore-pane').count(), 0);
  assert.equal(await one.locator('textarea').inputValue(), 'workspace one session');
  assert.equal(await one.locator('textarea').evaluate(node => node === window.retainedOneInput), true);
  await one.getByTestId('workspace-maximize-pane').tap();
  await page.evaluate(() => switchRetainedWorkspace('two'));
  await two.getByTestId('workspace-maximize-pane').tap();
  await page.evaluate(() => switchRetainedWorkspace('one'));
  await one.locator('textarea').waitFor({ state: 'visible' });
  assert.equal((await one.getByTestId('sidebar').boundingBox()).width, 370);
  await page.evaluate(() => switchRetainedWorkspace('two'));
  await two.locator('textarea').waitFor({ state: 'visible' });
  assert.equal((await two.getByTestId('sidebar').boundingBox()).width, 410);
  assert.equal(await two.locator('textarea').inputValue(), 'workspace two session');
  assert.deepEqual(await page.evaluate(() => [mounts, unmounts]), [3, 1], 'switching retained workspaces preserves both mounted sessions');
  assert.equal(await page.evaluate(() => paseoExplorerSuspendedWorkspaces.size), 0, 'retained workspace transitions clean up suspended main panes');
  assert.equal(await page.locator('dialog').count(), 0);
  assert.deepEqual(errors, []);
});
