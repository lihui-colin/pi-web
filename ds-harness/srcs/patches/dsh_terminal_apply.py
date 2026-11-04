#!/usr/bin/env python3
"""Restore terminal snapshot modes and repaint incremental TUIs on reattachment."""
import argparse
import json
from pathlib import Path
import shutil

if __package__:
    from .ds_bot_apply import publish, replace_once
else:
    from ds_bot_apply import publish, replace_once

HERE = Path(__file__).resolve().parent
RUNTIME = (HERE / 'dsh_terminal_runtime.js').read_text().strip() + '\n'
SNAPSHOT = (HERE / 'dsh_terminal_snapshot.js').read_text().strip() + '\n'
CLIPBOARD = (HERE / 'dsh_terminal_clipboard.js').read_text().strip() + '\n'

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
RUNTIME_NEW = RUNTIME + RUNTIME_ANCHOR
FORCE_SIGNATURE = '\t\t\tresize(cols, rows) {'
FORCE_SIGNATURE_NEW = '\t\t\tresize(cols, rows, force = false) {'
FORCE_CHECK = '\t\t\t\tif (state.info.cols === cols && state.info.rows === rows) return;'
FORCE_CHECK_NEW = '\t\t\t\tif (!force && state.info.cols === cols && state.info.rows === rows) return;'
SNAPSHOT_ANCHOR = 'var BrowserTerminal = class {'
SNAPSHOT_NEW = SNAPSHOT + SNAPSHOT_ANCHOR
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


def apply_replacements(text, replacements):
    for old, new in replacements:
        text = replace_once(text, old, new)
    return text


def patch_frontend(text):
    # Normalize a previously installed clipboard fix back to the redraw-only
    # baseline before applying it again, so both generations remain idempotent.
    if CLIP_FINISH_NEW in text:
        for old, fixed in reversed([(CLIP_HELPER, CLIP_HELPER_NEW), (CLIP_REF, CLIP_REF_NEW),
            (CLIP_SETUP, CLIP_SETUP_NEW), (CLIP_CLEANUP, CLIP_CLEANUP_NEW),
            (CLIP_CAPTURE, CLIP_CAPTURE_NEW), (CLIP_FINISH, CLIP_FINISH_NEW)]):
            if text.count(fixed) != 1:
                raise ValueError('Incomplete terminal clipboard patch; inspect before applying')
            text = text.replace(fixed, old, 1)
    text = apply_replacements(text, [(SCREEN_REF, SCREEN_REF_NEW), (SETUP, SETUP_NEW),
        (CLEANUP, CLEANUP_NEW), (FONT_FIT, FONT_FIT_NEW), (WRITE, WRITE_NEW),
        (VISIBLE, VISIBLE_NEW), (PHASE, PHASE_NEW), (RUNTIME_ANCHOR, RUNTIME_NEW)])
    return apply_replacements(text, [(CLIP_HELPER, CLIP_HELPER_NEW), (CLIP_REF, CLIP_REF_NEW),
        (CLIP_SETUP, CLIP_SETUP_NEW), (CLIP_CLEANUP, CLIP_CLEANUP_NEW),
        (CLIP_CAPTURE, CLIP_CAPTURE_NEW), (CLIP_FINISH, CLIP_FINISH_NEW)])


def patch_model(text):
    return apply_replacements(text, [(FORCE_SIGNATURE, FORCE_SIGNATURE_NEW), (FORCE_CHECK, FORCE_CHECK_NEW)])


def patch_host(text):
    return apply_replacements(text, [(SNAPSHOT_ANCHOR, SNAPSHOT_NEW), (SERIALIZE, SERIALIZE_NEW)])


def plan_changes(host=None):
    if host is None:
        executable = shutil.which('dsh')
        if executable is None:
            raise ValueError('dsh executable not found')
        host = Path(executable).resolve().parents[1] / 'node_modules/@deepseek-ai'
    host = Path(host)
    packages = [
        (host / 'dsh-client-ui-sidebar-terminal', '@deepseek-ai/dsh-client-ui-sidebar-terminal', '0.2.2-alpha.2'),
        (host / 'dsh-api-terminal-controller', '@deepseek-ai/dsh-api-terminal-controller', '0.2.2-alpha.2'),
        (host.parent / '@xterm/headless', '@xterm/headless', '6.0.0'),
        (host.parent / '@xterm/addon-serialize', '@xterm/addon-serialize', '0.14.0'),
    ]
    for directory, name, version in packages:
        manifest = json.loads((directory / 'package.json').read_text())
        if (manifest.get('name'), manifest.get('version')) != (name, version):
            raise ValueError(f'Unsupported package {manifest.get("name")}@{manifest.get("version")}; expected {name}@{version}. Review upstream before applying.')
    paths = [(host / 'dsh-client-ui-sidebar-terminal/lib/client.terminal.js', patch_frontend),
             (host / 'dsh-api-terminal-controller/lib/client.js', patch_model),
             (host / 'dsh-api-terminal-controller/lib/index.js', patch_host)]
    changes = []
    for path, transform in paths:
        original = path.read_text()
        changes.append((path, original, transform(original)))
    return changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Validate without writing')
    parser.add_argument('--host-dir', type=Path, help='Installed DSH node_modules/@deepseek-ai directory')
    args = parser.parse_args()
    changes = plan_changes(args.host_dir)
    pending = [path for path, original, fixed in changes if original != fixed]
    if args.check:
        if pending:
            for path in pending:
                print(f'Needs patch: {path}')
            raise SystemExit(1)
        print('DSH terminal compatibility fixes are present.')
        return
    publish(changes)
    print('DSH terminal compatibility fixes applied.')
    if pending:
        print('Host changes require a planned service restart; frontend resources require reload. No service restarted.')


if __name__ == '__main__':
    main()
