#!/usr/bin/env python3
"""Enable an optional vendored WebGL renderer for the reviewed rc.1 terminal."""
import hashlib
from pathlib import Path

if not __package__:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from patches.common import apply_replacements, patch_cli, vendor_addon
from patches.service.dsh_terminal_assets import plan_terminal_frontend

HERE = Path(__file__).resolve().parent
VENDOR = HERE / 'vendor/addon-webgl-0.19.0.js'
VENDOR_SHA256 = 'b85f8d4b3e9756bebb757e3fe47134d70f03ea3d6b187624426d2e2b65dec06c'
ADDON = vendor_addon(VENDOR, VENDOR_SHA256, 'WebglAddon',
                     error='Unexpected WebGL addon; review the pinned upstream bundle')
RUNTIME = (HERE / 'dsh_terminal_webgl.js').read_text().strip() + '\n'
HELPER = ADDON + RUNTIME
HELPER_PREFIX = 'const DshTerminalWebglAddon = (() => {\n'
LEGACY_HELPER_SHA256 = 'b09c0e9c8f752031c84db3c0da3ae51e3e86524448094991b4da79dd5aedc3f1'
ANCHOR = '\t\texports.TerminalBody = TerminalBody;'
OPEN = '\t\t\t\txterm.open(node);'
CLEANUP = '\t\t\t\t\txterm.dispose();'
REPLACEMENTS = (
    (ANCHOR, HELPER + ANCHOR),
    (OPEN, OPEN + '\n\t\t\t\tconst dshWebgl = createDshTerminalWebgl(xterm, node);'),
    (CLEANUP, '\t\t\t\t\tdshWebgl.dispose();\n' + CLEANUP),
)


def patch(text):
    if 'DshTerminalWebglAddon' in text:
        if text.count(HELPER_PREFIX) != 1 or text.count(ANCHOR) != 1:
            raise ValueError('Unknown or mixed WebGL helper placement')
        start = text.index(HELPER_PREFIX)
        end = text.find(ANCHOR, start)
        previous = text[start:end] if end >= 0 else ''
        if previous != HELPER:
            if hashlib.sha256(previous.encode()).hexdigest() != LEGACY_HELPER_SHA256:
                raise ValueError('Unknown WebGL helper revision; inspect upstream')
            text = text[:start] + HELPER + text[end:]
    installed = [new in text for _, new in REPLACEMENTS]
    if any(installed) and not all(installed):
        raise ValueError('Incomplete WebGL renderer patch; inspect before applying')
    if 'DshTerminalWebglAddon' in text and HELPER not in text:
        raise ValueError('Unknown WebGL helper revision; inspect upstream')
    return apply_replacements(text, REPLACEMENTS)


def plan_changes(host=None, *, read_text=Path.read_text):
    return plan_terminal_frontend(host, patch, read_text=read_text)


def main():
    patch_cli(plan_changes, __doc__, {'host': '--host-dir'}, 'Terminal optional WebGL renderer verified')


if __name__ == '__main__':
    main()
