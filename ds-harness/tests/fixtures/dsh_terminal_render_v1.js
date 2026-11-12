// Exclusive official TerminalScreen renderer; no frame history or input replay.
function dshBindTerminalRenderSink(model, xterm) {
    let alive = true, revision = 0, token = 0, ready = false, busy = false, deferredFit, shown;
    let writable = false;

    const current = (next, stamp) => alive && token === stamp
        && model.pendingRender?.revision === next.revision;
    const dimensions = (frame, enabled) => {
        writable = enabled;
        xterm.options.disableStdin = !enabled;
        xterm.resize(frame.info.cols, frame.info.rows);
    };
    const gate = {
        visibility(visible, action) {
            const changed = shown !== visible;
            shown = visible;
            if (changed && visible) gate.fit(action);
        },
        fit(action) {
            if (!alive) return;
            if (!ready || busy) deferredFit = action;
            // React may still hold the previous writable snapshot after the pump
            // has applied a queued state barrier. Consult both live owners here.
            else if (writable && model.state.getSnapshot().writable) action();
        },
        dispose() {
            if (!alive) return;
            alive = false;
            ++token;
            deferredFit = undefined;
            delete xterm.dshRenderGate;
            release();
        }
    };
    xterm.dshRenderGate = gate;
    const release = model.bindRenderer(next => {
        const frame = next.frame;
        if (frame.type === 'state') {
            dimensions(frame, next.writable);
            return;
        }
        if (next.revision <= revision) return;
        revision = next.revision;
        const stamp = ++token;
        busy = true;
        const complete = () => {
            if (!current(next, stamp)) return;
            busy = false;
            ready = true;
            model.acknowledge(next.revision);
            const action = deferredFit;
            deferredFit = undefined;
            // Let the pump apply already queued state barriers before measuring.
            if (action) queueMicrotask(() => gate.fit(action));
        };
        if (frame.type === 'snapshot') {
            ready = false;
            // An aborted generation may still be in xterm's parser. Fence it before
            // resetting the emulator; an old callback cannot reset a newer baseline.
            xterm.write('', () => {
                if (!current(next, stamp)) return;
                xterm.reset();
                dimensions(frame, next.writable);
                xterm.write(frame.screen, complete);
            });
        } else xterm.write(frame.data, complete);
    });
    return gate;
}
