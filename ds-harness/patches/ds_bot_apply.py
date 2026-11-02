#!/usr/bin/env python3
"""Apply the reviewed DS Bot 0.2.6 fixes after validating every target."""
import argparse
if __package__:
    from .ds_bot_patch_common import publish
    from . import ds_bot_history_native as history, ds_bot_mobile as mobile, ds_bot_prompt as prompt
else:
    from ds_bot_patch_common import publish
    import ds_bot_history_native as history
    import ds_bot_mobile as mobile
    import ds_bot_prompt as prompt


def plan_changes():
    changes = history.plan_changes()
    bot_path, original, fixed = changes[0]
    fixed = mobile.patch(fixed, '0.2.6')
    changes[0] = (bot_path, original, fixed)
    tools = bot_path.parent / 'src/host/tools.js'
    original = tools.read_text()
    fixed = prompt.patch(original)
    changes.append((tools, original, fixed))
    return changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Validate without writing; exit 1 if fixes are missing')
    args = parser.parse_args()
    changes = plan_changes()  # All versions and anchors checked before any write.
    pending = [(path, original, fixed) for path, original, fixed in changes if original != fixed]
    if args.check:
        for path, _, _ in pending:
            print(f'Needs patch: {path}')
        if pending:
            raise SystemExit(1)
        print('All reviewed DS Bot fixes are present.')
        return
    publish(changes)
    print('DS Bot fixes applied. Refresh the browser for frontend changes.')
    if any(path.name == 'tools.js' for path, _, _ in pending):
        print('Server module changed: reload it during a maintenance window; no restart performed.')


if __name__ == '__main__':
    main()
