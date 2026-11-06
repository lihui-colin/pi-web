#!/usr/bin/env python3
"""Fix legacy mobile URL resource lookup on reviewed DSH client-resources."""
import argparse
import json
from pathlib import Path
import shutil

if __package__:
    from .ds_bot_apply import publish, replace_once
else:
    from ds_bot_apply import publish, replace_once

# Upstream discussion #6217; rc.1 still derives provider names from URL.hostname.
OLD = '''		function protocolOf(address) {
			let parsed;
			try {
				parsed = new URL(address);
			} catch {
				return;
			}
			if (parsed.protocol !== `dsh-resource:`) return void 0;
			return parsed.hostname === "" ? void 0 : parsed.hostname.toLowerCase();
		}'''
NEW = r'''		function protocolOf(address) {
			let parsed;
			try {
				parsed = new URL(address);
			} catch {
				return;
			}
			if (parsed.protocol !== `dsh-resource:`) return void 0;
			if (parsed.hostname !== "") return parsed.hostname.toLowerCase();
			// Older mobile engines leave custom-scheme hosts empty. Keep modern URL
			// semantics; recover only canonical resource-provider names on that path.
			const authority = /^dsh-resource:\/\/([a-z0-9][a-z0-9._-]*)(?=[/?#]|$)/i.exec(address)?.[1];
			return authority?.toLowerCase();
		}'''


def patch(text):
    return replace_once(text, OLD, NEW)


def plan_changes(host=None):
    if host is None:
        executable = shutil.which('dsh')
        if executable is None:
            raise ValueError('dsh executable not found')
        host = Path(executable).resolve().parents[1] / 'node_modules/@deepseek-ai'
    package = Path(host) / 'dsh-client-resources'
    manifest = json.loads((package / 'package.json').read_text())
    # Both published bundles have the exact same protocolOf implementation.
    if (manifest.get('name') != '@deepseek-ai/dsh-client-resources'
            or manifest.get('version') not in ('0.2.2-alpha.2', '0.2.2-rc.1')):
        raise ValueError('Unsupported client-resources version; review upstream before applying')
    path = package / 'lib/client.js'
    original = path.read_text()
    return [(path, original, patch(original))]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host-dir', type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    changes = plan_changes(args.host_dir)
    if args.check:
        if any(before != after for _, before, after in changes):
            raise SystemExit('File-resource browser compatibility patch missing')
    else:
        publish(changes)
    print('File-resource browser compatibility verified; no service restarted.')


if __name__ == '__main__':
    main()
