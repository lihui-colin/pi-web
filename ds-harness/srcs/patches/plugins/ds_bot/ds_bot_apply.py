#!/usr/bin/env python3
"""Migrate reviewed DS Bot / DSH fixes without overriding upstream behavior.

DS Bot 0.3.1 / DSH 0.2.2-rc.1 uses upstream history, prompt and touch handling.
Only local layout preferences and mobile sidebar compatibility remain.
The reviewed 0.2.7 route retains its original layout transforms.
The isolated 0.2.6 / alpha.2 route remains available for existing old installs.
"""
from pathlib import Path

if not __package__:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from patches.common import COMPONENT_ROOT, host_directory, publish, read_change, replace_once, verify_package, patch_cli


# History compatibility
HISTORY_ANCHOR = '// src/client/header-navigation.js'

HISTORY_OLD = 'if (source.handoff === true) return (0, import_react17.createElement)(EarlierParts, { sessionId, roster, actions });'

HISTORY_NEW = 'if (source.handoff === true) return null; // History is rendered once by BotHistory.'

HISTORY_HOOK = '    installHeader,\n'

HISTORY_HOST_ROWS = '\t\t\treturn [\n\t\t\t\t...rows,'

HISTORY_HOST_ROWS_NEW = '\t\t\treturn [\n\t\t\t\t(0, react.createElement)(react.Fragment, { key: "chat-before" }, renderSlot("conversation.chat.before", {}, { fallback: null })),\n\t\t\t\t...rows,'

HISTORY_HOST_SLOT = '\t\t\t\tchildren: { "conversation.chat.node": {'

HISTORY_HOST_SLOT_NEW = '\t\t\t\tchildren: { "conversation.chat.before": { kind: "single", scope: "session" }, "conversation.chat.node": {'

HISTORY_INSERT = '''// Local compatibility: archived parts are conversation content, not Hero options.
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

HISTORY_HOOK_NEW = '''    () => shadow("conversation.historyPresence", { priority: BOT_PRIORITY, inject: face }, BotHistoryPresence),
    () => shadow("conversation.chat.before", { priority: BOT_PRIORITY, inject: face }, BotNativeHistory),
''' + HISTORY_HOOK

HISTORY_ROOT_STATE = '\t\t\tconst { sessionId, useSession, useSessions, useConversation, renderSlot, renderFactorySlot } = props;'

HISTORY_ROOT_STATE_NEW = HISTORY_ROOT_STATE + '''
			const [historyContent, setHistoryContent] = (0, react.useState)(null);
			const onHistory = (0, react.useCallback)((id, present) => {
				setHistoryContent(previous => previous?.id === id && previous?.present === present ? previous : { id, present });
			}, []);
			const hasHistoryContent = historyContent?.id === sessionId && historyContent?.present === true;'''

HISTORY_HERO = 'const hero = sessionId === void 0 || shellPhase === "blank" && (openState === "open" || summaryBlank === true);'

HISTORY_HERO_NEW = 'const hero = sessionId === void 0 || !hasHistoryContent && shellPhase === "blank" && (openState === "open" || summaryBlank === true);'

HISTORY_CHILD = 'children: [renderSlot("conversation.header", {}), renderFactorySlot("conversation.content", {'

HISTORY_CHILD_NEW = 'children: [renderSlot("conversation.historyPresence", { onHistory }, { fallback: null }), renderSlot("conversation.header", {}), renderFactorySlot("conversation.content", {'

HISTORY_DECLARE = 'children: { "conversation.header": {'

HISTORY_DECLARE_NEW = 'children: { "conversation.historyPresence": { kind: "single", scope: "session-maybe" }, "conversation.header": {'

HISTORY_VIEW_REPLACEMENTS = [
    ('phase,\n\t\t\t\t\thero\n\t\t\t\t}', 'phase,\n\t\t\t\t\thero,\n\t\t\t\t\thasHistoryContent\n\t\t\t\t}'),
    ('function ConversationSessionView({ renderSlot }) {\n\t\t\treturn renderSlot("conversation.session", {});', 'function ConversationSessionView({ renderSlot, hasHistoryContent }) {\n\t\t\treturn renderSlot("conversation.session", { hasHistoryContent });'),
    ('(0, react_jsx_runtime.jsx)(Views, {})', '(0, react_jsx_runtime.jsx)(Views, { hasHistoryContent: props.hasHistoryContent })'),
    ('function DefaultConversationViews({ view, useSession,', 'function DefaultConversationViews({ hasHistoryContent = false, view, useSession,'),
    ('if (session.blank && conversationPhase(session, conversation) === "blank") return null;', 'if (!hasHistoryContent && session.blank && conversationPhase(session, conversation) === "blank") return null;'),
]

def patch_history(text, replacements):
    if 'function BotHeroHistory(' in text:
        raise ValueError('Legacy Hero history patch found; restore the release bundle first')
    for old, new in replacements:
        text = replace_once(text, old, new)
    return text


# Mobile compatibility
MOBILE_GRID = '[class*="_frame"][data-sidebar-collapsed][data-rightbar-collapsed]:has(>[class*="_sidebarCol"]){grid-template-columns:0px minmax(0,1fr) 0px!important}'

MOBILE_GRID_FIXED = MOBILE_GRID + '''
/* dsh-web-mobile removes the host sidebar from grid flow on touch screens. */
@media (max-width:1023px) and (pointer:coarse){
html [data-mobile-nav="frame"][data-sidebar-collapsed][data-rightbar-collapsed]:has(>[class*="_sidebarCol"]){grid-template-columns:minmax(0,1fr) 0 0!important}
}'''

MOBILE_TRACK = '''var sidebarTrackWidth = () => typeof document === "undefined" ? null : document.querySelector('[class*="_sidebarCol"]')?.getBoundingClientRect().width ?? null;'''

MOBILE_TRACK_FIXED = '''var sidebarTrackWidth = () => {
  if (typeof document === "undefined") return null;
  const column = document.querySelector('[class*="_sidebarCol"]');
  if (!column) return null;
  // An overlay drawer occupies no layout track, even when its box has width.
  const position = getComputedStyle(column).position;
  return position === "absolute" || position === "fixed" ? 0 : column.getBoundingClientRect().width;
};'''

MOBILE_PHONE_CSS = '''
/* Phone reading layout: use the chat width, float tools instead of reserving 82px. */
@media (max-width:640px) and (pointer:coarse){
  body .bt-msg,body .bt-astack[data-lead]>.bt-msg{max-width:100%}
  body .bt-msg>.bt-msg-line{max-width:100%;min-width:0}
  body .bt-tools{top:-14px;right:0;left:auto;margin-left:0;transform:none;padding:2px;border-radius:999px;background:var(--bt-card);box-shadow:0 4px 14px rgba(0,0,0,.14)}
  body .bt-tools::after{display:none}
}
'''

MOBILE_COMPOSER = '[data-composer-card] [class*="_trailing"]{gap:8px!important}'

MOBILE_COMPOSER_CSS = '''
/* Keep typing full-width; actions occupy their own row below on every screen. */
  html body [data-composer-card]{border-radius:18px!important}
  html body [data-composer-card]>[data-input-scroll]{order:1!important;flex:0 0 100%!important;box-sizing:border-box;min-width:0!important;margin:0 0 6px!important}
  html body [data-composer-card] [class*="_tools"]{order:2!important;gap:8px!important}
  html body [data-composer-card] [class*="_trailing"]{order:3!important;margin-left:auto!important}
'''

VOICE_POSITION_LEGACY_CSS = '''
/* The empty-draft voice action shares the send button's rightmost seat.
   Flatten only visible standard controls; activity mode keeps them hidden. */
html body [data-composer-card] [class*="_standardControls"]:has(>.bt-voice):not([hidden]){display:contents!important}
html body [data-composer-card] [class*="_trailing"]>.bt-voice,
html body [data-composer-card] [class*="_trailing"]>[class*="_standardControls"]>.bt-voice{order:10!important}
'''

VOICE_POSITION_CSS = VOICE_POSITION_LEGACY_CSS.replace(
    ':has(>.bt-voice)', ':has(.bt-voice)',
).replace(
    'html body [data-composer-card] [class*="_trailing"]>.bt-voice,\n'
    'html body [data-composer-card] [class*="_trailing"]>[class*="_standardControls"]>.bt-voice',
    'html body [data-composer-card] [class*="_trailing"] .bt-voice',
)

MOBILE_GROUP_OLD = '''      { className: "bt-group-name", style: flat ? void 0 : { color: inkText(colorOf(bot)) } },
      flat ? lead : null,
      bot.name,
      room2?.admin === bot.id ? (0, import_react17.createElement)("span", { className: "bt-group-role" }, t("Admin")) : null,
      Number.isFinite(time) ? (0, import_react17.createElement)("span", { className: "bt-group-time", title: clockLabel(time) }, messageClock(time)) : null,
      took ? (0, import_react17.createElement)("span", { className: "bt-group-took", title: t("Ran for {duration}", { duration: took }) }, took) : null
    ),
    (0, import_react17.createElement)(Bubbles, { texts: texts2, roster, selfId: bot.id, actions, sessionId: room2?.id, msgKey, useUi, lead: flat ? null : lead, whole })'''

MOBILE_GROUP_NEW = MOBILE_GROUP_OLD.replace('className: "bt-group-name"', 'className: "bt-group-name bt-reply-meta"').replace('      flat ? lead : null,\n', '').replace('      took ?', '      lead,\n      took ?').replace('useUi, lead: flat ? null : lead, whole', 'useUi, whole')

MOBILE_GROUP_LEFT = MOBILE_GROUP_NEW.replace('      lead,\n', '').replace('      Number.isFinite(time) ?', '      lead,\n      Number.isFinite(time) ?')

MOBILE_META_CSS = '.bt-group-name>.bt-lead{margin:0 8px 0 0}'

MOBILE_META_FIXED = MOBILE_META_CSS + '''
/* Keep the clickable sender avatar beside the timestamp, outside the bubble. */
.bt-group-name.bt-reply-meta{display:flex;align-items:center;flex-wrap:wrap;column-gap:.4em;margin-inline-start:0}
.bt-group-name.bt-reply-meta>.bt-lead{margin:0}
'''

MOBILE_RAIL_CSS = '.bt-rail .bt-row{justify-content:center;width:56px;height:56px;min-height:56px;padding:0;border-radius:16px}'

MOBILE_RAIL_FIXED = MOBILE_RAIL_CSS + '''
/* Narrow navigation remains identifiable on both mouse and touch screens. */
.bt-rail .bt-row[title]{flex-direction:column;flex-shrink:0;width:90%;height:auto;min-height:0;padding:.45em .25em;gap:.25em}
.bt-rail .bt-row[title]::after{content:attr(title);display:block;flex:none;width:100%;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:center;font-size:.75rem;line-height:1.3;font-weight:500;color:var(--bt-ink)}
.bt-rail .bt-rail-top{align-self:stretch}
'''

def patch_mobile(text, react_alias='import_react17', *, phone_layout=True):
    for old, new in (
        (MOBILE_GRID, MOBILE_GRID_FIXED), (MOBILE_TRACK, MOBILE_TRACK_FIXED),
        (MOBILE_GROUP_OLD, MOBILE_GROUP_LEFT), (MOBILE_META_CSS, MOBILE_META_FIXED),
        (MOBILE_RAIL_CSS, MOBILE_RAIL_FIXED), (MOBILE_COMPOSER, MOBILE_COMPOSER + MOBILE_COMPOSER_CSS),
    ):
        text = replace_once(text, old.replace('import_react17', react_alias),
                            new.replace('import_react17', react_alias))
    if phone_layout:
        text = replace_once(text, MOBILE_GRID_FIXED, MOBILE_GRID_FIXED + MOBILE_PHONE_CSS)
    else:
        # 0.3.1 styles.js owns touch toolbar placement and 44px hit targets.
        # Full-width bubbles are already handled by ALIGN_CSS at every width.
        text = retire_replacements(text, [(MOBILE_GRID_FIXED, MOBILE_GRID_FIXED + MOBILE_PHONE_CSS)])
    if VOICE_POSITION_LEGACY_CSS in text:
        text = replace_once(text, VOICE_POSITION_LEGACY_CSS, VOICE_POSITION_CSS)
    text = replace_once(text, MOBILE_COMPOSER_CSS, MOBILE_COMPOSER_CSS + VOICE_POSITION_CSS)
    return text


# Restore the host's existing width controls on desktop; do not implement another dragger.
WIDTH_HANDLES = '[class*="_widthHandle"]{display:none!important}'
WIDTH_HANDLES_FIXED = '''/* Keep touch/narrow layouts unchanged; desktop uses DSH's native handles. */
@media (max-width:1023px),(pointer:coarse),(hover:none){
''' + WIDTH_HANDLES + '\n}'

WIDTH_BODY = '[class*="_body"]:has(> [class*="_scrollBody"]){--dsh-chat-content-width:min(960px,100%)}'
WIDTH_BODY_FIXED = WIDTH_BODY + '''
/* DS Bot registers these properties as non-inheriting for resize performance.
   Opt the desktop body back into the host root's live width axis only. */
@media (min-width:1024px) and (pointer:fine) and (hover:hover){
  [class*="_body"]:has(> [class*="_scrollBody"]){
    --dsh-conversation-column-width:inherit;
    --dsh-chat-user-width:inherit;
    --dsh-chat-content-width:var(--dsh-chat-user-width,clamp(680px,calc(var(--dsh-conversation-column-width,0px) * .64),920px));
  }
}
'''

WIDTH_COMPOSER = '[class*="_root"]:has(> [data-composer-card])>[data-composer-card]{max-width:min(992px,100%)!important}'
WIDTH_COMPOSER_FIXED = WIDTH_COMPOSER + '''
@media (min-width:1024px) and (pointer:fine) and (hover:hover){
  [class*="_root"]:has(> [data-composer-card])>[data-composer-card]{max-width:min(var(--dsh-composer-card-max-width,992px),100%)!important}
}
'''


# Bubble replies share the transcript's right edge with outgoing messages.
ALIGN_ANCHOR = 'body[data-bt-layout=flat] .bt-tools::after{display:none}'
ALIGN_CSS = '''
/* Keep reply bubbles and left-aligned text; use the full transcript width. */
body[data-bt-layout=bubble] .bt-astack{align-items:stretch}
body[data-bt-layout=bubble] .bt-astack>.bt-msg{align-items:stretch;min-width:0;max-width:100%}
body[data-bt-layout=bubble] .bt-msg-line{min-width:0}
body[data-bt-layout=bubble] .bt-msg-line>.bt-bubble{flex:1;min-width:0}
/* Both layouts keep message actions in a separate flow row below the reply. */
body[data-bt-layout] .bt-msg>.bt-msg-line{flex-wrap:wrap;row-gap:4px}
body[data-bt-layout] .bt-msg>.bt-msg-line>.bt-tools{position:static;flex:0 0 100%;justify-content:flex-start;margin:0;transform:none;padding:0;border-radius:0;background:none;box-shadow:none}
body[data-bt-layout] .bt-msg>.bt-msg-line>.bt-tools::after{display:none}
'''
TOUCH_ACTIONS_CSS = '''
/* Touch users can access reply actions without first tapping the message. */
@media (hover:none),(pointer:coarse){
  body[data-bt-layout] .bt-msg>.bt-msg-line>.bt-tools{opacity:1;visibility:visible}
}
'''


MORE_BUTTON = '''    (0, import_react17.createElement)("button", { type: "button", className: "bt-tool", "aria-label": t("More message actions"), title: t("More"), "aria-haspopup": "menu", "aria-expanded": panel?.kind === "more", onClick: (event) => open("more", event) }, copied ? (0, import_react17.createElement)(CheckIcon) : (0, import_react17.createElement)(DotsIcon)),'''
DIRECT_BUTTONS = '''    (0, import_react17.createElement)("button", { type: "button", className: "bt-tool", "aria-label": copied ? t("Copied") : t("Copy"), title: copied ? t("Copied") : t("Copy"), onClick: copy2 }, (0, import_react17.createElement)(copied ? CheckIcon : CopyIcon)),
    (0, import_react17.createElement)("button", { type: "button", className: "bt-tool", "aria-label": t("Download"), title: t("Download"), onClick: download2 }, (0, import_react17.createElement)(DownloadIcon)),'''
MORE_ITEM = '''  const item = (label, Icon, run2) => (0, import_react17.createElement)("button", { key: label, type: "button", role: "menuitem", onClick: () => {
    close();
    run2();
  } }, (0, import_react17.createElement)(Icon), label);'''
MORE_PORTAL = '''    panel?.kind === "more" ? (0, import_react_dom.createPortal)((0, import_react17.createElement)(
      "div",
      { ref: pop, className: "bt-menu", role: "menu", "aria-label": t("Message actions"), style: place },
      item(t("Copy"), CopyIcon, copy2),
      item(t("Download"), DownloadIcon, download2)
    ), document.body) : null'''
MESSAGE_ACTION_REPLACEMENTS = [
    (MORE_BUTTON, DIRECT_BUTTONS),
    (MORE_ITEM, '  // Copy and download are direct message actions.'),
    (MORE_PORTAL, '    // Message actions no longer need a More popup.'),
    ('''    const below = rect.bottom + 220 < viewBottom();
    return panel.kind === "react" ? { left: Math.min(Math.max(rect.left + rect.width / 2, STRIP_HALF), window.innerWidth - STRIP_HALF), top: rect.top - 6, "--bt-origin": "bottom center" } : { left: Math.min(rect.left, window.innerWidth - 208), ...below ? { top: rect.bottom + 4 } : { bottom: viewBottom() - rect.top + 4, "--bt-origin": "bottom left" } };''',
     '''    return { left: Math.min(Math.max(rect.left + rect.width / 2, STRIP_HALF), window.innerWidth - STRIP_HALF), top: rect.top - 6, "--bt-origin": "bottom center" };'''),
]


def patch_presentation(text, react_alias='import_react17', react_dom_alias='import_react_dom'):
    for old, new in [
        (WIDTH_HANDLES, WIDTH_HANDLES_FIXED), (WIDTH_BODY, WIDTH_BODY_FIXED),
        (WIDTH_COMPOSER, WIDTH_COMPOSER_FIXED), (ALIGN_ANCHOR, ALIGN_ANCHOR + ALIGN_CSS),
        (ALIGN_CSS, ALIGN_CSS + TOUCH_ACTIONS_CSS),
        *MESSAGE_ACTION_REPLACEMENTS,
    ]:
        text = replace_once(text, old.replace('import_react17', react_alias).replace('import_react_dom', react_dom_alias),
                            new.replace('import_react17', react_alias).replace('import_react_dom', react_dom_alias))
    return text


# Prompt compatibility
PROMPT_OLD = '        tools: assembled.tools.filter(tool => !HIDDEN_TOOLS.includes(tool.name)),'

# Recognize the already-applied patch on current 0.2.6 installations during consolidation.
# This is a source migration, not support for older package/host versions.
PROMPT_APPLIED_026 = '''        // New DSH attaches provider-owned tools after the prompt waterfall.
        // Older hosts still expose tools here; preserve their filtering.
        ...(Array.isArray(assembled.tools) ? {
          tools: assembled.tools.filter(tool => !HIDDEN_TOOLS.includes(tool.name)),
        } : {}),'''

PROMPT_NEW = '        // DSH 0.2.2-alpha.2 attaches provider-owned tools after this waterfall.'

def patch_prompt(text):
    if PROMPT_APPLIED_026 in text:
        text = replace_once(text, PROMPT_APPLIED_026, PROMPT_NEW)
    return replace_once(text, PROMPT_OLD, PROMPT_NEW)


# Composer compatibility
COMPOSER_ANCHOR = '''\t\t\t\tif (event !== null && isComposingEvent(event, recentlyComposing)) return true;
\t\t\t\tif (handlers.arbitrate("enter", false) !== "pass") {'''

COMPOSER_REPLACEMENT = COMPOSER_ANCHOR.replace(
    '\t\t\t\tif (handlers.arbitrate',
    '\t\t\t\t// Mobile Enter inserts a line break without submitting the draft.\n'
    '\t\t\t\tif ((0, _deepseek_ai_dsh_client_ui_primitives.isMobileDevice)()) {\n'
    '\t\t\t\t\tevent?.preventDefault();\n'
    '\t\t\t\t\treturn editor.dispatchCommand(Ue$2, false);\n'
    '\t\t\t\t}\n'
    '\t\t\t\tif (handlers.arbitrate',
)

def patch_composer(text):
    return replace_once(text, COMPOSER_ANCHOR, COMPOSER_REPLACEMENT)


def retire_replacements(text, replacements):
    """Undo only complete, uniquely recognized local edits; accept pristine source."""
    for original, fixed in reversed(replacements):
        if fixed in text:
            if text.count(fixed) != 1:
                raise ValueError('Duplicate retired patch; inspect before migrating')
            text = text.replace(fixed, original, 1)
        if text.count(original) != 1:
            raise ValueError('Unknown or mixed retired patch; inspect before migrating')
    return text


def retire_composer(text):
    """mobile 3.3.0 owns Enter, including modifier keys and trigger menus."""
    text = retire_replacements(text, [(COMPOSER_ANCHOR, COMPOSER_REPLACEMENT)])
    if '// Mobile Enter inserts a line break' in text:
        raise ValueError('Incomplete retired composer patch')
    return text


def retire_host_history(text, replacements):
    text = retire_replacements(text, replacements)
    if any(marker in text for marker in ('hasHistoryContent', 'conversation.historyPresence',
                                         'conversation.chat.before')):
        raise ValueError('Incomplete retired history patch')
    return text




HISTORY_BOT_REPLACEMENTS = [
    (HISTORY_ANCHOR, HISTORY_INSERT + HISTORY_ANCHOR),
    (HISTORY_OLD, HISTORY_NEW), (HISTORY_HOOK, HISTORY_HOOK_NEW),
]
HISTORY_CHAT_REPLACEMENTS = [
    (HISTORY_HOST_ROWS, HISTORY_HOST_ROWS_NEW), (HISTORY_HOST_SLOT, HISTORY_HOST_SLOT_NEW),
]
HISTORY_CONVERSATION_REPLACEMENTS = [
    (HISTORY_ROOT_STATE, HISTORY_ROOT_STATE_NEW), (HISTORY_HERO, HISTORY_HERO_NEW),
    (HISTORY_CHILD, HISTORY_CHILD_NEW), (HISTORY_DECLARE, HISTORY_DECLARE_NEW),
] + HISTORY_VIEW_REPLACEMENTS


def plan_changes(bot=None, host=None, *, read_text=Path.read_text):
    bot = Path(bot) if bot is not None else COMPONENT_ROOT / 'data/.dsh/profiles/web/node_modules/ds-bot'
    host = host_directory(host)
    bot_version = verify_package(bot, 'ds-bot', ('0.2.6', '0.2.7', '0.3.1'))
    host_version = '0.2.2-alpha.2' if bot_version == '0.2.6' else '0.2.2-rc.1'
    for name in ('dsh-client-ui-chat', 'dsh-client-ui-conversation'):
        verify_package(host / name, '@deepseek-ai/' + name, (host_version,))
    if bot_version != '0.2.6':
        # Reviewed 0.3.1 tag/npm gitHead 6559c9e7c4ef71c292e6ac50f690031133536fe0:
        # history and safe prompt assembly are native; no Bot host patch is needed.
        # styles.js still fixes widths and cells.js still uses the More menu.
        # Compiled message/portal aliases changed; validate every anchor as before.
        latest = bot_version == '0.3.1'
        react_alias = 'import_react31' if latest else 'import_react19'
        dom_alias = 'import_react_dom3' if latest else 'import_react_dom'
        changes = [read_change(bot / 'client.js', lambda text: patch_presentation(
            patch_mobile(text, react_alias, phone_layout=not latest), react_alias, dom_alias),
            read_text=read_text)]
        for path, replacements in (
            (host / 'dsh-client-ui-chat/lib/client.js', HISTORY_CHAT_REPLACEMENTS),
            (host / 'dsh-client-ui-conversation/lib/client.js', HISTORY_CONVERSATION_REPLACEMENTS),
        ):
            original = read_text(path)
            fixed = retire_host_history(original, replacements)
            if path.parent.parent.name == 'dsh-client-ui-conversation':
                fixed = retire_composer(fixed)
            changes.append((path, original, fixed))
        return changes
    transforms = [
        (bot / 'client.js', lambda text: patch_presentation(patch_mobile(
            patch_history(text, HISTORY_BOT_REPLACEMENTS)))),
        (bot / 'src/host/tools.js', patch_prompt),
        (host / 'dsh-client-ui-chat/lib/client.js', lambda text: patch_history(text, HISTORY_CHAT_REPLACEMENTS)),
        (host / 'dsh-client-ui-conversation/lib/client.js', lambda text: patch_composer(
            patch_history(text, HISTORY_CONVERSATION_REPLACEMENTS))),
    ]
    return [read_change(path, transform, read_text=read_text) for path, transform in transforms]


def main():
    patch_cli(plan_changes, __doc__, {'bot': '--bot-dir', 'host': '--host-dir'},
              'Reviewed DS Bot / host compatibility verified')


if __name__ == '__main__':
    main()
