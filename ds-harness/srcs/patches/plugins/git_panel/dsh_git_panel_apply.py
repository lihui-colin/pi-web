#!/usr/bin/env python3
"""Omit the Git input pill while preserving the Git panel and sidebar."""
import argparse
from pathlib import Path

if not __package__:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from patches.common import COMPONENT_ROOT, check_or_publish, publish, read_change, replace_once, verify_package


PILL = 'r(e.slots.inject("conversation.input.left",()=>e.slots.register({name:"conversation.input.left",id:"git-panel-pill",order:100,locale:er},l=>(0,io.createElement)(iu,{ctx:e,sessionId:l.sessionId,t}))));'
REMOVED = '/* Local preference: omit the Git composer status pill. */'


def patch(text):
    if PILL not in text and 'git-panel-pill' not in text:
        return text
    return replace_once(text, PILL, REMOVED)


def plan_changes(package=None, *, read_text=Path.read_text):
    package = Path(package) if package else COMPONENT_ROOT / 'data/.dsh/profiles/web/node_modules/@xbzbing/dsh-git-panel'
    if not package.exists():
        return []
    verify_package(package, '@xbzbing/dsh-git-panel', ('1.11.2',))
    path = package / 'lib/client.js'
    return [read_change(path, patch, read_text=read_text)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--git-panel-dir', type=Path)
    args = parser.parse_args()
    changes = plan_changes(args.git_panel_dir)
    check_or_publish(changes, args.check, 'Git composer status pill removal missing')
    print('Git composer status pill removal verified; no service restarted.')


if __name__ == '__main__':
    main()
