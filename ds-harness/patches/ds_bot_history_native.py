#!/usr/bin/env python3
"""Expose archived Bot parts through the native conversation and ChatFlow."""
from pathlib import Path
import json
import shutil
if __package__:
    from .ds_bot_patch_common import replace_once, publish
    from .ds_bot_history import HOST_ROWS, HOST_ROWS_NEW, HOST_SLOT, HOST_SLOT_NEW, OLD, NEW, ANCHOR, HOOK
else:
    from ds_bot_patch_common import replace_once, publish
    from ds_bot_history import HOST_ROWS, HOST_ROWS_NEW, HOST_SLOT, HOST_SLOT_NEW, OLD, NEW, ANCHOR, HOOK

INSERT = '''// Local compatibility: archived parts are conversation content, not Hero options.
function BotHistoryPresence({ sessionId, useRoster, onHistory }) {
  const roster = useRoster(value => value);
  const parts = roster.byId[sessionId]?.parts ?? roster.roomsById[sessionId]?.ownParts ?? [];
  const present = parts.length > 0;
  (0, import_react17.useLayoutEffect)(() => {
    onHistory(sessionId, present);
  }, [sessionId, present, onHistory]);
  return null;
}
function BotNativeHistory({ sessionId, useRoster, actions }) {
  const roster = useRoster(value => value);
  const parts = roster.byId[sessionId]?.parts ?? roster.roomsById[sessionId]?.ownParts ?? [];
  return parts.length > 0 ? (0, import_react17.createElement)(EarlierParts, {
    key: sessionId, sessionId, roster, actions
  }) : null;
}

'''
HOOK_NEW = '''    () => shadow("conversation.historyPresence", { priority: BOT_PRIORITY, inject: face }, BotHistoryPresence),
    () => shadow("conversation.chat.before", { priority: BOT_PRIORITY, inject: face }, BotNativeHistory),
''' + HOOK
ROOT_STATE = '\t\t\tconst { sessionId, useSession, useSessions, useConversation, renderSlot, renderFactorySlot } = props;'
ROOT_STATE_NEW = ROOT_STATE + '''
			const [historyContent, setHistoryContent] = (0, react.useState)(null);
			const onHistory = (0, react.useCallback)((id, present) => {
				setHistoryContent(previous => previous?.id === id && previous?.present === present ? previous : { id, present });
			}, []);
			const hasHistoryContent = historyContent?.id === sessionId && historyContent?.present === true;'''
HERO = 'const hero = sessionId === void 0 || shellPhase === "blank" && (openState === "open" || summaryBlank === true);'
HERO_NEW = 'const hero = sessionId === void 0 || !hasHistoryContent && shellPhase === "blank" && (openState === "open" || summaryBlank === true);'
CHILD = 'children: [renderSlot("conversation.header", {}), renderFactorySlot("conversation.content", {'
CHILD_NEW = 'children: [renderSlot("conversation.historyPresence", { onHistory }, { fallback: null }), renderSlot("conversation.header", {}), renderFactorySlot("conversation.content", {'
DECLARE = 'children: { "conversation.header": {'
DECLARE_NEW = 'children: { "conversation.historyPresence": { kind: "single", scope: "session-maybe" }, "conversation.header": {'

VIEW_REPLACEMENTS = [
    ('phase,\n\t\t\t\t\thero\n\t\t\t\t}', 'phase,\n\t\t\t\t\thero,\n\t\t\t\t\thasHistoryContent\n\t\t\t\t}'),
    ('function ConversationSessionView({ renderSlot }) {\n\t\t\treturn renderSlot("conversation.session", {});', 'function ConversationSessionView({ renderSlot, hasHistoryContent }) {\n\t\t\treturn renderSlot("conversation.session", { hasHistoryContent });'),
    ('(0, react_jsx_runtime.jsx)(Views, {})', '(0, react_jsx_runtime.jsx)(Views, { hasHistoryContent: props.hasHistoryContent })'),
    ('function DefaultConversationViews({ view, useSession,', 'function DefaultConversationViews({ hasHistoryContent = false, view, useSession,'),
    ('if (session.blank && conversationPhase(session, conversation) === "blank") return null;', 'if (!hasHistoryContent && session.blank && conversationPhase(session, conversation) === "blank") return null;'),
]

def patch(text, replacements):
    if 'function BotHeroHistory(' in text:
        raise ValueError('Legacy Hero history patch found; restore the release bundle first')
    for old, new in replacements:
        text = replace_once(text, old, new)
    return text

def plan_changes():
    root = Path(__file__).resolve().parents[1]
    bot = root / 'data/.dsh/profiles/web/node_modules/ds-bot'
    executable = shutil.which('dsh')
    if executable is None:
        raise ValueError('dsh executable not found')
    host = Path(executable).resolve().parents[1] / 'node_modules/@deepseek-ai'
    packages = [(bot, 'ds-bot', '0.2.6'), (host/'dsh-client-ui-chat', '@deepseek-ai/dsh-client-ui-chat', '0.2.2-alpha.2'), (host/'dsh-client-ui-conversation', '@deepseek-ai/dsh-client-ui-conversation', '0.2.2-alpha.2')]
    for directory, name, version in packages:
        manifest = json.loads((directory/'package.json').read_text())
        if (manifest.get('name'), manifest.get('version')) != (name, version):
            raise ValueError('Unsupported version; review before applying')
    files = [(bot/'client.js', [(ANCHOR, INSERT+ANCHOR), (OLD, NEW), (HOOK, HOOK_NEW)]), (host/'dsh-client-ui-chat/lib/client.js', [(HOST_ROWS, HOST_ROWS_NEW), (HOST_SLOT, HOST_SLOT_NEW)]), (host/'dsh-client-ui-conversation/lib/client.js', [(ROOT_STATE, ROOT_STATE_NEW), (HERO, HERO_NEW), (CHILD, CHILD_NEW), (DECLARE, DECLARE_NEW)] + VIEW_REPLACEMENTS)]
    changes = []
    for path, replacements in files:
        original = path.read_text()
        fixed = patch(original, replacements)
        changes.append((path, original, fixed))
    return changes


def main():
    publish(plan_changes())
    print('Native history integration applied; no CSS or Hero history container added.')

if __name__ == '__main__':
    main()
