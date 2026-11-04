// OSC 52 is emitted by TUIs such as Codex after mouse selection. Collect it
// at xterm write boundaries so a restored snapshot can never copy old text.
function createTerminalClipboard(xterm, node) {
  let pending, notice, timer, serial = 0, disposed = false;
  const originalPosition = node.style.position;
  const handler = xterm.parser.registerOscHandler(52, data => {
    const separator = data.indexOf(';');
    if (separator < 0 || !/^[cs]*$/.test(data.slice(0, separator))) return true;
    const payload = data.slice(separator + 1);
    if (!payload || payload === '?' || payload.length > 1048576) return true;
    try {
      const binary = atob(payload);
      const bytes = Uint8Array.from(binary, character => character.charCodeAt(0));
      pending = new TextDecoder('utf-8', {fatal: true}).decode(bytes) || pending;
    } catch { /* Ignore invalid base64 or UTF-8. */ }
    return true;
  });
  function clear() {
    if (timer !== undefined) clearTimeout(timer);
    timer = undefined;
    notice?.remove();
    notice = undefined;
  }
  function show(message, retry) {
    clear();
    node.style.position = 'relative';
    notice = document.createElement('div');
    notice.setAttribute('role', 'status');
    notice.style.cssText = 'position:absolute;z-index:20;bottom:8px;left:50%;transform:translateX(-50%);display:flex;gap:8px;align-items:center;max-width:calc(100% - 24px);padding:6px 10px;border-radius:6px;background:var(--dsw-alias-bg-l2, #333);color:var(--dsw-alias-label-primary, white);font:12px system-ui,sans-serif;box-shadow:0 2px 8px #0005';
    const label = document.createElement('span');
    label.textContent = message;
    notice.appendChild(label);
    if (retry) {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = 'Copy';
      button.addEventListener('click', retry);
      notice.appendChild(button);
      const dismiss = document.createElement('button');
      dismiss.type = 'button';
      dismiss.textContent = '×';
      dismiss.setAttribute('aria-label', 'Dismiss');
      dismiss.addEventListener('click', () => { serial++; clear(); });
      notice.appendChild(dismiss);
    }
    node.appendChild(notice);
  }
  function selectionCopy(text) {
    const input = document.createElement('textarea');
    input.value = text;
    input.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0';
    const focus = document.activeElement;
    document.body.appendChild(input);
    input.focus({preventScroll:true});
    input.select();
    try { return document.execCommand('copy'); }
    catch { return false; }
    finally { input.remove(); focus?.focus?.({preventScroll:true}); }
  }
  async function copy(text, explicit = false) {
    const token = ++serial;
    clear();
    let success = false;
    try {
      if (typeof navigator.clipboard?.writeText === 'function') {
        await navigator.clipboard.writeText(text);
        success = true;
      } else if (explicit) success = selectionCopy(text);
    } catch { if (explicit) success = selectionCopy(text); }
    if (disposed || token !== serial) return;
    if (!success) {
      show('Automatic copy was blocked.', () => { void copy(text, true); });
      return;
    }
    show('Copied');
    timer = setTimeout(clear, 2000);
  }
  return {
    finish(live) {
      const text = pending;
      pending = undefined;
      if (live && text !== undefined && !disposed) void copy(text);
    },
    dispose() { disposed = true; serial++; handler.dispose(); pending = undefined; clear(); node.style.position = originalPosition; }
  };
}
