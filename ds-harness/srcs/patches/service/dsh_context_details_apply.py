#!/usr/bin/env python3
"""Expose a session-scoped extension inside the native context details panel."""
from pathlib import Path

if not __package__:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from patches.common import apply_replacements, plan_host_patch, patch_cli

SIGNATURE = 'function ContextMeter({ useProjection, t }) {'
SIGNATURE_LEGACY = 'function ContextMeter({ useProjection, t, renderSlot }) {'
SIGNATURE_NEW = 'function ContextMeter({ useProjection, t, renderSlot, dshSessionInfoOwner, dshSessionInfoVisible = true }) {'
VISIBILITY = 'if (!available && open) setOpen(false);\n\t\t\t}, [available, open]);'
VISIBILITY_NEW = 'if ((!available || !dshSessionInfoVisible) && open) setOpen(false);\n\t\t\t}, [available, open, dshSessionInfoVisible]);'
PORTAL = 'open && (0, react_dom.createPortal)((0, react_jsx_runtime.jsxs)("div", {'
PORTAL_NEW = 'open && dshSessionInfoVisible && (0, react_dom.createPortal)((0, react_jsx_runtime.jsxs)("div", {'
PANEL = '\t\t\t\t\tref: panelRef,\n\t\t\t\t\tclassName: ContextMeter_module_css_default.panel,'
PANEL_NEW = PANEL.replace('ref: panelRef,', 'ref: panelRef,\n\t\t\t\t\t"data-dsh-session-info-owner": dshSessionInfoOwner,')
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
    if SIGNATURE_LEGACY in text:
        # Upgrade only the complete previously published extension shape.
        if (text.count(SIGNATURE_LEGACY) != 1 or SIGNATURE in text or SIGNATURE_NEW in text
                or text.count(DECLARE_NEW) != 1 or text.count(PANEL_END_NEW) != 1
                or text.count(PANEL) != 1 or PANEL_NEW in text
                or text.count(VISIBILITY) != 1 or text.count(PORTAL) != 1
                or VISIBILITY_NEW in text or PORTAL_NEW in text):
            raise ValueError('Unknown or partial context details extension')
        text = apply_replacements(text, ((VISIBILITY, VISIBILITY_NEW), (PORTAL, PORTAL_NEW)))
        text = text.replace(SIGNATURE_LEGACY, SIGNATURE_NEW, 1).replace(PANEL, PANEL_NEW, 1)
    elif SIGNATURE_NEW in text:
        if (text.count(SIGNATURE_NEW) != 1 or text.count(PANEL_NEW) != 1
                or text.count(DECLARE_NEW) != 1 or text.count(PANEL_END_NEW) != 1
                or text.count(VISIBILITY_NEW) != 1 or text.count(PORTAL_NEW) != 1):
            raise ValueError('Unknown or partial context details ownership')
    return apply_replacements(text, ((SIGNATURE, SIGNATURE_NEW), (DECLARE, DECLARE_NEW),
                                     (PANEL_END, PANEL_END_NEW), (PANEL, PANEL_NEW),
                                     (VISIBILITY, VISIBILITY_NEW), (PORTAL, PORTAL_NEW)))


def plan_changes(host=None, *, read_text=Path.read_text):
    return plan_host_patch(host, 'dsh-client-ui-conversation', patch,
                           versions=('0.2.2-alpha.2', '0.2.2-rc.1'), read_text=read_text)


if __name__ == '__main__':
    patch_cli(plan_changes, __doc__, {'host': '--host-dir'}, 'Context details extension verified')
