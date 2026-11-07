// xterm serialize 0.14 preserves screen content and most modes, but omits
// mouse encoding, cursor visibility, and synchronized output. The public
// modes API does not expose the first two; these fields are from headless 6.0.0.
function terminalSnapshotModes(screen) {
  const mouse = screen._core.coreMouseService.activeEncoding;
  const encoding = { DEFAULT: "", SGR: "\x1b[?1006h", SGR_PIXELS: "\x1b[?1016h" }[mouse];
  if (encoding === undefined) throw new Error(`Unsupported xterm mouse encoding: ${mouse}`);
  return encoding + (screen._core.coreService.isCursorHidden ? "\x1b[?25l" : "")
    + (screen.modes.synchronizedOutputMode ? "\x1b[?2026h" : "");
}
