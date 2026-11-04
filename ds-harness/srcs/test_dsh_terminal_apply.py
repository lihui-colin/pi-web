"""Terminal patch installation and behavior in isolated fixtures."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from patches import dsh_terminal_apply as p


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
        self.front.write_text('\n'.join([p.SCREEN_REF, p.SETUP, p.CLEANUP, p.FONT_FIT, p.WRITE, p.VISIBLE, p.PHASE, p.RUNTIME_ANCHOR, p.CLIP_HELPER, p.CLIP_SETUP, p.CLIP_CLEANUP]))
        self.model.write_text('\n'.join([p.FORCE_SIGNATURE, p.FORCE_CHECK]))
        self.backend.write_text('\n'.join([p.SNAPSHOT_ANCHOR, p.SERIALIZE]))

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
