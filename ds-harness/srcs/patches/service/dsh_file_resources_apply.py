#!/usr/bin/env python3
"""Fix legacy mobile URL resource lookup on reviewed DSH client-resources."""
from pathlib import Path

if not __package__:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from patches.common import host_directory, publish, read_change, replace_once, verify_package, patch_cli

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


def plan_changes(host=None, *, read_text=Path.read_text):
    host = host_directory(host)
    package = Path(host) / 'dsh-client-resources'
    # Both published bundles share protocolOf.
    verify_package(package, '@deepseek-ai/dsh-client-resources', ('0.2.2-alpha.2', '0.2.2-rc.1'))
    path = package / 'lib/client.js'
    return [read_change(path, patch, read_text=read_text)]


def main():
    patch_cli(plan_changes, __doc__, {'host': '--host-dir'},
              'File-resource browser compatibility verified')


if __name__ == '__main__':
    main()
