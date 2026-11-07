#!/usr/bin/env python3
"""Omit the Git input pill while preserving the Git panel and sidebar."""
from pathlib import Path

if not __package__:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from patches.common import COMPONENT_ROOT, publish, read_change, replace_once, verify_package, patch_cli


PILL = 'r(e.slots.inject("conversation.input.left",()=>e.slots.register({name:"conversation.input.left",id:"git-panel-pill",order:100,locale:er},l=>(0,io.createElement)(iu,{ctx:e,sessionId:l.sessionId,t}))));'
PILL_1131 = 'r(e.slots.inject("conversation.input.left",()=>e.slots.register({name:"conversation.input.left",id:"git-panel-pill",order:100,locale:sr},c=>(0,Qa.createElement)(Qf,{ctx:e,sessionId:c.sessionId,t,useContextMenu:c.useContextMenu}))));'
REMOVED = '/* Local preference: omit the Git composer status pill. */'


def patch(text):
    if 'git-panel-pill' not in text:
        return text
    if text.count('git-panel-pill') != 1:
        raise ValueError('Duplicate or mixed Git pill registration')
    return replace_once(text, PILL_1131 if PILL_1131 in text else PILL, REMOVED)


def plan_changes(package=None, *, read_text=Path.read_text):
    package = Path(package) if package else COMPONENT_ROOT / 'data/.dsh/profiles/web/node_modules/@xbzbing/dsh-git-panel'
    if not package.exists():
        return []
    verify_package(package, '@xbzbing/dsh-git-panel', ('1.11.2', '1.13.1'))
    path = package / 'lib/client.js'
    return [read_change(path, patch, read_text=read_text)]


def main():
    patch_cli(plan_changes, __doc__, {'package': '--git-panel-dir'},
              'Git composer status pill removal verified')


if __name__ == '__main__':
    main()
