function createTerminalTools(xterm, node, model, current) {
  const document = node.ownerDocument, window = document.defaultView;
  const originalPosition = node.style.position;
  node.style.position = 'relative';
  const keyboard = createTerminalKeyboardState(xterm);
  const queries = suppressTerminalQueries(xterm);
  const search = new DshTerminalSearchAddon({highlightLimit: 1000});
  xterm.loadAddon(search);
  xterm.loadAddon(new DshTerminalWebLinksAddon((event, uri) => {
    if (!(event.ctrlKey || event.metaKey)) return;
    try {
      const url = new URL(uri);
      if (url.protocol === 'https:' || url.protocol === 'http:') window.open(url.href, '_blank', 'noopener,noreferrer');
    } catch { /* Ignore malformed links. */ }
  }));

  const toolbar = document.createElement('div');
  toolbar.style.cssText = 'position:absolute;z-index:15;top:8px;right:8px;max-width:calc(100% - 16px);display:flex;flex-wrap:wrap;gap:4px;align-items:center;padding:4px;border-radius:4px;background:var(--dsw-alias-bg-l2,#333);color:var(--dsw-alias-label-primary,white);font:12px system-ui,sans-serif';
  toolbar.setAttribute('role', 'search');
  toolbar.setAttribute('aria-label', 'Terminal search');
  const button = (text, label, action) => {
    const element = document.createElement('button');
    element.type = 'button'; element.textContent = text;
    element.setAttribute('aria-label', label); element.title = label;
    element.addEventListener('click', action);
    toolbar.appendChild(element);
    return element;
  };
  const openButton = button('Find', 'Find in terminal (Ctrl+Shift+F / Cmd+F)', () => open());
  const input = document.createElement('input');
  input.type = 'search'; input.placeholder = 'Find in terminal';
  input.setAttribute('aria-label', 'Find in terminal');
  input.style.cssText = 'width:140px;min-width:60px;max-width:100%;color:inherit;background:transparent;border:1px solid currentColor;border-radius:3px;padding:2px 4px';
  toolbar.appendChild(input);
  const results = document.createElement('span');
  results.setAttribute('role', 'status');
  toolbar.appendChild(results);
  const previous = button('↑', 'Previous match', () => find(true));
  const next = button('↓', 'Next match', () => find(false));
  const closeButton = button('×', 'Close search (Escape)', () => close());
  const fields = [input, results, previous, next, closeButton];
  let opened = false;
  const decorations = {matchBackground: '#665200', matchBorder: '#b89600',
    activeMatchBackground: '#aa6500', activeMatchBorder: '#ffbf47'};
  function find(reverse = false, incremental = false) {
    if (!input.value) { search.clearDecorations(); results.textContent = ''; return; }
    const found = search[reverse ? 'findPrevious' : 'findNext'](input.value, {incremental, decorations});
    if (!found) results.textContent = 'No results';
  }
  const resultListener = search.onDidChangeResults(({resultIndex, resultCount}) => {
    results.textContent = resultCount ? `${resultIndex + 1} / ${resultCount}` : 'No results';
  });
  function open() {
    opened = true; openButton.hidden = true;
    fields.forEach(field => { field.hidden = false; });
    input.focus({preventScroll: true}); input.select();
    find(false, true);
  }
  function close(focus = true) {
    opened = false; openButton.hidden = false;
    fields.forEach(field => { field.hidden = true; });
    search.clearDecorations();
    if (focus) xterm.focus();
  }
  input.addEventListener('input', () => find(false, true));
  toolbar.addEventListener('keydown', event => {
    event.stopPropagation();
    if (event.isComposing || event.keyCode === 229) return;
    if (event.key === 'Escape') { event.preventDefault(); close(); }
    if (event.key === 'Enter') { event.preventDefault(); find(event.shiftKey); }
  });
  close(false);
  node.appendChild(toolbar);
  xterm.attachCustomKeyEventHandler(event => {
    if (event.isComposing || event.keyCode === 229) return true;
    // Let the browser deliver paste and copy a native xterm selection. Ctrl+C
    // without a selection remains application input (SIGINT in legacy mode).
    const key = event.key.toLowerCase();
    // Let the DOM paste event run without xterm also emitting the ^V byte.
    if (event.ctrlKey && !event.altKey && key === 'v') return false;
    // Do not prevent the DOM copy event, but stop xterm from also sending ^C.
    if (event.ctrlKey && !event.altKey && key === 'c' && xterm.hasSelection()) return false;
    if (event.type === 'keydown' && key === 'f' && !event.altKey
      && ((event.ctrlKey && event.shiftKey) || event.metaKey)) {
      event.preventDefault(); open(); return false;
    }
    const data = encodeTerminalKey(event, keyboard.flags());
    if (data === undefined) return true;
    event.preventDefault();
    const live = current();
    if (live.visible && live.state.writable && live.state.phase === 'connected') model.write(data);
    return false;
  });
  return {
    reset() { keyboard.reset(); search.clearDecorations(); if (opened) results.textContent = ''; },
    dispose() {
      xterm.attachCustomKeyEventHandler(() => true);
      resultListener.dispose(); queries.dispose(); keyboard.dispose();
      toolbar.remove(); node.style.position = originalPosition;
      // loadAddon registers the addons for disposal by the owning xterm.
    }
  };
}
