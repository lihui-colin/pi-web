#!/usr/bin/env python3
"""Fix legacy mobile URL resource lookup on reviewed DSH client-resources."""
import argparse
from pathlib import Path

if not __package__:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from patches.common import check_or_publish, host_directory, publish, read_change, replace_once, verify_package

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
NEW = OLD.replace(
    'return parsed.hostname === "" ? void 0 : parsed.hostname.toLowerCase();',
    r'''if (parsed.hostname !== "") return parsed.hostname.toLowerCase();
			// Older mobile engines leave custom-scheme hosts empty. Keep modern URL
			// semantics; recover only canonical resource-provider names on that path.
			const authority = /^dsh-resource:\/\/([a-z0-9][a-z0-9._-]*)(?=[/?#]|$)/i.exec(address)?.[1];
			return authority?.toLowerCase();''')


def patch(text):
    return replace_once(text, OLD, NEW)


def plan_changes(host=None):
    host = host_directory(host)
    package = Path(host) / 'dsh-client-resources'
    # Both published bundles share protocolOf.
    verify_package(package, '@deepseek-ai/dsh-client-resources', ('0.2.2-alpha.2', '0.2.2-rc.1'))
    path = package / 'lib/client.js'
    return [read_change(path, patch)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host-dir', type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    changes = plan_changes(args.host_dir)
    check_or_publish(changes, args.check, 'File-resource browser compatibility patch missing')
    print('File-resource browser compatibility verified; no service restarted.')


if __name__ == '__main__':
    main()
