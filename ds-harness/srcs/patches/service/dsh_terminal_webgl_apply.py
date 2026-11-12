#!/usr/bin/env python3
"""Restore the upstream terminal renderer by removing known retired WebGL patches."""
import hashlib
from pathlib import Path

if not __package__:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from patches.common import patch_cli
from patches.service.dsh_terminal_assets import plan_terminal_frontend

# Keep this installer entry as a migration for existing deployments.
RETIRED_HELPERS = frozenset((
    'b09c0e9c8f752031c84db3c0da3ae51e3e86524448094991b4da79dd5aedc3f1',
    '9e745c20f9cee4f7e7e9d5a9acda377c3a682dfb41f718c9df63a1acd1f6c51f',
))
HELPER_PREFIX = 'const DshTerminalWebglAddon = (() => {\n'
ANCHOR = '\t\texports.TerminalBody = TerminalBody;'
OPEN = '\t\t\t\txterm.open(node);'
CLEANUP = '\t\t\t\t\txterm.dispose();'
REPLACEMENTS = (
    (OPEN, OPEN + '\n\t\t\t\tconst dshWebgl = createDshTerminalWebgl(xterm, node);'),
    (CLEANUP, '\t\t\t\t\tdshWebgl.dispose();\n' + CLEANUP),
)
MARKERS = ('DshTerminalWebglAddon', 'createDshTerminalWebgl', 'dshWebgl', 'data-dsh-terminal-renderer')


def patch(text):
    if not any(marker in text for marker in MARKERS):
        return text
    if text.count(HELPER_PREFIX) != 1 or text.count(ANCHOR) != 1:
        raise ValueError('Unknown or incomplete retired WebGL patch')
    start = text.index(HELPER_PREFIX)
    end = text.find(ANCHOR, start)
    helper = text[start:end] if end >= 0 else ''
    if hashlib.sha256(helper.encode()).hexdigest() not in RETIRED_HELPERS:
        raise ValueError('Unknown WebGL helper revision; inspect before removing')
    text = text[:start] + text[end:]
    for original, installed in REPLACEMENTS:
        if text.count(installed) != 1:
            raise ValueError('Incomplete retired WebGL lifecycle; inspect before removing')
        text = text.replace(installed, original, 1)
    if any(marker in text for marker in MARKERS):
        raise ValueError('Unexpected WebGL patch residue; inspect before removing')
    return text


def plan_changes(host=None, *, read_text=Path.read_text):
    return plan_terminal_frontend(host, patch, read_text=read_text)


def main():
    patch_cli(plan_changes, __doc__, {'host': '--host-dir'}, 'Upstream terminal renderer restored; WebGL disabled')


if __name__ == '__main__':
    main()
