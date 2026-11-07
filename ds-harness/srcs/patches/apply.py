#!/usr/bin/env python3
"""Validate and publish the complete reviewed DSH patch set."""
import argparse
from importlib import import_module
from pathlib import Path

if not __package__:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from patches.common import COMPONENT_ROOT, check_or_publish, host_directory


# Preserve migration order: Bot retires old host hooks before mobile fits tabs.
PATCHES = (
    ('plugins.ds_bot.ds_bot_apply', 'bot', 'ds-bot'),
    ('plugins.mobile.dsh_mobile_apply', 'package', 'dsh-web-mobile'),
    ('plugins.git_panel.dsh_git_panel_apply', 'package', '@xbzbing/dsh-git-panel'),
    ('service.dsh_terminal_apply', None, None),
    ('service.dsh_file_resources_apply', None, None),
    ('service.dsh_composer_metadata_apply', None, None),
)


def load_patches():
    """Import every tool before package installation or target validation."""
    return [(import_module('patches.' + name), argument, package)
            for name, argument, package in PATCHES]


def plan_changes(profile=None, host=None):
    profile = Path(profile) if profile is not None else COMPONENT_ROOT / 'data/.dsh/profiles/web'
    host = host_directory(host)
    changes = {}

    def read_text(path):
        path = Path(path).resolve()
        if path not in changes:
            original = path.read_text()
            changes[path] = (original, original)
        return changes[path][1]

    for module, argument, package in load_patches():
        options = {'read_text': read_text}
        if argument:
            options[argument] = profile / 'node_modules' / package
        if package != '@xbzbing/dsh-git-panel':
            options['host'] = host
        try:
            for path, before, after in module.plan_changes(**options):
                path = Path(path).resolve()
                if read_text(path) != before:
                    raise ValueError(f'Inconsistent patch plan for {path}')
                changes[path] = (changes[path][0], after)
        except (ValueError, OSError) as error:
            raise ValueError(f'{module.__name__}: {error}') from error
    return [(path, before, after) for path, (before, after) in changes.items()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Validate without writing')
    parser.add_argument('--validate-tools', action='store_true', help='Check local patch tools without reading installed packages')
    parser.add_argument('--profile-dir', type=Path, help='Installed DSH web profile')
    parser.add_argument('--host-dir', type=Path, help='Installed DSH node_modules/@deepseek-ai directory')
    args = parser.parse_args()
    if args.validate_tools:
        load_patches()
        return
    changes = plan_changes(args.profile_dir, args.host_dir)
    check_or_publish(changes, args.check, 'DSH patches missing')
    if not args.check:
        for path, before, after in changes:
            print(f'已安装，跳过：{path}' if before == after else f'已应用补丁：{path}')
        if not changes:
            print('没有需要安装的补丁。')
    print('Reviewed DSH patch set verified; no service restarted.')


if __name__ == '__main__':
    main()
