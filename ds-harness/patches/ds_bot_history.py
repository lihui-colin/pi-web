#!/usr/bin/env python3
"""Show ds-bot history independently of a persisted handoff trigger."""
import json
from pathlib import Path
import shutil
import sys

ANCHOR = '// src/client/header-navigation.js'
INSERT = '''// Local compatibility: history belongs to the session, not a handoff row.
function BotHistory({ sessionId, useRoster, actions }) {
  const roster = useRoster(value => value);
  const bot = roster.byId[sessionId];
  const room = roster.roomsById[sessionId];
  const parts = bot?.parts ?? room?.ownParts ?? [];
  return parts.length > 0 ? (0, import_react17.createElement)(EarlierParts, {
    key: sessionId, sessionId, roster, actions
  }) : null;
}
function BotHeroHistory(props) {
  return (0, import_react17.createElement)(import_react17.Fragment, null,
    (0, import_react17.createElement)("style", null,
      '[data-content-phase=hero] [class*="_heroWorkspaceRow"]:has(.bt-history-hero){display:flex!important;order:-1;width:100%;flex-direction:column}' +
      '[data-content-phase=hero] [class*="_heroWorkspaceRow"]:has(.bt-history-hero)>:not([class*="_heroOptions"]){display:none!important}' +
      '[data-content-phase=hero] [class*="_heroOptions"]:has(.bt-history-hero){width:100%}'),
    (0, import_react17.createElement)("div", {
      className: "bt-history-hero",
      style: { maxHeight: "60vh", overflowY: "auto", minWidth: 0, width: "100%" }
    }, (0, import_react17.createElement)(BotHistory, props)));
}

'''

OLD = 'if (source.handoff === true) return (0, import_react17.createElement)(EarlierParts, { sessionId, roster, actions });'
NEW = 'if (source.handoff === true) return null; // History is rendered once by BotHistory.'
HOOK = '    installHeader,\n'
HOOK_NEW = '    () => shadow("conversation.chat.before", { priority: BOT_PRIORITY, inject: face }, BotHistory),\n    () => shadow("conversation.hero.options", { id: "bot-history", order: -100, inject: face }, BotHeroHistory),\n' + HOOK
HOST_ROWS = '\t\t\treturn [\n\t\t\t\t...rows,'
HOST_ROWS_NEW = '\t\t\treturn [\n\t\t\t\t(0, react.createElement)(react.Fragment, { key: "chat-before" }, renderSlot("conversation.chat.before", {}, { fallback: null })),\n\t\t\t\t...rows,'
HOST_SLOT = '\t\t\t\tchildren: { "conversation.chat.node": {'
HOST_SLOT_NEW = '\t\t\t\tchildren: { "conversation.chat.before": { kind: "single", scope: "session" }, "conversation.chat.node": {'


def patch_host(text):
    for old, new in [(HOST_ROWS, HOST_ROWS_NEW), (HOST_SLOT, HOST_SLOT_NEW)]:
        if new in text:
            continue
        if text.count(old) != 1:
            raise ValueError('Unrecognized DSH chat client; review upstream before applying')
        text = text.replace(old, new, 1)
    return text


def patch(text):
    for old, new in [(ANCHOR, INSERT + ANCHOR), (OLD, NEW), (HOOK, HOOK_NEW)]:
        if new in text:
            continue
        if text.count(old) != 1:
            raise ValueError('Unrecognized ds-bot client; inspect upstream before applying')
        text = text.replace(old, new, 1)
    return text


def main():
    package = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / 'data/.dsh/profiles/web/node_modules/ds-bot'
    manifest = json.loads((package / 'package.json').read_text())
    if (manifest.get('name'), manifest.get('version')) != ('ds-bot', '0.2.5'):
        raise SystemExit('Only reviewed ds-bot 0.2.5 is supported')
    executable = shutil.which('dsh')
    if executable is None:
        raise SystemExit('dsh executable not found')
    host = Path(executable).resolve().parents[1] / 'node_modules/@deepseek-ai/dsh-client-ui-chat'
    metadata = json.loads((host / 'package.json').read_text())
    if (metadata.get('name'), metadata.get('version')) != ('@deepseek-ai/dsh-client-ui-chat', '0.2.2-alpha.2'):
        raise SystemExit('Only reviewed DSH chat 0.2.2-alpha.2 is supported')
    path = package / 'client.js'
    original = path.read_text()
    fixed = patch(original)
    host_path = host / 'lib/client.js'
    host_original = host_path.read_text()
    host_fixed = patch_host(host_original)
    # Validate both packages before writing either; no session files are changed.
    if host_fixed != host_original:
        host_path.write_text(host_fixed)
    if fixed != original:
        path.write_text(fixed)
    print('ds-bot history compatibility patch applied')


if __name__ == '__main__':
    main()
