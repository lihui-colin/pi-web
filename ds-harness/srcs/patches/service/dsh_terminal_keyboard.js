// Shared by the retained headless terminal and each browser view. Use xterm's
// parser so fragmented CSI, OSC payloads and alternate buffers stay ordered.
function createTerminalKeyboardState(screen, reply = () => {}) {
  const stacks = {normal: [0], alternate: [0]};
  const subscriptions = [];
  const active = () => stacks[screen.buffer.active.type];
  const flags = () => active().at(-1);
  const reset = () => { stacks.normal = [0]; stacks.alternate = [0]; };
  const register = (prefix, handler) => subscriptions.push(screen.parser.registerCsiHandler(
    {prefix, final: 'u'}, params => { handler(params); return true; }));
  // Implement disambiguation (flag 1); do not advertise release events,
  // alternate layouts or all-key reporting that the browser cannot provide.
  register('>', params => {
    const stack = active();
    if (stack.length === 32) stack.shift();
    stack.push((params[0] || 0) & 1);
  });
  register('<', params => {
    const stack = active();
    stack.splice(Math.max(0, stack.length - (params[0] || 1)));
    if (!stack.length) stack.push(0);
  });
  register('=', params => {
    const stack = active(), requested = (params[0] || 0) & 1, mode = params[1] || 1;
    if (mode === 1) stack[stack.length - 1] = requested;
    if (mode === 2) stack[stack.length - 1] |= requested;
    if (mode === 3) stack[stack.length - 1] &= ~requested;
  });
  register('?', () => reply(`\x1b[?${flags()}u`));
  subscriptions.push(screen.parser.registerEscHandler({final: 'c'}, () => { reset(); return false; }));
  function restore(stack) {
    return '\x1b[<32u' + `\x1b[=${stack[0]};1u` + stack.slice(1).map(value => `\x1b[>${value}u`).join('');
  }
  return {
    flags, reset,
    // A browser snapshot starts on an empty normal screen. Seed both mode
    // stacks before serialize restores text, scrollback and the active buffer.
    snapshot: data => restore(stacks.normal) + '\x1b[?1047h' + restore(stacks.alternate) + '\x1b[?1047l' + data,
    dispose() { subscriptions.forEach(subscription => subscription.dispose()); reset(); }
  };
}

function encodeTerminalKey(event, flags) {
  if (!(flags & 1) || event.type !== 'keydown' || event.isComposing || event.keyCode === 229
    || event.key === 'Dead' || event.key === 'Process' || event.getModifierState?.('AltGraph')) return;
  // Leave browser/OS Command shortcuts alone. Plain text and IME still use
  // xterm's input/composition path; only negotiated control keys are encoded.
  if (event.metaKey) return;
  const modifiers = 1 + (event.shiftKey ? 1 : 0) + (event.altKey ? 2 : 0) + (event.ctrlKey ? 4 : 0);
  const functional = {ArrowUp: [1, 'A'], ArrowDown: [1, 'B'], ArrowRight: [1, 'C'], ArrowLeft: [1, 'D'],
    Home: [1, 'H'], End: [1, 'F'], Insert: [2, '~'], Delete: [3, '~'], PageUp: [5, '~'], PageDown: [6, '~'],
    F1: [1, 'P'], F2: [1, 'Q'], F3: [13, '~'], F4: [1, 'S'], F5: [15, '~'], F6: [17, '~'],
    F7: [18, '~'], F8: [19, '~'], F9: [20, '~'], F10: [21, '~'], F11: [23, '~'], F12: [24, '~']};
  // Canonical function/cursor keys also avoid F3/CPR ambiguity and SS3 modes.
  const functionKey = functional[event.key];
  if (functionKey) return `\x1b[${functionKey[0]};${modifiers}${functionKey[1]}`;
  const controls = {Enter: 13, Tab: 9, Backspace: 127, Escape: 27};
  let code = controls[event.key];
  if (code !== undefined) {
    if (event.key !== 'Escape' && modifiers === 1) return;
  } else if (Array.from(event.key || '').length === 1 && (event.ctrlKey || event.altKey)) {
    const shifted = '~!@#$%^&*()_+{}|:"<>?';
    const unshifted = '`1234567890-=[]\\;\',./';
    const index = event.shiftKey ? shifted.indexOf(event.key) : -1;
    code = (index >= 0 ? unshifted[index] : event.key.toLowerCase()).codePointAt(0);
  } else return;
  return `\x1b[${code};${modifiers}u`;
}
