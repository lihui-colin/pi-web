const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { patchProjectWorkspaceMenu } = require('../srcs/patches/service/patch-web-ui.cjs');
const { serverRoot } = require('../srcs/patches/patch-utils.cjs');
const baseline = require('../srcs/patches/service/patch-web-ui.baseline.json');

test('project context and dropdown menus reuse the existing new-workspace action', t => {
  const installed = fs.existsSync(path.join(serverRoot, 'package.json')) && JSON.parse(fs.readFileSync(path.join(serverRoot, 'package.json'))).version === baseline.version;
  if (process.env.PASEO_RUNTIME_PREFIX) assert.ok(installed);
  if (!installed) return t.skip(`Paseo ${baseline.version} bundle not installed`);
  const source = fs.readFileSync(path.join(serverRoot, 'dist/server/web-ui', baseline.webEntry), 'utf8');
  const patched = patchProjectWorkspaceMenu(source);
  assert.equal(patchProjectWorkspaceMenu(patched), patched);
  const start = patched.indexOf('const paseoProjectWorkspaceMenuContext=');
  const wrappers = patched.slice(start, patched.indexOf('function paseoProjectActionsBase', start));
  let inherited = null, selected = 0;
  const jsx = (type, props) => ({ type, props });
  const context = vm.createContext({
    p: { createContext: () => ({ Provider: 'provider' }), useContext: () => inherited },
    u: { useTranslation: () => ({ t: key => key }) },
    Se: { jsx, jsxs: jsx, Fragment: 'fragment' }, Je: 'menu-item',
    oe: { DensityIcon: 'icon' }, S: { Plus: 'plus' },
    paseoProjectActionsBase: 'original-actions', paseoProjectMenuBase: 'original-menu',
  });
  vm.runInContext(wrappers, context);
  const create = () => selected++;
  // The dropdown inherits the same callback that the upstream + button uses.
  context.props = { worktreeTarget: { serverId: 'host' }, onBeginWorkspaceSetup: create };
  const provider = vm.runInContext('Ve(props)', context);
  assert.equal(provider.props.value, create);
  assert.equal(provider.props.children.type, 'original-actions');
  inherited = provider.props.value;
  for (const surface of ['dropdown', 'context']) {
    context.props = { surface, projectViewKey: 'project', onBeginWorkspaceSetup: surface === 'context' ? create : undefined };
    const menu = vm.runInContext('Qe(props)', context);
    const [item, original] = menu.props.children;
    assert.equal(item.props.surface, surface);
    assert.equal(item.props.testID, 'sidebar-project-menu-new-workspace-project');
    assert.equal(item.props.children, 'sidebar.workspace.actions.newWorkspace');
    item.props.onSelect();
    assert.equal(original.type, 'original-menu');
    assert.equal(original.props, context.props, 'all existing menu items keep their original props');
  }
  assert.equal(selected, 2);
  inherited = null;
  context.props = { projectViewKey: 'unavailable' };
  assert.equal(vm.runInContext('Qe(props)', context).props.children[0], null);
  context.props = { worktreeTarget: null, onBeginWorkspaceSetup: create };
  assert.equal(vm.runInContext('Ve(props)', context).props.value, null, 'no creation action without an available target');
  const row = text => {
    const at = text.indexOf('function rr({project:o');
    return text.slice(at, text.indexOf('function ', at + 10));
  };
  const anchor = 'surface:"context",projectViewKey:o.viewKey,settingsTarget:z';
  assert.equal(row(patched), row(source).replace(anchor, 'surface:"context",onBeginWorkspaceSetup:b?$:void 0,projectViewKey:o.viewKey,settingsTarget:z'), 'existing route, drag and long-press handlers remain unchanged');
  assert.throws(() => patchProjectWorkspaceMenu(source.replace(anchor, 'surface:"context",changed:true')), /structure changed/);
  assert.throws(() => patchProjectWorkspaceMenu(source + source), /structure changed/);
});
