#!/usr/bin/env python3
"""Coalesce reviewed rc.1 host output after headless parsing (standalone candidate)."""
import hashlib
from pathlib import Path

if not __package__:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from patches.common import plan_host_patch, patch_cli, undo_replacements

HERE = Path(__file__).resolve().parent
HELPER = (HERE / 'dsh_terminal_host_batching.js').read_text().strip() + '\n'
ANCHOR = '/** Process lifetime is independent of follower and component lifetimes. */'
CLASS = 'var BrowserTerminal = class {'
DIGEST = '9184e7b5484ae525f9cf36953600a6b72e9877f584890e082b3f5207128c15ee'
OUTPUT = '''\t\t\tthis.broadcast({
\t\t\t\ttype: "output",
\t\t\t\tsequence: ++this.sequence,
\t\t\t\tdata
\t\t\t});'''
REPLACEMENTS = [
    ('\toperations = Promise.resolve();', '\toperations = Promise.resolve();\n\thostOutputBatcher = createDshHostOutputBatcher(this);\n\thostOutputDisposed = false;'),
    ('\t\t\tsignal.throwIfAborted();\n\t\t\tthis.controller = follower;', '\t\t\tsignal.throwIfAborted();\n\t\t\tthis.hostOutputBatcher.flush();\n\t\t\tthis.controller = follower;'),
    ('\t\t\t\tfollower.push({\n\t\t\t\t\ttype: "ack",', '\t\t\t\tthis.hostOutputBatcher.flush();\n\t\t\t\tfollower.push({\n\t\t\t\t\ttype: "ack",'),
    ('\t\t\t\tconst failure = remoteErrorOf(error);', '\t\t\t\tthis.hostOutputBatcher.flush();\n\t\t\t\tconst failure = remoteErrorOf(error);'),
    ('\tbroadcastState() {', '\tbroadcastState() {\n\t\tthis.hostOutputBatcher.flush();'),
    ('''\t\t\tif (this.controller === follower) {
\t\t\t\tthis.controller = void 0;
\t\t\t\tthis.broadcastState();
\t\t\t}
\t\t\tawait uplink.return?.();
\t\t\tawait commands;''', '''\t\t\tconst cleanupFailures = [];
\t\t\ttry {
\t\t\t\tif (this.controller === follower) {
\t\t\t\t\tthis.controller = void 0;
\t\t\t\t\tthis.broadcastState();
\t\t\t\t}
\t\t\t} catch (error) {
\t\t\t\tcleanupFailures.push(error);
\t\t\t}
\t\t\t// Returning the iterator must interrupt consumeInput's pending read even
\t\t\t// if publishing the controller transition failed.
\t\t\ttry {
\t\t\t\tawait uplink.return?.();
\t\t\t} catch (error) {
\t\t\t\tcleanupFailures.push(error);
\t\t\t}
\t\t\ttry {
\t\t\t\tawait commands;
\t\t\t} catch (error) {
\t\t\t\tcleanupFailures.push(error);
\t\t\t}
\t\t\tif (cleanupFailures.length !== 0) throw cleanupFailures[0];'''),
    ('\t\t\tawait this.drained;', '''\t\t\tlet outputFailure;
\t\t\ttry {
\t\t\t\tawait this.drained;
\t\t\t} catch (error) {
\t\t\t\toutputFailure = error;
\t\t\t}
\t\t\ttry {
\t\t\t\tthis.hostOutputBatcher.dispose();
\t\t\t} catch (error) {
\t\t\t\toutputFailure ??= error;
\t\t\t}
\t\t\t// Termination succeeded. Release resources even when output publication failed.
\t\t\tthis.hostOutputDisposed = true;'''),
    ('\t\t\tthis.screen.dispose();\n\t\t})().catch((error) => {\n\t\t\tthis.closing = void 0;', '\t\t\tthis.screen.dispose();\n\t\t\tif (outputFailure !== void 0) throw outputFailure;\n\t\t})().catch((error) => {\n\t\t\tif (!this.hostOutputDisposed) this.closing = void 0;'),
    (OUTPUT, '\t\t\tthis.hostOutputBatcher.handle(data);'),
]


def baseline_class(text):
    # Keep compatibility with the separately reviewed terminal enhancement patch.
    # Its exact snapshot/protocol additions do not alter the host batching anchors.
    from patches.service import dsh_terminal_apply as terminal
    if terminal.PROTOCOL_SERIALIZE in text:
        text = terminal.undo_replacements(text, terminal.HOST_REPLACEMENTS)
        if text.count(terminal.SERIALIZE_NEW) != 1:
            raise ValueError('Partial terminal enhancement snapshot')
        text = text.replace(terminal.SERIALIZE_NEW, terminal.SERIALIZE, 1)
    return text


def patch(text):
    if text.count(CLASS) != 1 or text.count(ANCHOR) != 1:
        raise ValueError('Unknown or mixed BrowserTerminal anchors')
    patched = 'createDshHostOutputBatcher' in text or 'hostOutputBatcher' in text
    original = text
    if patched:
        if text.count(HELPER) != 1:
            raise ValueError('Unknown or partial host batching helper')
        text = undo_replacements(text.replace(HELPER, '', 1), REPLACEMENTS,
                                 error='Partial or mixed host batching patch')
        if 'hostOutputBatcher' in text or 'createDshHostOutputBatcher' in text:
            raise ValueError('Unexpected host batching references')
    start = text.index(CLASS)
    end = text.index('\n};', start) + 3
    body = baseline_class(text[start:end])
    if hashlib.sha256(body.encode()).hexdigest() != DIGEST:
        raise ValueError('BrowserTerminal differs from reviewed rc.1; inspect upstream')
    if patched:
        # Require the exact canonical placement as well as the complete replacements.
        if patch(text) != original:
            raise ValueError('Noncanonical host batching patch')
        return original
    for old, new in REPLACEMENTS:
        if text.count(old) != 1:
            raise ValueError('Ambiguous host batching replacement')
        text = text.replace(old, new, 1)
    return text.replace(ANCHOR, HELPER + ANCHOR, 1)


def plan_changes(host=None, *, read_text=Path.read_text):
    return plan_host_patch(host, 'dsh-api-terminal-controller', patch,
                           filename='lib/index.js', read_text=read_text)


def main():
    patch_cli(plan_changes, __doc__, {'host': '--host-dir'}, 'Terminal host output batching verified')


if __name__ == '__main__':
    main()
