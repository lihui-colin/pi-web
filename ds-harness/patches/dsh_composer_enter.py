#!/usr/bin/env python3
"""Keep mobile Enter as a newline in the shared DSH / DS Bot composer."""
import argparse
import json
from pathlib import Path
import shutil

if __package__:
    from .ds_bot_patch_common import publish, replace_once
else:
    from ds_bot_patch_common import publish, replace_once


ANCHOR = '''\t\t\t\tif (event !== null && isComposingEvent(event, recentlyComposing)) return true;
\t\t\t\tif (handlers.arbitrate("enter", false) !== "pass") {'''
REPLACEMENT = ANCHOR.replace(
    '\t\t\t\tif (handlers.arbitrate',
    '\t\t\t\t// Mobile Enter inserts a line break without submitting the draft.\n'
    '\t\t\t\tif ((0, _deepseek_ai_dsh_client_ui_primitives.isMobileDevice)()) {\n'
    '\t\t\t\t\tevent?.preventDefault();\n'
    '\t\t\t\t\treturn editor.dispatchCommand(Ue$2, false);\n'
    '\t\t\t\t}\n'
    '\t\t\t\tif (handlers.arbitrate',
)


def patch(text):
    return replace_once(text, ANCHOR, REPLACEMENT)


def plan_changes():
    executable = shutil.which('dsh')
    if executable is None:
        raise ValueError('dsh executable not found')
    package = (Path(executable).resolve().parents[1] / 'node_modules/@deepseek-ai/'
               'dsh-client-ui-conversation')
    manifest = json.loads((package / 'package.json').read_text())
    if (manifest.get('name'), manifest.get('version')) != (
            '@deepseek-ai/dsh-client-ui-conversation', '0.2.2-alpha.2'):
        raise ValueError('Only reviewed DSH conversation 0.2.2-alpha.2 is supported')
    target = package / 'lib/client.js'
    original = target.read_text()
    return [(target, original, patch(original))]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    changes = plan_changes()
    if args.check:
        if any(original != fixed for _, original, fixed in changes):
            raise SystemExit('Shared composer needs the mobile Enter fix')
        print('Shared composer mobile Enter fix is present.')
        return
    publish(changes)
    print('Mobile Enter fix applied to DSH and DS Bot; reload frontend resources to activate.')


if __name__ == '__main__':
    main()
