"""Terminal patch installation and behavior in isolated fixtures."""
import test_support  # Configure the service source import path.
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from patches.service import dsh_terminal_apply as p


class TerminalPatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.host = self.root / 'node_modules/@deepseek-ai'
        for directory, name, version in [
            (self.host / 'dsh-client-ui-sidebar-terminal', '@deepseek-ai/dsh-client-ui-sidebar-terminal', '0.2.2-alpha.2'),
            (self.host / 'dsh-api-terminal-controller', '@deepseek-ai/dsh-api-terminal-controller', '0.2.2-alpha.2'),
            (self.host.parent / '@xterm/headless', '@xterm/headless', '6.0.0'),
            (self.host.parent / '@xterm/addon-serialize', '@xterm/addon-serialize', '0.14.0'),
        ]:
            (directory / 'lib').mkdir(parents=True)
            (directory / 'package.json').write_text(json.dumps({'name': name, 'version': version}))
        self.front = self.host / 'dsh-client-ui-sidebar-terminal/lib/client.terminal.js'
        self.model = self.host / 'dsh-api-terminal-controller/lib/client.js'
        self.backend = self.host / 'dsh-api-terminal-controller/lib/index.js'
        self.front.write_text((Path(__file__).parent / 'fixtures/dsh_terminal_screen_rc1.js').read_text())
        self.model.write_text('\n'.join([p.FORCE_SIGNATURE, p.FORCE_CHECK]))
        self.backend.write_text('\n'.join([p.SNAPSHOT_ANCHOR, p.SERIALIZE, p.HOST_SETUP, p.HOST_WRITE, p.HOST_DISPOSE]))

    def cli(self, *args):
        return subprocess.run([sys.executable, '-B', p.__file__, '--host-dir', str(self.host), *args], text=True, capture_output=True)

    def test_atomic_plan_idempotence_and_check(self):
        self.assertNotEqual(self.cli('--check').returncode, 0)
        p.publish(p.plan_changes(self.host), self.root / 'backup')
        self.assertEqual(self.cli('--check').returncode, 0)
        self.assertTrue(all(old == new for _, old, new in p.plan_changes(self.host)))
        self.model.write_text(p.FORCE_SIGNATURE + '\n' + p.FORCE_CHECK)
        self.assertNotEqual(self.cli('--check').returncode, 0)

    def test_unsupported_version_or_anchor_never_writes(self):
        original = self.front.read_bytes()
        package = self.host.parent / '@xterm/headless/package.json'
        package.write_text(json.dumps({'name': '@xterm/headless', 'version': '7.0.0'}))
        self.assertNotEqual(self.cli().returncode, 0)
        self.assertEqual(self.front.read_bytes(), original)
        package.write_text(json.dumps({'name': '@xterm/headless', 'version': '6.0.0'}))
        self.backend.write_text('unknown upstream')
        self.assertNotEqual(self.cli().returncode, 0)
        self.assertEqual(self.front.read_bytes(), original)

    def test_rc1_support_requires_matching_host_versions(self):
        for directory in ('dsh-client-ui-sidebar-terminal', 'dsh-api-terminal-controller'):
            (self.host / directory / 'package.json').write_text(json.dumps({
                'name': '@deepseek-ai/' + directory, 'version': '0.2.2-rc.1'}))
        changes = p.plan_changes(self.host)
        p.publish(changes, self.root / 'backup')
        self.assertEqual(self.cli('--check').returncode, 0)
        (self.host / 'dsh-api-terminal-controller/package.json').write_text(json.dumps({
            'name': '@deepseek-ai/dsh-api-terminal-controller', 'version': '0.2.2-alpha.2'}))
        before = [path.read_bytes() for path in (self.front, self.model, self.backend)]
        self.assertNotEqual(self.cli().returncode, 0)
        self.assertEqual([path.read_bytes() for path in (self.front, self.model, self.backend)], before)

    def direct_frontend(self):
        from patches.service import dsh_terminal_render_apply as direct
        for directory in ('dsh-client-ui-sidebar-terminal', 'dsh-api-terminal-controller'):
            (self.host / directory / 'package.json').write_text(json.dumps({
                'name': '@deepseek-ai/' + directory, 'version': '0.2.2-rc.1'}))
        return direct.patch((Path(__file__).parent / 'fixtures/dsh_terminal_screen_rc1.js').read_text())

    def test_complete_direct_mode_is_preserved_with_version_guards(self):
        self.front.write_text(self.direct_frontend())
        before = [path.read_bytes() for path in (self.front, self.model, self.backend)]
        self.assertEqual(p.plan_changes(self.host), [])
        self.assertEqual(self.cli('--check').returncode, 0)
        self.assertEqual([path.read_bytes() for path in (self.front, self.model, self.backend)], before)
        package = self.host / 'dsh-api-terminal-controller/package.json'
        package.write_text(json.dumps({'name': '@deepseek-ai/dsh-api-terminal-controller', 'version': '0.2.2-alpha.2'}))
        with self.assertRaises(ValueError):
            p.plan_changes(self.host)

    def test_partial_or_mixed_direct_mode_is_not_silently_skipped(self):
        original = self.direct_frontend()
        for text in (original.replace('renderSink.dispose()', 'renderSink.broken()'),
                     original + '\n// createTerminalClipboard', original + original):
            self.front.write_text(text)
            before = [path.read_bytes() for path in (self.front, self.model, self.backend)]
            with self.assertRaises(ValueError):
                p.plan_changes(self.host)
            self.assertEqual([path.read_bytes() for path in (self.front, self.model, self.backend)], before)

    def test_upgrade_previous_patch_and_reject_unknown_helpers(self):
        # Preserve an actual released helper, rather than reconstructing the
        # old behavior from the new implementation.
        legacy = (Path(__file__).parent / 'fixtures/dsh_terminal_redraw_v1.js').read_text()
        front = p.patch_frontend(self.front.read_text())
        front = p.undo_replacements(front, p.FENCE_REPLACEMENTS)
        front = p.undo_replacements(front, p.TOOLS_REPLACEMENTS)
        front = front.replace(p.FRONT_HELPERS, legacy)
        backend = p.patch_host(self.backend.read_text())
        backend = p.undo_replacements(backend, p.HOST_REPLACEMENTS).replace(p.HOST_HELPERS, p.SNAPSHOT)
        self.assertEqual(p.patch_frontend(front), p.patch_frontend(self.front.read_text()))
        self.assertEqual(p.patch_host(backend), p.patch_host(self.backend.read_text()))
        with self.assertRaises(ValueError):
            p.patch_frontend(front.replace('// Snapshot parsing must finish before', '// Unknown helper'))
        incomplete = p.patch_frontend(self.front.read_text()).replace(p.TOOLS_REPLACEMENTS[-1][1], p.PROPOSED)
        with self.assertRaises(ValueError):
            p.patch_frontend(incomplete)
        self.front.write_text(front.replace('let ready = false;', 'let ready = true;'))
        self.backend.write_text(backend)
        originals = [path.read_bytes() for path in (self.front, self.model, self.backend)]
        self.assertNotEqual(self.cli().returncode, 0)
        self.assertEqual([path.read_bytes() for path in (self.front, self.model, self.backend)], originals)

    def test_complete_released_legacy_tools_and_clipboard_migrate(self):
        fixed = p.patch_frontend(self.front.read_text())
        old = p.undo_replacements(fixed, p.FENCE_REPLACEMENTS)
        runtime = (Path(__file__).parent / 'fixtures/dsh_terminal_runtime_v2.js').read_text()
        old = old.replace(p.RUNTIME, runtime)
        self.assertEqual(p.patch_frontend(old), fixed)
        clipboard_only = p.undo_replacements(old, p.TOOLS_REPLACEMENTS)
        self.assertEqual(p.patch_frontend(clipboard_only), fixed)
        redraw_only = p.undo_replacements(clipboard_only, [
            (p.CLIP_HELPER, p.CLIP_HELPER_NEW), (p.CLIP_REF, p.CLIP_REF_NEW),
            (p.CLIP_SETUP, p.CLIP_SETUP_NEW), (p.CLIP_CLEANUP, p.CLIP_CLEANUP_NEW),
            (p.CLIP_CAPTURE, p.CLIP_CAPTURE_NEW), (p.CLIP_FINISH, p.CLIP_FINISH_NEW)])
        self.assertEqual(p.patch_frontend(redraw_only), fixed)
        self.assertEqual(p.patch_frontend(fixed), fixed)
        for changed in (fixed.replace(p.RUNTIME, runtime, 1),
                        p.undo_replacements(fixed, p.FENCE_REPLACEMENTS),
                        old.replace('let ready = false;', 'let ready = true;'),
                        old.replace('pending = undefined;', 'pending = null;', 1),
                        old.replace('terminalTools.current?.reset();', 'terminalTools.current?.broken();'),
                        fixed.replace('redraw.current?.resizeReadonly(state);', 'redraw.current?.unknown(state);')):
            with self.assertRaises(ValueError):
                p.patch_frontend(changed)
        # Read-only sizing and frame invalidation are part of a complete migration.
        self.assertIn('redraw.current?.resizeReadonly(state);', fixed)
        self.assertIn('[state.render, state.phase, model]', fixed)
        for cleanup in ('observer.disconnect();', 'input.dispose();', 'palette.dispose();'):
            self.assertIn(cleanup, fixed)

    def test_legacy_parser_fence_with_real_headless(self):
        dsh = shutil.which('dsh')
        if not dsh:
            self.skipTest('DSH not installed')
        modules = Path(dsh).resolve().parents[1] / 'node_modules'
        frontend = p.patch_frontend(self.front.read_text())
        start = frontend.index('\t\t\t\tlet active = true;')
        end = frontend.index('\n\t\t\t}, [state.render, state.phase, model]);', start)
        result = subprocess.run(['node', str(Path(__file__).with_name('test_dsh_terminal_legacy_fence.cjs'))],
            input=json.dumps({'write': frontend[start:end], 'clipboard': p.CLIPBOARD}),
            env={**os.environ, 'DSH_TEST_MODULES': str(modules)}, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_protocol_and_tools(self):
        dsh = shutil.which('dsh')
        if not dsh:
            self.skipTest('DSH not installed')
        modules = Path(dsh).resolve().parents[1] / 'node_modules'
        if not (modules / '@xterm/headless/package.json').exists():
            self.skipTest('xterm headless not installed')
        result = subprocess.run(['node', '--test', str(Path(__file__).with_name('test_dsh_terminal_features.cjs'))],
            env={**os.environ, 'DSH_TEST_MODULES': str(modules)}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_installed_bundles_in_isolation(self):
        if not shutil.which('dsh'):
            self.skipTest('DSH not installed')
        changes = p.plan_changes()
        direct_transform = None
        if not changes:
            from patches.common import host_directory
            from patches.service.dsh_terminal_render_apply import patch as direct_transform
            path = host_directory() / 'dsh-client-ui-sidebar-terminal/lib/client.terminal.js'
            source = path.read_text()
            changes = [(path, source, direct_transform(source))]
        for path, old, fixed in changes:
            isolated = self.root / (path.parent.parent.name + '-' + path.name)
            isolated.write_text(fixed)
            result = subprocess.run(['node', '--check', str(isolated)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            transform = direct_transform or (p.patch_frontend if path.name == 'client.terminal.js' else p.patch_model if path.name == 'client.js' else p.patch_host)
            self.assertEqual(transform(fixed), fixed)

    def test_host_controller_replies_without_attachment(self):
        dsh = shutil.which('dsh')
        if not dsh:
            self.skipTest('DSH not installed')
        modules = Path(dsh).resolve().parents[1] / 'node_modules'
        # Isolate the reviewed class, rather than slicing a possibly patched installation
        # away from helper declarations that live outside its original region.
        backend = p.patch_host((Path(__file__).parent / 'fixtures/dsh_terminal_host_rc1.js').read_text())
        script = r'''
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm'), path = require('node:path');
const modules = process.argv[1], sent = [], trace = [];
const context = {TextDecoder, requireHeadless: () => require(path.join(modules, '@xterm/headless')),
  requireSerialize: () => require(path.join(modules, '@xterm/addon-serialize'))};
vm.runInNewContext(fs.readFileSync(0, 'utf8'), context);
(async () => {
  let done; const completion = new Promise(resolve => { done = resolve; });
  const handle = {done: completion, write: async data => { sent.push(data); trace.push('reply'); }, terminate: async () => {},
    output: (async function* () { yield Buffer.from('hi\x1b[?'); yield Buffer.from('u\x1b[c\x1b[6n'); done({exitCode: 0}); })()};
  const host = new context.BrowserTerminal(handle, {cols: 80, rows: 24, state: 'running'}, 1000, 1048576);
  host.broadcast = frame => { if (frame.type === 'output') trace.push('output'); };
  await host.drained;
  assert.equal(host.info.state, 'exited'); assert.equal(host.followers.size, 0);
  assert.deepEqual(sent, ['\x1b[?0u\x1b[?1;2c\x1b[1;3R']);
  assert.deepEqual(trace, ['output', 'reply', 'output']);
  await host.closeProcess();
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
        result = subprocess.run(['node', '-e', script, str(modules)], input=backend, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(os.environ.get('DSH_TEST_PLAYWRIGHT'), 'Set DSH_TEST_PLAYWRIGHT for the optional browser test')
    def test_real_browser(self):
        source = os.environ.get('DSH_TEST_LEGACY_SOURCE')
        changes = p.plan_changes() if source is None else []
        if source is None and not changes:
            self.skipTest('Installed direct mode; set DSH_TEST_LEGACY_SOURCE to a reviewed legacy bundle')
        frontend = self.root / 'client.terminal.js'
        frontend.write_text(p.patch_frontend(Path(source).read_text()) if source else changes[0][2])
        result = subprocess.run(['node', str(Path(__file__).with_name('test_dsh_terminal_browser.cjs'))],
            env={**os.environ, 'DSH_TEST_FRONTEND': str(frontend)}, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_redraw_lifecycle(self):
        script = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
let scheduled, cancelled = 0;
const context = { setTimeout: (fn, ms) => { assert.equal(ms, 100); scheduled = fn; return 1; },
  clearTimeout: () => { scheduled = undefined; cancelled++; }, fitScreen: (term, fit, state, model) => {
    const d = fit.proposeDimensions(); term.resize(d.cols, d.rows); model.resize(d.cols, d.rows);
  }};
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), context);
let size = {cols:80, rows:24}, calls = [];
const node = {clientWidth: 800, clientHeight: 500};
const term = {resize: (cols, rows) => calls.push(['local', cols, rows])};
const model = {resize: (cols, rows, force) => calls.push(['host', cols, rows, force])};
let live = {visible:true, state:{phase:'connected', writable:true, environment:{maxCols:100, maxRows:50}}};
const redraw = context.createTerminalRedraw(term, {proposeDimensions: () => size}, node, model, () => live);
redraw.update(); assert.deepEqual(calls, []);
const snapshot = redraw.prepare(); redraw.update(); assert.deepEqual(calls, []);
redraw.parsed(snapshot);
assert.deepEqual(calls, [['local',81,24],['host',81,24,true]]);
size = {cols:92, rows:30}; redraw.update(); assert.equal(calls.length,2);
scheduled(); assert.deepEqual(calls.slice(2), [['local',92,30],['host',92,30,true]]);
// A detached view invalidates its pending callback even after reconnection.
const stale = redraw.prepare(); live.state.phase='disconnected'; live.state.writable=false; redraw.update();
live.state.phase='connected'; live.state.writable=true; redraw.parsed(stale); assert.equal(calls.length,4);
// Hidden/read-only views wait for control and visibility.
live.visible=false; const next = redraw.prepare(); redraw.parsed(next); assert.equal(calls.length,4);
live.visible=true; live.state.writable=false; redraw.update(); assert.equal(calls.length,4);
live.state.writable=true; size={cols:100,rows:30}; redraw.update();
assert.deepEqual(calls.slice(-2), [['local',99,30],['host',99,30,true]]);
// Disposal restores the original dimensions even if the host has not acknowledged the pulse.
redraw.dispose(); assert.deepEqual(calls.slice(-2), [['local',100,30],['host',100,30,true]]);
assert.ok(cancelled >= 1); assert.equal(scheduled, undefined);
// A read-only follower must also wait until its snapshot has parsed.
const readonlyCalls = [];
live = {visible:true, state:{phase:'connected', writable:false, info:{cols:70,rows:20}}};
const follower = context.createTerminalRedraw({resize:(...size)=>readonlyCalls.push(size)}, {}, node, model, () => live);
const pending = follower.prepare(); follower.resizeReadonly(live.state); assert.deepEqual(readonlyCalls, []);
follower.parsed(pending); assert.deepEqual(readonlyCalls, [[70,20]]);
live.state.info={cols:72,rows:21}; follower.resizeReadonly(live.state); assert.deepEqual(readonlyCalls, [[70,20],[72,21]]);
live.state.phase='disconnected'; follower.update(); live.state.phase='connected';
follower.resizeReadonly(live.state); assert.equal(readonlyCalls.length, 2);
follower.dispose(); follower.parsed(pending); follower.resizeReadonly(live.state); assert.equal(readonlyCalls.length, 2);
'''
        result = subprocess.run(['node', '-e', script, str(p.HERE / 'dsh_terminal_runtime.js')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_clipboard_live_output_only_and_copy_retry(self):
        dsh = shutil.which('dsh')
        if not dsh:
            self.skipTest('DSH not installed')
        modules = Path(dsh).resolve().parents[1] / 'node_modules'
        if not (modules / '@xterm/headless/package.json').exists():
            self.skipTest('xterm headless not installed')
        script = r"""
const assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm'), path=require('node:path');
const {Terminal}=require(path.join(process.argv[1], '@xterm/headless'));
let copied=[], reject=false, fallback=[];
const createElement = tag => ({tag,style:{},children:[],attrs:{},events:{},
  appendChild(child){this.children.push(child);child.parent=this},
  setAttribute(k,v){this.attrs[k]=v}, addEventListener(k,v){this.events[k]=v},
  remove(){if(this.parent) this.parent.children=this.parent.children.filter(x=>x!==this)},
  focus(){}, select(){fallback.push(this.value)} });
const body=createElement('body'); const document={body,activeElement:null,createElement,execCommand:()=>true};
const context={document,navigator:{clipboard:{writeText:async text=>{if(reject)throw Error('blocked');copied.push(text)}}},
 TextDecoder,Uint8Array,atob,setTimeout,clearTimeout};
vm.runInNewContext(fs.readFileSync(process.argv[2],'utf8'),context);
const osc=(text,end='\x07')=>'\x1b]52;c;'+Buffer.from(text).toString('base64')+end;
const write=(t,s)=>new Promise(r=>t.write(s,r)); const flush=()=>new Promise(r=>setImmediate(r));
(async()=>{
 const term=new Terminal({allowProposedApi:true}), node=createElement('div');
 const clip=context.createTerminalClipboard(term,node);
 const data=osc('中文 😀','\x1b\\');
 await write(term,data.slice(0,7));clip.finish(true);await flush();assert.deepEqual(copied,[]);
 await write(term,data.slice(7));clip.finish(true);await flush();assert.deepEqual(copied,['中文 😀']);
 assert.equal(node.children[0].children[0].textContent,'Copied');
 await write(term,osc('snapshot'));clip.finish(false);await flush();assert.deepEqual(copied,['中文 😀']);
 for(const invalid of ['c;?','p;aGVsbG8=','c;','c;%%%','c;/w==']) {
   await write(term,'\x1b]52;'+invalid+'\x07');clip.finish(true);
 }
 await flush();assert.deepEqual(copied,['中文 😀']);
 reject=true;await write(term,osc('retry'));clip.finish(true);await flush();
 assert.equal(node.children[0].children[0].textContent,'Automatic copy was blocked.');
 node.children[0].children[1].events.click();await flush();
 assert.deepEqual(fallback,['retry']);assert.equal(node.children[0].children[0].textContent,'Copied');
 clip.dispose();assert.equal(node.children.length,0);term.dispose();
})().catch(e=>{console.error(e);process.exitCode=1});
"""
        result = subprocess.run(['node', '-e', script, str(modules), str(p.HERE / 'dsh_terminal_clipboard.js')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_force_resize_is_not_suppressed_by_stale_host_size(self):
        dsh = shutil.which('dsh')
        if not dsh:
            self.skipTest('DSH not installed')
        host = Path(dsh).resolve().parents[1] / 'node_modules/@deepseek-ai'
        try:
            model = p.patch_model((host / 'dsh-api-terminal-controller/lib/client.js').read_text())
        except (FileNotFoundError, ValueError):
            self.skipTest('reviewed DSH controller bundle not installed')
        method = model.split(p.FORCE_SIGNATURE_NEW, 1)[1].split('\n\t\t\tsend(attachment, command, bytes) {', 1)[0]
        script = r"""
const assert = require('node:assert/strict');
const method = require('node:fs').readFileSync(0, 'utf8');
const resize = new Function('return ({resize(cols, rows, force = false) {' + method + '}).resize')();
const sent=[]; const attachment={signal:{aborted:false},sequence:0};
const state={writable:true,info:{cols:80,rows:24},environment:{maxCols:200,maxRows:100}};
const self={state:{getSnapshot:()=>state},attachment,send:(_, command)=>{sent.push(command);attachment.sequence=command.sequence}};
resize.call(self,81,24,true);
resize.call(self,80,24,true);
resize.call(self,80,24);
assert.deepEqual(sent.map(({cols,rows})=>[cols,rows]), [[81,24],[80,24]]);
assert.deepEqual(sent.map(({sequence})=>sequence),[1,2]);
"""
        result = subprocess.run(['node', '-e', script], input=method, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_real_xterm_snapshot_modes_when_installed(self):
        dsh = shutil.which('dsh')
        if not dsh:
            self.skipTest('DSH not installed')
        modules = Path(dsh).resolve().parents[1] / 'node_modules'
        for name, version in [('@xterm/headless', '6.0.0'), ('@xterm/addon-serialize', '0.14.0')]:
            manifest = modules / name / 'package.json'
            if not manifest.exists() or json.loads(manifest.read_text()).get('version') != version:
                self.skipTest('reviewed xterm versions not installed')
        script = r'''
const assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm'), path=require('node:path');
const {Terminal}=require(path.join(process.argv[1], '@xterm/headless'));
const {SerializeAddon}=require(path.join(process.argv[1], '@xterm/addon-serialize'));
const ctx={}; vm.runInNewContext(fs.readFileSync(process.argv[2], 'utf8'), ctx);
async function write(t, data) { await new Promise(resolve => t.write(data, resolve)); }
(async()=>{
 for (const seq of [
  '\x1b[?1049h\x1b[?1003h\x1b[?1006h\x1b[?1004h\x1b[?2004h\x1b[?25lhello',
  '\x1b[?1000h\x1b[?1016h\x1b[?2026htext',
  '\x1b[?1006h\x1b[?1006l\x1b[?25l\x1b[?25htext',
  '\x1b[?1006h\x1bcafter reset',
 ]) {
  const a=new Terminal({cols:80, rows:24, allowProposedApi:true}); const s=new SerializeAddon(); a.loadAddon(s);
  await write(a,seq); const b=new Terminal({cols:80, rows:24, allowProposedApi:true});
  await write(b,s.serialize()+ctx.terminalSnapshotModes(a));
  assert.deepEqual(b.modes,a.modes); assert.equal(b.buffer.active.type,a.buffer.active.type);
  assert.equal(b._core.coreMouseService.activeEncoding,a._core.coreMouseService.activeEncoding);
  assert.equal(b._core.coreService.isCursorHidden,a._core.coreService.isCursorHidden);
  if (b._core.coreMouseService.activeEncoding === 'SGR' && b.modes.mouseTrackingMode !== 'none') {
   const reported=[]; b.onData(value=>reported.push(value));
   assert.equal(b._core.coreMouseService.triggerMouseEvent({col:10,row:5,x:0,y:0,button:4,action:0,ctrl:false,alt:false,shift:false}),true);
   assert.equal(b._core.coreMouseService.triggerMouseEvent({col:10,row:5,x:0,y:0,button:0,action:1,ctrl:false,alt:false,shift:false}),true);
   assert.deepEqual(reported,['\x1b[<64;11;6M','\x1b[<0;11;6M']);
  }
  assert.equal(b.buffer.active.getLine(0).translateToString(true),a.buffer.active.getLine(0).translateToString(true));
  a.dispose(); b.dispose();
 }
})().catch(e=>{console.error(e);process.exitCode=1});
'''
        result = subprocess.run(['node', '-e', script, str(modules), str(p.HERE / 'dsh_terminal_snapshot.js')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
