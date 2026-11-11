#!/usr/bin/env python3
"""Batch reviewed rc.1 terminal output without delaying input acknowledgements."""
import hashlib
from pathlib import Path

if not __package__:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from patches.common import plan_host_patch, patch_cli

HERE = Path(__file__).resolve().parent
HELPER = (HERE / 'dsh_terminal_batching.js').read_text().strip() + '\n'
START = '\t\t\tasync consume(stream) {'
END = '\n\t\t\tpatch(patch) {'
ANCHOR = '\t\tvar TerminalView = class {'
ORIGINAL_SHA256 = '7d2fd6d0d0f81812356e5b3cbeedf2a97801e58cd39dc3bec182157745af5804'
CONSUME = START + '\n\t\t\t\treturn dshConsumeTerminalBatched.call(this, stream);\n\t\t\t}'
HELPER_BEGIN = '// Connected terminal render batching. Physical Gateway inbox remains unchanged.\n'
LEGACY_SHA256 = 'd728e743b1d470f1f3e0a4b0e62a4eb240d0fcf1792a64b23263bbedda5225a8'
MOUNT = '\t\t\t\telse if (state.info !== void 0 && state.phase !== "failed" && state.phase !== "closed") this.connect();'
MOUNT_NEW = '\t\t\t\telse if (this.stream === void 0 && state.info !== void 0 && (this.renderer !== void 0 || (state.phase !== "failed" && state.phase !== "closed"))) this.connect();'
METHODS = '''
            // Exclusive, opt-in renderer. A new emulator always attaches a fresh baseline.
            bindRenderer(sink) {
                if (this.renderer !== undefined) throw new Error('Terminal renderer already owned');
                this.renderer = sink;
                if (this.mounted) this.connect();
                let released = false;
                return () => {
                    if (released) return;
                    released = true;
                    if (this.renderer !== sink) return;
                    this.renderer = undefined;
                    this.detach();
                };
            }
            offerFrame(render) {
                if (this.renderer === undefined) return false;
                this.renderer(render);
                return true;
            }
'''



def patch(text):
    if '\t\t\tmount() {' in text:
        if text.count(MOUNT) + text.count(MOUNT_NEW) != 1:
            raise ValueError('Unknown terminal mount lifecycle; inspect upstream')
    if 'dshConsumeTerminalBatched' in text:
        if text.count(HELPER_BEGIN) != 1 or text.count(ANCHOR) != 1:
            raise ValueError('Ambiguous terminal batching helper boundaries')
        if HELPER not in text:
            start = text.index(HELPER_BEGIN)
            end = text.index(ANCHOR)
            legacy = text[start:end]
            if (start >= end or hashlib.sha256(legacy.encode()).hexdigest() != LEGACY_SHA256
                    or text.count(CONSUME) != 1 or METHODS in text):
                raise ValueError('Unknown legacy terminal batching helper')
            text = text[:start] + HELPER + text[end:]
            text = text.replace(ANCHOR, ANCHOR + METHODS, 1)
            text = text.replace(MOUNT, MOUNT_NEW, 1)
        if (MOUNT in text or text.count(HELPER + ANCHOR + METHODS) != 1
                or text.count(HELPER) != 1 or text.count(METHODS) != 1 or text.count(CONSUME) != 1
                or text.count(START) != 1 or text.count(END) != 1 or text.count(ANCHOR) != 1):
            raise ValueError('Mixed terminal batching candidate; inspect before applying')
        # Exact helper and consume must be the only references plus their declaration.
        if text.count('dshConsumeTerminalBatched') != 2:
            raise ValueError('Unexpected terminal batching references')
        return text
    if text.count(START) != 1 or text.count(END) != 1 or text.count(ANCHOR) != 1:
        raise ValueError('Unrecognized terminal controller anchors')
    start = text.index(START)
    end = text.index(END, start)
    if hashlib.sha256(text[start:end].encode()).hexdigest() != ORIGINAL_SHA256:
        raise ValueError('Terminal consumer differs from reviewed rc.1; inspect upstream')
    text = text[:start] + CONSUME + text[end:]
    text = text.replace(MOUNT, MOUNT_NEW, 1)
    return text.replace(ANCHOR, HELPER + ANCHOR + METHODS, 1)


def plan_changes(host=None, *, read_text=Path.read_text):
    return plan_host_patch(host, 'dsh-api-terminal-controller', patch, read_text=read_text)


def main():
    patch_cli(plan_changes, __doc__, {'host': '--host-dir'},
              'Terminal render batching verified')


if __name__ == '__main__':
    main()
