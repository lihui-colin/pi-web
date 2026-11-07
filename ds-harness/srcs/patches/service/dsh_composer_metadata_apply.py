#!/usr/bin/env python3
"""Collapse the native DSH composer metadata behind a session-info disclosure."""
import json
from pathlib import Path

if not __package__:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from patches.common import host_directory, publish, read_change, replace_once, verify_package, patch_cli

HELPER = Path(__file__).with_name('dsh_composer_metadata.js').read_text().strip() + '\n'
ANCHOR = '\t\tconst InputBar = (0, react.memo)(function InputBar('
OLD = '''					(0, react_jsx_runtime.jsxs)("div", {
						className: InputBar_module_css_default.dock,
						"data-composer-dock": true,
						children: [variant === "composer" && input !== void 0 && sessionId !== void 0 ? renderSlot("conversation.composer.dock", {}) : null, activity ? null : (0, react_jsx_runtime.jsx)(ContextMeter, {
							useProjection,
							t
						})]
					})'''
NEW = ('\t\t\t\t\t(0, react_jsx_runtime.jsx)(DshComposerMetadata, {\n'
       '\t\t\t\t\t\t\t\t\t\t\t\tchildren: ' + OLD.lstrip() + '\n\t\t\t\t\t}, sessionId)')
TRANSLATIONS = {'运行中…': '会话信息', 'Running…': 'Session info', '実行中…': 'セッション情報', 'Corriendo…': 'Información de sesión', 'Courir…': 'Informations de session', 'Laufen…': 'Sitzungsinformationen', 'Бег…': 'Сведения о сеансе', 'Correndo…': 'Informações da sessão'}


WRAPPER = 'const InputBar = (0, react.memo)(function InputBar(props) {\n  return (0, react_jsx_runtime.jsx)(DshComposerFrame, {\n    children: (0, react_jsx_runtime.jsx)(DshInputBar, props)\n  }, props.sessionId);\n});\n'
TRAILING = '\t\t\t\t\t\t\t\t\tclassName: clsx(InputBar_module_css_default.trailing, activity && InputBar_module_css_default.trailingActive),\n\t\t\t\t\t\t\t\t\tchildren: ['
TRAILING_NEW = TRAILING + '\n\t\t\t\t\t\t\t\t\t\t(0, react_jsx_runtime.jsx)(DshSessionInfoTrigger, { useProjection, t }),'
REGISTER_ANCHOR = '\t\t\tconst registerComposerBar = () => slots.register({'
REGISTER_TRIGGER = '''\t\t\tslots.inject("conversation.input.right", () => slots.register({
                name: "conversation.input.right",
                id: "dsh-session-info",
                order: -100,
                locale: NS
            }, DshSessionInfoTrigger));
'''

PREVIOUS_STYLE = r'''const dshSessionInfoCss = `
[data-dsh-session-info]{box-sizing:border-box;min-width:0;width:100%;flex:none}
[data-dsh-session-info][hidden]{display:none!important}
[data-dsh-session-info][data-bypass]{display:contents}
[data-dsh-session-info-trigger]{box-sizing:border-box;display:inline-grid;place-items:center;flex:none;width:32px;height:32px;padding:4px;border:0;border-radius:50%;background:transparent;color:var(--dsw-alias-label-tertiary,#92989c);cursor:pointer}
[data-dsh-session-info-trigger]:focus-visible{outline:2px solid var(--dsw-alias-state-business-primary,#6b9cff);outline-offset:2px}
[data-dsh-session-info-trigger][aria-expanded=true]{background:var(--dsw-alias-interactive-bg-hover,rgba(128,128,128,.15))}
[data-dsh-session-info] [data-mobile-nav="stats-ring"]{position:static!important;left:auto!important;top:auto!important;transform:none!important}
[data-dsh-session-info] [data-mobile-nav="stats-ring-reserve"]{display:none!important}
`;'''
_STYLE_START = HELPER.index('const dshSessionInfoCss = `')
CURRENT_STYLE = HELPER[_STYLE_START:HELPER.index('`;', _STYLE_START) + 2]

PREVIOUS_TRIGGER_ICON = '    children: (0, react_jsx_runtime.jsxs)("svg", {\n      width: 22, height: 22, viewBox: "0 0 24 24", "aria-hidden": true,\n      children: [\n        (0, react_jsx_runtime.jsx)("circle", { cx: 12, cy: 12, r: 9, fill: "none", stroke: "currentColor", strokeWidth: 2.5 }),\n        (0, react_jsx_runtime.jsx)("circle", { cx: 12, cy: 12, r: 9, fill: "none", stroke: "#f5a000", strokeWidth: 2.5,\n          strokeLinecap: "round", pathLength: 100, strokeDasharray: `${percent} 100`, transform: "rotate(-90 12 12)" })\n      ]\n    })'
_ICON_START = HELPER.index('    children: (0, react_jsx_runtime.jsxs)("svg"')
CURRENT_TRIGGER_ICON = HELPER[_ICON_START:HELPER.index('\n  });', _ICON_START)]

PREVIOUS_FRAME = 'function DshComposerFrame({ children }) {\n  const [open, setOpen] = (0, react.useState)(false);\n  const [bypass, setBypass] = (0, react.useState)(false);\n  const id = (0, react.useId)();\n  return (0, react_jsx_runtime.jsx)(DshSessionInfoContext.Provider, {\n    value: { open, setOpen, bypass, setBypass, id }, children\n  });\n}\n'
CURRENT_FRAME = HELPER[HELPER.index("function DshComposerFrame("):HELPER.index("function DshSessionInfoTrigger")]

def patch(text):
    if 'const DshSessionInfoContext =' in text:
        if PREVIOUS_FRAME in text:
            text = replace_once(text, PREVIOUS_FRAME, CURRENT_FRAME)
        if PREVIOUS_TRIGGER_ICON in text:
            text = replace_once(text, PREVIOUS_TRIGGER_ICON, CURRENT_TRIGGER_ICON)
        if PREVIOUS_STYLE in text:
            text = replace_once(text, PREVIOUS_STYLE, CURRENT_STYLE)
        if HELPER not in text:
            raise ValueError('Unknown composer metadata helper; inspect before migrating')
    text = replace_once(text, ANCHOR, HELPER + WRAPPER + ANCHOR.replace('const InputBar =', 'const DshInputBar ='))
    text = replace_once(text, OLD, NEW)
    # Migrate the previous direct child to a real slot contribution.
    if TRAILING_NEW in text:
        if text.count(TRAILING_NEW) != 1:
            raise ValueError('Duplicate direct session-info trigger')
        text = text.replace(TRAILING_NEW, TRAILING, 1)
    text = replace_once(text, REGISTER_ANCHOR, REGISTER_TRIGGER + REGISTER_ANCHOR)
    for running, label in TRANSLATIONS.items():
        original = '"details.running": ' + json.dumps(running, ensure_ascii=False) + ','
        addition = '"composer.sessionInfo": ' + json.dumps(label, ensure_ascii=False) + ',\n\t\t\t' + original
        text = replace_once(text, original, addition)
    return text


def plan_changes(host=None, *, read_text=Path.read_text):
    host = host_directory(host)
    package = Path(host) / 'dsh-client-ui-conversation'
    # The legacy release does not have this UI contribution.
    if verify_package(package, '@deepseek-ai/dsh-client-ui-conversation', ('0.2.2-alpha.2', '0.2.2-rc.1')) == '0.2.2-alpha.2':
        return []
    file = package / 'lib/client.js'
    return [read_change(file, patch, read_text=read_text)]


def main():
    patch_cli(plan_changes, __doc__, {'host': '--host-dir'},
              'Composer metadata disclosure verified')


if __name__ == '__main__':
    main()
