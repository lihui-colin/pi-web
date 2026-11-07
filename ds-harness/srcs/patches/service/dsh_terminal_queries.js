// The host's headless xterm answers these queries even without an attached UI.
// Browser views consume the same requests so reconnection/multiple views do
// not send duplicate device/status/mode replies into the application's input.
function suppressTerminalQueries(screen) {
  const handlers = [
    [{final: 'c'}, params => !params[0]],
    [{prefix: '>', final: 'c'}, params => !params[0]],
    [{final: 'n'}, params => params[0] === 5 || params[0] === 6],
    [{prefix: '?', final: 'n'}, params => params[0] === 6],
    [{intermediates: '$', final: 'p'}, () => true],
    [{prefix: '?', intermediates: '$', final: 'p'}, () => true]
  ].map(([id, handler]) => screen.parser.registerCsiHandler(id, handler));
  handlers.push(screen.parser.registerDcsHandler({intermediates: '$', final: 'q'}, () => true));
  return {dispose() { handlers.forEach(handler => handler.dispose()); }};
}

function createTerminalHostProtocol(screen, handle, running) {
  let pending = '', disposed = false;
  function reply(data) {
    // Bound generated replies just as the host bounds attached output queues.
    if (!disposed && pending.length + data.length <= 65536) pending += data;
  }
  const keyboard = createTerminalKeyboardState(screen, reply);
  const responses = screen.onData(reply);
  return {
    snapshot: data => keyboard.snapshot(data),
    async flush() {
      const data = pending;
      pending = '';
      if (!data || disposed || !running()) return;
      try { await handle.write(data); }
      catch (error) { if (!disposed && running()) throw error; }
    },
    dispose() { disposed = true; pending = ''; responses.dispose(); keyboard.dispose(); }
  };
}
