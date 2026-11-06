// Snapshot parsing must finish before the browser or PTY is resized. A brief
// size change then asks incremental TUIs to repaint, as in Pi Web.
function createTerminalRedraw(xterm, fit, node, model, current) {
  let ready = false;
  let needsRedraw = false;
  let generation = 0;
  let timer;
  let restore;
  let disposed = false;
  let disconnected = false;
  let frame;
  const document = node.ownerDocument;
  const window = document?.defaultView;
  const listeners = [];

  // Layout may settle one frame after a tab resumes or a font becomes ready.
  // These events never claim input control or focus the terminal.
  function resume() {
    if (disposed || document?.visibilityState === 'hidden' || !current().visible) return;
    update();
    if (ready) xterm.refresh(0, xterm.rows - 1);
    if (frame !== undefined || !window?.requestAnimationFrame) return;
    frame = window.requestAnimationFrame(() => {
      frame = undefined;
      if (disposed || document?.visibilityState === 'hidden' || !current().visible) return;
      update();
      if (ready) xterm.refresh(0, xterm.rows - 1);
    });
  }
  for (const [target, event] of [[document, 'visibilitychange'], [window, 'focus'],
    [window, 'resize'], [window?.visualViewport, 'resize'], [document?.fonts, 'loadingdone']]) {
    if (!target?.addEventListener) continue;
    target.addEventListener(event, resume);
    listeners.push(() => target.removeEventListener(event, resume));
  }
  document?.fonts?.ready?.then(resume, () => {});

  function dimensions() {
    const state = current().state;
    const size = fit.proposeDimensions();
    if (!size || !state.environment) return;
    const cols = Math.min(size.cols, state.environment.maxCols);
    const rows = Math.min(size.rows, state.environment.maxRows);
    if (cols >= 2 && rows >= 1) return { cols, rows };
  }
  function cancel() {
    if (timer === undefined) return;
    clearTimeout(timer);
    timer = undefined;
    const size = dimensions() || restore;
    restore = undefined;
    if (size && current().state.writable) {
      xterm.resize(size.cols, size.rows);
      model.resize(size.cols, size.rows, true);
    }
  }
  function update() {
    const { state, visible } = current();
    if (disposed) return;
    if (state.phase !== "connected") {
      if (!disconnected) generation++;
      disconnected = true;
      ready = false;
      cancel();
      return;
    }
    disconnected = false;
    if (!ready || !visible || document?.visibilityState === 'hidden' || !state.writable || !node.clientWidth || !node.clientHeight) return;
    if (timer !== undefined) return;
    const size = dimensions();
    if (!size) return;
    if (!needsRedraw) {
      fitScreen(xterm, fit, state, model);
      return;
    }
    needsRedraw = false;
    // Respect the host's bounds, even when the view is already at maximum width.
    const tempCols = size.cols < state.environment.maxCols ? size.cols + 1 : size.cols > 2 ? size.cols - 1 : size.cols;
    const tempRows = tempCols !== size.cols ? size.rows : size.rows < state.environment.maxRows ? size.rows + 1 : size.rows > 1 ? size.rows - 1 : size.rows;
    if (tempCols === size.cols && tempRows === size.rows) {
      fitScreen(xterm, fit, state, model);
      return;
    }
    restore = size;
    xterm.resize(tempCols, tempRows);
    // Force both requests: the host's state acknowledgement can lag behind the pulse.
    model.resize(tempCols, tempRows, true);
    timer = setTimeout(() => {
      timer = undefined;
      const latest = dimensions() || restore;
      restore = undefined;
      if (!disposed && current().state.writable && latest) {
        xterm.resize(latest.cols, latest.rows);
        model.resize(latest.cols, latest.rows, true);
      }
    }, 100);
  }
  return {
    prepare() { cancel(); ready = false; needsRedraw = true; return ++generation; },
    parsed(token) { if (!disposed && token === generation) { ready = true; update(); } },
    update,
    dispose() {
      cancel(); disposed = true; generation++;
      for (const remove of listeners) remove();
      if (frame !== undefined) window.cancelAnimationFrame(frame);
    }
  };
}
