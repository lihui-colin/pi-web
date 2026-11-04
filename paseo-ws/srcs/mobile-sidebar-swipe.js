/* Let Paseo own left-sidebar opening/closing pans instead of browser scrolling. */
(function installMobileSidebarSwipe() {
  if (typeof document === 'undefined') return;
  globalThis.__paseoMobileSidebarSwipeCleanup?.();
  const edgeWidth = 32; // Matches upstream MOBILE_WEB_EDGE_SWIPE_WIDTH.
  let touch = null;
  const reset = () => { touch = null; };
  function start(event) {
    reset();
    if (event.touches.length !== 1) return;
    const target = event.target;
    const leftHost = target?.closest?.('[id^="agent-list-gesture-host-"]');
    const leftOpen = document.querySelector('[data-testid="agent-list-backdrop"]');
    const closing = Boolean(leftHost && leftOpen);
    const shell = closing ? document.querySelector('[data-testid="compact-shell"]') :
      target?.closest?.('[data-testid="compact-shell"]');
    if (!shell || target.closest('input,textarea,[contenteditable="true"],[role="dialog"],[role="menu"]')) return;
    if (!closing && document.querySelector('[data-testid="agent-list-backdrop"],[data-testid="file-explorer-backdrop"]')) return;
    const point = event.touches[0];
    if (!closing && (point.clientX < 0 || point.clientX > edgeWidth)) return;
    touch = { id: point.identifier, x: point.clientX, y: point.clientY, shell,
      direction: closing ? -1 : 1, horizontal: false };
  }
  function move(event) {
    if (!touch) return;
    if (event.touches.length !== 1 || !touch.shell.isConnected ||
        touch.shell.getAttribute('data-testid') !== 'compact-shell') return reset();
    const point = event.touches[0];
    if (point.identifier !== touch.id) return reset();
    const dx = (point.clientX - touch.x) * touch.direction;
    const dy = Math.abs(point.clientY - touch.y);
    if (!touch.horizontal) {
      if (dx < -6 || (dy > 6 && dy >= Math.abs(dx))) return reset();
      if (dx < 6 || dx < dy * 1.5) return;
      touch.horizontal = true;
    }
    // Do not stop propagation: the upstream gesture owns animation and the commit.
    if (event.cancelable) event.preventDefault();
  }
  const listeners = { touchstart: start, touchmove: move, touchend: reset, touchcancel: reset };
  for (const [type, handler] of Object.entries(listeners)) {
    document.addEventListener(type, handler, { capture: true, passive: type !== 'touchmove' });
  }
  globalThis.__paseoMobileSidebarSwipeCleanup = () => {
    for (const [type, handler] of Object.entries(listeners)) document.removeEventListener(type, handler, true);
    reset();
  };
})();
