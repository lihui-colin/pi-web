// Optional renderer only: parsing, keyboard input and ACKs stay with xterm/model.
function createDshTerminalWebgl(xterm, node) {
    let disposed = false, addon, contextLoss, scheduled;
    const mark = value => node.setAttribute('data-dsh-terminal-renderer', value);
    const release = () => {
        const previous = addon;
        addon = undefined;
        contextLoss?.dispose();
        contextLoss = undefined;
        try { previous?.dispose(); } catch (_) { /* Keep the DOM fallback usable. */ }
    };
    const fallback = () => {
        if (disposed) return;
        release();
        mark('dom');
        try { xterm.refresh(0, Math.max(0, xterm.rows - 1)); } catch (_) { /* Already unmounted. */ }
    };
    const install = () => {
        scheduled = undefined;
        if (disposed) return;
        try {
            addon = new DshTerminalWebglAddon();
            contextLoss = addon.onContextLoss(fallback);
            xterm.loadAddon(addon);
            if (!disposed && addon !== undefined) mark('webgl');
        } catch (_) {
            fallback();
        }
    };
    mark('dom');
    // GPU setup is optional; output parsing never waits for an animation frame.
    if (typeof requestAnimationFrame === 'function') scheduled = requestAnimationFrame(install);
    else install();
    return {
        dispose() {
            if (disposed) return;
            disposed = true;
            if (scheduled !== undefined && typeof cancelAnimationFrame === 'function') cancelAnimationFrame(scheduled);
            scheduled = undefined;
            release();
            node.removeAttribute('data-dsh-terminal-renderer');
        }
    };
}
