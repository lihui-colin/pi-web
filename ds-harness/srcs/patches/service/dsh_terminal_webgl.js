// Optional renderer only: parsing, keyboard input and ACKs stay with xterm/model.
function createDshTerminalWebgl(xterm, node) {
    let disposed = false, addon, contextLoss, scheduled;
    const mark = value => node.setAttribute('data-dsh-terminal-renderer', value);
    // The outer content padding is outside xterm's own mouse listener.
    const focusPadding = event => {
        if (event.target === node && event.button === 0 && !xterm.options.disableStdin) {
            // Like xterm's mousedown handler, prevent the default blur after focus.
            event.preventDefault();
            xterm.focus();
        }
    };
    node.addEventListener('mousedown', focusPadding);
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
            // Match the upstream DOM rows: painting must not intercept the tap.
            // xterm's screen owns both mouse handling and the hidden input.
            for (const canvas of xterm.element.querySelectorAll('.xterm-screen > canvas')) canvas.style.pointerEvents = 'none';
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
            node.removeEventListener('mousedown', focusPadding);
            if (scheduled !== undefined && typeof cancelAnimationFrame === 'function') cancelAnimationFrame(scheduled);
            scheduled = undefined;
            release();
            node.removeAttribute('data-dsh-terminal-renderer');
        }
    };
}
