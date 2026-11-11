"""Keep the watched client entry in sync with its immutable terminal lazy chunk."""
import hashlib
from pathlib import Path
import re
from patches.common import reviewed_host_package

MARKER = '// DSH terminal lazy chunk SHA256: '
PATTERN = re.compile(r'(?m)^// DSH terminal lazy chunk SHA256: [0-9a-f]{64}\n')
MAP_TRAILER = re.compile(r'(?m)^//# sourceMappingURL=[^\n]*(?:\n)?\Z')


def refresh_terminal_entry(source, frontend):
    matches = list(PATTERN.finditer(source))
    if source.count(MARKER) != len(matches) or len(matches) > 1:
        raise ValueError('Unknown or duplicate terminal lazy chunk revision marker')
    baseline = PATTERN.sub('', source)
    stamp = MARKER + hashlib.sha256(frontend.encode()).hexdigest() + '\n'
    trailer = MAP_TRAILER.search(baseline)
    if trailer:
        before = baseline[:trailer.start()]
        return before + ('' if before.endswith('\n') else '\n') + stamp + baseline[trailer.start():]
    return baseline + ('' if baseline.endswith('\n') else '\n') + stamp


def plan_terminal_frontend(host, transform, *, read_text=Path.read_text):
    package = reviewed_host_package(host, 'dsh-client-ui-sidebar-terminal')
    return [] if package is None else terminal_frontend_changes(package, transform, read_text=read_text)


def terminal_frontend_changes(package, transform, *, read_text=Path.read_text):
    """Publish both files atomically; HMR watches the entry, not its lazy chunks."""
    package = Path(package)
    lazy = package / 'lib/client.terminal.js'
    before = read_text(lazy)
    after = transform(before)
    entry = package / 'lib/client.js'
    entry_before = read_text(entry)
    entry_after = refresh_terminal_entry(entry_before, after)
    return [(lazy, before, after), (entry, entry_before, entry_after)]
