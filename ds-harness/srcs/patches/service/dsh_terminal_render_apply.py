#!/usr/bin/env python3
"""Offer official rc.1 TerminalScreen frames directly to its exclusive xterm sink."""
from pathlib import Path
if not __package__:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from patches.common import patch_cli, undo_replacements
from patches.service import dsh_terminal_apply as legacy
from patches.service.dsh_terminal_assets import plan_terminal_frontend

HERE = Path(__file__).resolve().parent
HELPER = (HERE / 'dsh_terminal_render.js').read_text().strip() + '\n'
ANCHOR = legacy.CLIP_HELPER
REGISTER = '\t\t\t\tlastRevision.current = 0;'
REGISTER_NEW = REGISTER + '\n\t\t\t\tconst renderSink = dshBindTerminalRenderSink(model, xterm);'
CLEANUP = '\t\t\t\t\tobserver.disconnect();'
CLEANUP_NEW = '\t\t\t\t\trenderSink.dispose();\n' + CLEANUP
RENDER = '\t\t\t\tconst render = state.render;'
RENDER_NEW = '\t\t\t\tif (xterm.dshRenderGate) return;\n' + RENDER
VISIBLE_NEW = '''\t\t\t\tif (xterm.dshRenderGate) {
\t\t\t\t\txterm.dshRenderGate.visibility(visible, () => {\n\t\t\t\t\t\tconst live = current.current;\n\t\t\t\t\t\tif (live.visible && live.state.writable && element.current?.clientWidth && element.current.clientHeight) fitScreen(xterm, fit.current, live.state, model);\n\t\t\t\t\t});
\t\t\t\t\treturn;
\t\t\t\t}
''' + legacy.VISIBLE
FIT = '\t\t\tconst dimensions = fit.proposeDimensions();'
FIT_NEW = '''\t\t\tif (xterm.dshRenderGate) {
\t\t\t\tconst gate = xterm.dshRenderGate;
\t\t\t\tgate.fit(() => {
\t\t\t\t\tdelete xterm.dshRenderGate;
\t\t\t\t\ttry { fitScreen(xterm, fit, state, model); }
\t\t\t\t\tfinally { xterm.dshRenderGate = gate; }
\t\t\t\t});
\t\t\t\treturn;
\t\t\t}
''' + FIT
EDITS = [(REGISTER, REGISTER_NEW), (CLEANUP, CLEANUP_NEW), (RENDER, RENDER_NEW), (legacy.VISIBLE, VISIBLE_NEW), (FIT, FIT_NEW)]


def patch(text):
    # Preserve all clipboard/tools/redraw semantics of the separately maintained
    # legacy enhancement. Only an exactly validated complete candidate may skip.
    if 'createTerminalRedraw' in text or 'createTerminalClipboard' in text:
        if 'dshBindTerminalRenderSink' in text or legacy.patch_frontend(text) != text:
            raise ValueError('Mixed legacy terminal render candidate')
        return text
    if 'dshBindTerminalRenderSink' in text:
        if text.count(HELPER) != 1 or text.count('dshBindTerminalRenderSink') != 2:
            raise ValueError('Mixed direct terminal render helper')
        base = undo_replacements(text.replace(HELPER, '', 1), EDITS,
                                 error='Mixed direct terminal render anchors')
        if patch(base) != text:
            raise ValueError('Unknown direct terminal renderer candidate')
        return text
    if text.count(ANCHOR) != 1:
        raise ValueError('Unknown TerminalScreen anchor')
    for old, new in EDITS:
        if text.count(old) != 1:
            raise ValueError('Unknown TerminalScreen render anchors')
        text = text.replace(old, new, 1)
    return text.replace(ANCHOR, HELPER + ANCHOR, 1)


def plan_changes(host=None, *, read_text=Path.read_text):
    return plan_terminal_frontend(host, patch, read_text=read_text)


def main():
    patch_cli(plan_changes, __doc__, {'host': '--host-dir'}, 'Terminal direct renderer verified')


if __name__ == '__main__':
    main()
