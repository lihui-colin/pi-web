#!/usr/bin/env python3
"""Expose a session-scoped extension inside the native context details panel."""
from pathlib import Path

if not __package__:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from patches.common import apply_replacements, plan_host_patch, patch_cli

SIGNATURE = 'function ContextMeter({ useProjection, t }) {'
SIGNATURE_NEW = 'function ContextMeter({ useProjection, t, renderSlot }) {'
DECLARE = '\t\t\t\t\t"conversation.composer.dock": {'
DECLARE_NEW = ('\t\t\t\t\t"conversation.context.details": {\n'
               '\t\t\t\t\t\tkind: "list",\n\t\t\t\t\t\tscope: "session"\n'
               '\t\t\t\t\t},\n' + DECLARE)
PANEL_END = ('\t\t\t\t\t\t\t}, row.key))\n'
             '\t\t\t\t\t\t})\n\t\t\t\t\t]\n'
             '\t\t\t\t}), document.body)]')
PANEL_END_NEW = PANEL_END.replace(
    '\t\t\t\t\t\t})\n\t\t\t\t\t]',
    '\t\t\t\t\t\t}),\n'
    '\t\t\t\t\t\trenderSlot?.("conversation.context.details", {}, { fallback: null })\n'
    '\t\t\t\t\t]')


def patch(text):
    return apply_replacements(text, ((SIGNATURE, SIGNATURE_NEW), (DECLARE, DECLARE_NEW),
                                     (PANEL_END, PANEL_END_NEW)))


def plan_changes(host=None, *, read_text=Path.read_text):
    return plan_host_patch(host, 'dsh-client-ui-conversation', patch,
                           versions=('0.2.2-alpha.2', '0.2.2-rc.1'), read_text=read_text)


if __name__ == '__main__':
    patch_cli(plan_changes, __doc__, {'host': '--host-dir'}, 'Context details extension verified')
