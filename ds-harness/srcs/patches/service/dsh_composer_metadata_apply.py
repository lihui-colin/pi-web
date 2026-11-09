#!/usr/bin/env python3
"""Collapse the native DSH composer metadata behind a session-info disclosure."""
import hashlib
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
DOCK = ('\t\t\t\t\t(0, react_jsx_runtime.jsx)(DshComposerMetadata, {\n'
        '\t\t\t\t\t\t\t\t\t\t\t\tchildren: ' + OLD.lstrip() + '\n\t\t\t\t\t}, sessionId)')
NEW = DOCK.replace('(ContextMeter, {', '(DshContextMeter, {').replace(
    'useProjection,', 'useProjection,\n' + '\t' * 7 + 'renderSlot,')
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

# Only the last published helper is upgraded in place; experimental intermediate
# layouts are retired. The complete digest rejects partial or unknown edits.
LEGACY_HELPER_SHA256 = '356384b545827b166da2623b3e630659e3dd4fc22a2304b8c6e836ceb929e13d'
HELPER_PREFIX = HELPER.split('const DshSessionInfoContext =', 1)[0]


def patch(text):
    if 'const DshSessionInfoContext =' in text:
        start = text.index(HELPER_PREFIX)
        end = text.index(WRAPPER, start)
        installed = text[start:end]
        if installed != HELPER and hashlib.sha256(installed.encode()).hexdigest() != LEGACY_HELPER_SHA256:
            raise ValueError('Unknown composer metadata helper; restore the reviewed release before patching')
        text = replace_once(text, installed, HELPER)
    text = replace_once(text, ANCHOR, HELPER + WRAPPER + ANCHOR.replace('const InputBar =', 'const DshInputBar ='))
    for previous in (DOCK, DOCK.replace('(ContextMeter, {', '(DshContextMeter, {')):
        if previous in text:
            text = replace_once(text, previous, NEW)
    text = replace_once(text, OLD, NEW)
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
    package = host_directory(host) / 'dsh-client-ui-conversation'
    if verify_package(package, '@deepseek-ai/dsh-client-ui-conversation',
                      ('0.2.2-alpha.2', '0.2.2-rc.1')) == '0.2.2-alpha.2':
        return []
    return [read_change(package / 'lib/client.js', patch, read_text=read_text)]


if __name__ == '__main__':
    patch_cli(plan_changes, __doc__, {'host': '--host-dir'}, 'Composer metadata disclosure verified')
