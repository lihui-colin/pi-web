#!/usr/bin/env python3
"""Apply version-checked DSH terminal recovery, input and browser enhancements."""
import hashlib
import json
from pathlib import Path

if not __package__:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from patches.common import (apply_replacements, host_directory, publish, read_change,
                            replace_once, undo_replacements, verify_package, patch_cli,
                            vendor_addon as embed_addon)

HERE = Path(__file__).resolve().parent
RUNTIME = (HERE / 'dsh_terminal_runtime.js').read_text().strip() + '\n'
SNAPSHOT = (HERE / 'dsh_terminal_snapshot.js').read_text().strip() + '\n'
CLIPBOARD = (HERE / 'dsh_terminal_clipboard.js').read_text().strip() + '\n'
KEYBOARD = (HERE / 'dsh_terminal_keyboard.js').read_text().strip() + '\n'
QUERIES = (HERE / 'dsh_terminal_queries.js').read_text().strip() + '\n'
TOOLS = (HERE / 'dsh_terminal_tools.js').read_text().strip() + '\n'


def vendor_addon(filename, digest, export):
    return embed_addon(HERE / 'vendor' / filename, digest, export)


ADDONS = vendor_addon('addon-search-0.16.0.js',
    '7bc1b8c7b3549411f6f6f779524c4ded6ca621fd80d64b40a70ae7c78aefbf55', 'SearchAddon') + vendor_addon(
    'addon-web-links-0.12.0.js', 'b74864125ef3889753b94e61eb4dabb99b2a27f920f0c9a7bd53cbe6d10f032a', 'WebLinksAddon')
FRONT_HELPERS = RUNTIME + KEYBOARD + QUERIES + ADDONS + TOOLS
HOST_HELPERS = SNAPSHOT + KEYBOARD + QUERIES

SCREEN_REF = '\t\t\tconst lastRevision = (0, react.useRef)(0);'
SCREEN_REF_NEW = SCREEN_REF + '\n\t\t\tconst redraw = (0, react.useRef)();'
SETUP = '''\t\t\t\tconst measure = () => {
\t\t\t\t\tif (!current.current.visible || !current.current.state.writable || node.clientWidth === 0 || node.clientHeight === 0) return;
\t\t\t\t\tfitScreen(xterm, addon, current.current.state, model);
\t\t\t\t};'''
SETUP_NEW = '''\t\t\t\tredraw.current = createTerminalRedraw(xterm, addon, node, model, () => current.current);
\t\t\t\tconst measure = () => redraw.current?.update();'''
CLEANUP = '''\t\t\t\t\tobserver.disconnect();
\t\t\t\t\tinput.dispose();'''
CLEANUP_NEW = '''\t\t\t\t\tobserver.disconnect();
\t\t\t\t\tredraw.current?.dispose();
\t\t\t\t\tredraw.current = void 0;
\t\t\t\t\tinput.dispose();'''
FONT_FIT = '''\t\t\t\tconst { state: live, visible: shown } = current.current;
\t\t\t\tif (shown && live.writable && element.current.clientWidth && element.current.clientHeight) fitScreen(xterm, fit.current, live, model);'''
FONT_FIT_NEW = '''\t\t\t\tredraw.current?.update(); // Refit after a terminal font change.'''
WRITE = '''\t\t\t\tif (render.frame.type === "snapshot") {
\t\t\t\t\txterm.reset();
\t\t\t\t\txterm.resize(render.frame.info.cols, render.frame.info.rows);
\t\t\t\t}
\t\t\t\txterm.write(render.frame.type === "snapshot" ? render.frame.screen : render.frame.data, () => {
\t\t\t\t\tmodel.acknowledge(render.revision);
\t\t\t\t});'''
WRITE_NEW = '''\t\t\t\tlet snapshotToken;
\t\t\t\tconst redrawForFrame = redraw.current;
\t\t\t\tif (render.frame.type === "snapshot") {
\t\t\t\t\tsnapshotToken = redrawForFrame?.prepare();
\t\t\t\t\txterm.reset();
\t\t\t\t\txterm.resize(render.frame.info.cols, render.frame.info.rows);
\t\t\t\t}
\t\t\t\txterm.write(render.frame.type === "snapshot" ? render.frame.screen : render.frame.data, () => {
\t\t\t\t\tif (snapshotToken !== void 0) redrawForFrame?.parsed(snapshotToken);
\t\t\t\t\tmodel.acknowledge(render.revision);
\t\t\t\t});'''
VISIBLE = '''\t\t\t\tif (visible && state.writable && element.current?.clientWidth && element.current.clientHeight) fitScreen(xterm, fit.current, state, model);
\t\t\t\telse if (state.info !== void 0 && !state.writable) xterm.resize(state.info.cols, state.info.rows);'''
VISIBLE_NEW = '''\t\t\t\tredraw.current?.update();
\t\t\t\tif (state.phase === "connected" && state.info !== void 0 && !state.writable) xterm.resize(state.info.cols, state.info.rows);'''
PHASE = '''\t\t\t\tvisible,
\t\t\t\tstate.writable,
\t\t\t\tstate.info?.cols,'''
PHASE_NEW = '''\t\t\t\tvisible,
\t\t\t\tstate.phase,
\t\t\t\tstate.writable,
\t\t\t\tstate.info?.cols,'''
RUNTIME_ANCHOR = '\t\tfunction fitScreen(xterm, fit, state, model) {'
RUNTIME_NEW = FRONT_HELPERS + RUNTIME_ANCHOR
FORCE_SIGNATURE = '\t\t\tresize(cols, rows) {'
FORCE_SIGNATURE_NEW = '\t\t\tresize(cols, rows, force = false) {'
FORCE_CHECK = '\t\t\t\tif (state.info.cols === cols && state.info.rows === rows) return;'
FORCE_CHECK_NEW = '\t\t\t\tif (!force && state.info.cols === cols && state.info.rows === rows) return;'
SNAPSHOT_ANCHOR = 'var BrowserTerminal = class {'
SNAPSHOT_NEW = HOST_HELPERS + SNAPSHOT_ANCHOR
SERIALIZE = '\t\t\t\tscreen: this.serializer.serialize(),'
SERIALIZE_NEW = '\t\t\t\tscreen: this.serializer.serialize() + terminalSnapshotModes(this.screen),'

CLIP_HELPER = '\t\tfunction TerminalScreen({ state, model, visible, label, theme }) {'
CLIP_HELPER_NEW = CLIPBOARD + CLIP_HELPER
CLIP_REF = '\t\t\tconst redraw = (0, react.useRef)();'
CLIP_REF_NEW = CLIP_REF + '\n\t\t\tconst clipboard = (0, react.useRef)();'
CLIP_SETUP = '\t\t\t\tcolors.current = palette;'
CLIP_SETUP_NEW = CLIP_SETUP + '\n\t\t\t\tclipboard.current = createTerminalClipboard(xterm, node);'
CLIP_CLEANUP = '\t\t\t\tcursor.dispose();\n\t\t\t\t\tpalette.dispose();'
CLIP_CLEANUP_NEW = '\t\t\t\tcursor.dispose();\n\t\t\t\t\tclipboard.current?.dispose();\n\t\t\t\t\tclipboard.current = void 0;\n\t\t\t\t\tpalette.dispose();'
CLIP_CAPTURE = '\t\t\t\txterm.write(render.frame.type === "snapshot" ? render.frame.screen : render.frame.data, () => {'
CLIP_CAPTURE_NEW = '\t\t\t\tconst clipboardForFrame = clipboard.current;\n' + CLIP_CAPTURE
CLIP_FINISH = '\t\t\t\t\tmodel.acknowledge(render.revision);'
CLIP_FINISH_NEW = '''\t\t\t\t\tconst live = current.current;
\t\t\t\t\tclipboardForFrame?.finish(clipboard.current === clipboardForFrame && render.frame.type === "output"
\t\t\t\t\t\t&& live.visible && live.state.writable && live.state.phase === "connected" && live.state.render?.revision === render.revision);
\t\t\t\t\tmodel.acknowledge(render.revision);'''

PROPOSED = '\t\t\t\t\tminimumContrastRatio: 4.5,'
TOOLS_RESET = '\t\t\t\t\txterm.reset();'
TOOLS_RESET_NEW = '\t\t\t\t\tterminalTools.current?.reset();\n' + TOOLS_RESET
TOOLS_REPLACEMENTS = [
    (CLIP_REF_NEW, CLIP_REF_NEW + '\n\t\t\tconst terminalTools = (0, react.useRef)();'),
    (CLIP_SETUP_NEW, CLIP_SETUP_NEW + '\n\t\t\t\tterminalTools.current = createTerminalTools(xterm, node, model, () => current.current);'),
    (CLIP_CLEANUP_NEW, CLIP_CLEANUP_NEW.replace('\t\t\t\t\tclipboard.current?.dispose();',
        '\t\t\t\t\tterminalTools.current?.dispose();\n\t\t\t\t\tterminalTools.current = void 0;\n\t\t\t\t\tclipboard.current?.dispose();')),
    (TOOLS_RESET, TOOLS_RESET_NEW),
    (PROPOSED, '\t\t\t\t\tallowProposedApi: true,\n' + PROPOSED),
]
HOST_SETUP = '\t\tthis.screen.loadAddon(this.serializer);'
HOST_WRITE = '\t\t\t\tthis.screen.write(data, resolve);\n\t\t\t});'
HOST_DISPOSE = '\t\t\tthis.screen.dispose();'
PROTOCOL_SERIALIZE = '\t\t\t\tscreen: this.terminalProtocol.snapshot(this.serializer.serialize() + terminalSnapshotModes(this.screen)),'
HOST_REPLACEMENTS = [
    (SERIALIZE_NEW, PROTOCOL_SERIALIZE),
    (HOST_SETUP, HOST_SETUP + '\n\t\tthis.terminalProtocol = createTerminalHostProtocol(this.screen, handle, () => !this.exited && this.closing === void 0 && this.info.state === "running");'),
    (HOST_WRITE, HOST_WRITE + '\n\t\t\tawait this.terminalProtocol.flush();'),
    (HOST_DISPOSE, '\t\t\tthis.terminalProtocol.dispose();\n' + HOST_DISPOSE),
]


# Normalize the complete published clipboard/tools write before upgrading it.
# Keep these exact anchors so partial or locally modified installations fail closed.
FENCE_WRITE_OLD = apply_replacements(WRITE_NEW, [(CLIP_CAPTURE, CLIP_CAPTURE_NEW),
    (CLIP_FINISH, CLIP_FINISH_NEW), (TOOLS_RESET, TOOLS_RESET_NEW)])
FENCE_WRITE = '''\t\t\t\tlet active = true;
\t\t\t\tconst redrawForFrame = redraw.current;
\t\t\t\tconst clipboardForFrame = clipboard.current;
\t\t\t\tconst isCurrentFrame = () => active && terminal.current === xterm
\t\t\t\t\t&& redraw.current === redrawForFrame && clipboard.current === clipboardForFrame
\t\t\t\t\t&& current.current.state.phase === "connected"
\t\t\t\t\t&& current.current.state.render === render && lastRevision.current === render.revision
\t\t\t\t\t&& model.pendingRender?.revision === render.revision;
\t\t\t\tconst snapshotToken = isCurrentFrame() && render.frame.type === "snapshot" ? redrawForFrame?.prepare() : void 0;
\t\t\t\tconst writeFrame = () => {
\t\t\t\t\tif (!isCurrentFrame()) return;
\t\t\t\t\tif (render.frame.type === "snapshot") {
\t\t\t\t\t\tterminalTools.current?.reset();
\t\t\t\t\t\txterm.reset();
\t\t\t\t\t\txterm.resize(render.frame.info.cols, render.frame.info.rows);
\t\t\t\t\t\tclipboardForFrame?.finish(false);
\t\t\t\t\t}
\t\t\t\t\txterm.write(render.frame.type === "snapshot" ? render.frame.screen : render.frame.data, () => {
\t\t\t\t\t\tif (!isCurrentFrame()) { clipboardForFrame?.finish(false); return; }
\t\t\t\t\t\tif (snapshotToken !== void 0) redrawForFrame?.parsed(snapshotToken);
\t\t\t\t\t\tconst live = current.current;
\t\t\t\t\t\tclipboardForFrame?.finish(render.frame.type === "output" && live.visible && live.state.writable);
\t\t\t\t\t\tmodel.acknowledge(render.revision);
\t\t\t\t\t});
\t\t\t\t};
\t\t\t\t// Drain writes from cancelled generations before resetting the parser.
\t\t\t\tif (isCurrentFrame()) {
\t\t\t\t\tif (render.frame.type === "snapshot") xterm.write("", writeFrame);
\t\t\t\t\telse writeFrame();
\t\t\t\t}
\t\t\t\treturn () => { active = false; };'''
FENCE_REPLACEMENTS = [
    (FENCE_WRITE_OLD, FENCE_WRITE),
    ('\t\t\t}, [state.render, model]);', '\t\t\t}, [state.render, state.phase, model]);'),
    (VISIBLE_NEW, '\t\t\t\tredraw.current?.update();\n\t\t\t\tredraw.current?.resizeReadonly(state);'),
]


def upgrade_helpers(text, marker, signature, anchor, current, legacy_digest):
    if marker not in text:
        if signature in text:
            raise ValueError('Unrecognized terminal helper block; inspect before applying')
        return text
    if text.count(marker) != 1 or text.count(signature) != 1 or text.count(anchor) != 1:
        raise ValueError('Ambiguous terminal helper block')
    start, end = text.index(marker), text.index(anchor)
    previous = text[start:end]
    accepted = (legacy_digest,) if isinstance(legacy_digest, str) else legacy_digest
    if previous != current and hashlib.sha256(previous.encode()).hexdigest() not in accepted:
        raise ValueError('Unknown terminal helper revision; inspect before applying')
    return text[:start] + current + text[end:]


def patch_frontend(text):
    if (FENCE_WRITE in text) != (FRONT_HELPERS in text):
        raise ValueError('Mixed terminal parser fence and helper revisions')
    if FENCE_WRITE in text:
        text = undo_replacements(text, FENCE_REPLACEMENTS)
    text = upgrade_helpers(text, '// Snapshot parsing must finish before', 'function createTerminalRedraw(', RUNTIME_ANCHOR,
        FRONT_HELPERS, ('b28e1ca4c854859cb7c1243cca162265f73704c683923255c401d5169a2a5ce6',
                        'db4e98d7e4f70c108b951226de4808cd8d02f9aeeb288e205a9f3a634a7255a7'))
    if TOOLS_RESET_NEW in text:
        text = undo_replacements(text, TOOLS_REPLACEMENTS)
    # Normalize a previously installed clipboard fix back to the redraw-only
    # baseline before applying it again, so both generations remain idempotent.
    if CLIP_FINISH_NEW in text:
        text = undo_replacements(text, [(CLIP_HELPER, CLIP_HELPER_NEW), (CLIP_REF, CLIP_REF_NEW),
            (CLIP_SETUP, CLIP_SETUP_NEW), (CLIP_CLEANUP, CLIP_CLEANUP_NEW),
            (CLIP_CAPTURE, CLIP_CAPTURE_NEW), (CLIP_FINISH, CLIP_FINISH_NEW)])
    text = apply_replacements(text, [(SCREEN_REF, SCREEN_REF_NEW), (SETUP, SETUP_NEW),
        (CLEANUP, CLEANUP_NEW), (FONT_FIT, FONT_FIT_NEW), (WRITE, WRITE_NEW),
        (VISIBLE, VISIBLE_NEW), (PHASE, PHASE_NEW), (RUNTIME_ANCHOR, RUNTIME_NEW)])
    text = apply_replacements(text, [(CLIP_HELPER, CLIP_HELPER_NEW), (CLIP_REF, CLIP_REF_NEW),
        (CLIP_SETUP, CLIP_SETUP_NEW), (CLIP_CLEANUP, CLIP_CLEANUP_NEW),
        (CLIP_CAPTURE, CLIP_CAPTURE_NEW), (CLIP_FINISH, CLIP_FINISH_NEW)])
    text = apply_replacements(text, TOOLS_REPLACEMENTS)
    return apply_replacements(text, FENCE_REPLACEMENTS)


def patch_model(text):
    return apply_replacements(text, [(FORCE_SIGNATURE, FORCE_SIGNATURE_NEW), (FORCE_CHECK, FORCE_CHECK_NEW)])


def patch_host(text):
    text = upgrade_helpers(text, '// xterm serialize 0.14 preserves', 'function terminalSnapshotModes(', SNAPSHOT_ANCHOR,
        HOST_HELPERS, 'fe5167d48cfa51957a9aab6479dc98fa002e8eace88010d29c7a5098a53f7f19')
    if PROTOCOL_SERIALIZE in text:
        text = undo_replacements(text, HOST_REPLACEMENTS)
    text = apply_replacements(text, [(SNAPSHOT_ANCHOR, SNAPSHOT_NEW), (SERIALIZE, SERIALIZE_NEW)])
    return apply_replacements(text, HOST_REPLACEMENTS)


def plan_changes(host=None, *, read_text=Path.read_text):
    host = host_directory(host)
    version = json.loads((host / 'dsh-client-ui-sidebar-terminal/package.json').read_text()).get('version')
    if version not in ('0.2.2-alpha.2', '0.2.2-rc.1'):
        raise ValueError(f'Unsupported terminal package version {version}; review upstream before applying')
    packages = [
        (host / 'dsh-client-ui-sidebar-terminal', '@deepseek-ai/dsh-client-ui-sidebar-terminal', version),
        (host / 'dsh-api-terminal-controller', '@deepseek-ai/dsh-api-terminal-controller', version),
        (host.parent / '@xterm/headless', '@xterm/headless', '6.0.0'),
        (host.parent / '@xterm/addon-serialize', '@xterm/addon-serialize', '0.14.0'),
    ]
    for directory, name, required_version in packages:
        verify_package(directory, name, (required_version,))
    frontend = host / 'dsh-client-ui-sidebar-terminal/lib/client.terminal.js'
    original = read_text(frontend)
    if 'dshBindTerminalRenderSink' in original:
        # Preserve the explicitly deployed direct mode. Adding the older tools
        # here would create a mixed UI that the later renderer planner rejects.
        from patches.service import dsh_terminal_render_apply as direct
        if version != '0.2.2-rc.1':
            raise ValueError('Direct terminal renderer requires reviewed rc.1 packages')
        direct.patch(original)  # Validate current or exactly reviewed older helper.
        return []
    return [(frontend, original, patch_frontend(original)),
            read_change(host / 'dsh-api-terminal-controller/lib/client.js', patch_model, read_text=read_text),
            read_change(host / 'dsh-api-terminal-controller/lib/index.js', patch_host, read_text=read_text)]


def main():
    patch_cli(plan_changes, __doc__, {'host': '--host-dir'},
              'DSH terminal compatibility verified')


if __name__ == '__main__':
    main()
