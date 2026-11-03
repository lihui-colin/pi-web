#!/usr/bin/env python3
"""Apply all reviewed DS Bot 0.2.6 / DSH 0.2.2-alpha.2 fixes atomically.

Self-contained installer entry: history, prompt compatibility, layout and mobile Enter.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile


def replace_once(text, old, new):
    if new in text:
        if text.count(new) != 1 or old in text.replace(new, '', 1):
            raise ValueError('Duplicate or mixed patch anchors; inspect upstream before applying')
        return text
    if text.count(old) != 1:
        raise ValueError('Unrecognized bundle; inspect upstream before applying')
    return text.replace(old, new, 1)

def publish(changes, backup_root=None):
    """Stage every file, keep originals, and roll back completed replacements on failure."""
    pending = [(path.resolve(), original, fixed) for path, original, fixed in changes if original != fixed]
    if not pending:
        return
    if any(path.read_text() != original for path, original, _ in changes):
        raise ValueError('Target changed during validation; rerun without overwriting it')
    backup_root = backup_root or Path(__file__).resolve().parents[1] / 'log/patch-backups'
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix='ds-bot-', dir=backup_root))
    staged = []
    replaced = []
    try:
        for index, (path, original, fixed) in enumerate(pending):
            saved = backup / str(index)
            shutil.copy2(path, saved)
            # Staging next to the target guarantees same-filesystem atomic replacement.
            stage_dir = Path(tempfile.mkdtemp(prefix='.ds-bot-patch-', dir=path.parent))
            staged.append((path, saved, stage_dir))
            stage = stage_dir / 'client'
            stage.write_text(fixed)
            shutil.copymode(path, stage)
            with stage.open('rb') as handle:
                os.fsync(handle.fileno())
        (backup / 'manifest.json').write_text(json.dumps([str(path) for path, _, _ in pending], indent=2))
        if any(path.read_text() != original for path, original, _ in changes):
            raise ValueError('Target changed while staging; no replacements made')
        for path, saved, stage_dir in staged:
            os.replace(stage_dir / 'client', path)
            replaced.append((path, saved, stage_dir))
    except Exception as error:
        failures = []
        for path, saved, stage_dir in reversed(replaced):
            try:
                shutil.copy2(saved, stage_dir / 'restore')
                os.replace(stage_dir / 'restore', path)
            except OSError:
                failures.append(str(path))
        detail = f'; rollback failed for {failures}' if failures else '; completed replacements rolled back'
        raise RuntimeError(f'Patch publication failed{detail}. Originals: {backup}') from error
    finally:
        for path, _, stage_dir in staged:
            # Only remove directories created above, alongside their verified target.
            if stage_dir.parent == path.parent and stage_dir.name.startswith('.ds-bot-patch-'):
                shutil.rmtree(stage_dir)
    print(f'Original files saved in {backup}')


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

def patch_mobile(text):
    for old, new in (
        (MOBILE_GRID, MOBILE_GRID_FIXED), (MOBILE_TRACK, MOBILE_TRACK_FIXED),
        (MOBILE_GRID_FIXED, MOBILE_GRID_FIXED + MOBILE_PHONE_CSS),
        (MOBILE_GROUP_OLD, MOBILE_GROUP_LEFT), (MOBILE_META_CSS, MOBILE_META_FIXED),
        (MOBILE_RAIL_CSS, MOBILE_RAIL_FIXED), (MOBILE_COMPOSER, MOBILE_COMPOSER + MOBILE_COMPOSER_CSS),
    ):
        text = replace_once(text, old, new)
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


def plan_changes(bot=None, host=None):
    bot = Path(bot) if bot is not None else Path(__file__).resolve().parents[1] / 'data/.dsh/profiles/web/node_modules/ds-bot'
    if host is None:
        executable = shutil.which('dsh')
        if executable is None:
            raise ValueError('dsh executable not found')
        host = Path(executable).resolve().parents[1] / 'node_modules/@deepseek-ai'
    host = Path(host)
    packages = [
        (bot, 'ds-bot', '0.2.6'),
        (host / 'dsh-client-ui-chat', '@deepseek-ai/dsh-client-ui-chat', '0.2.2-alpha.2'),
        (host / 'dsh-client-ui-conversation', '@deepseek-ai/dsh-client-ui-conversation', '0.2.2-alpha.2'),
    ]
    for directory, name, version in packages:
        manifest = json.loads((directory / 'package.json').read_text())
        if (manifest.get('name'), manifest.get('version')) != (name, version):
            raise ValueError(f'Unsupported package {manifest.get("name")}@{manifest.get("version")}; expected {name}@{version}. Review upstream before applying.')
    transforms = [
        (bot / 'client.js', lambda text: patch_mobile(patch_history(text, HISTORY_BOT_REPLACEMENTS))),
        (bot / 'src/host/tools.js', patch_prompt),
        (host / 'dsh-client-ui-chat/lib/client.js', lambda text: patch_history(text, HISTORY_CHAT_REPLACEMENTS)),
        (host / 'dsh-client-ui-conversation/lib/client.js', lambda text: patch_composer(patch_history(text, HISTORY_CONVERSATION_REPLACEMENTS))),
    ]
    changes = []
    for path, transform in transforms:
        original = path.read_text()
        changes.append((path, original, transform(original)))
    return changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Validate without writing; exit 1 if any fix is missing')
    parser.add_argument('--bot-dir', type=Path, help='Installed ds-bot package directory')
    parser.add_argument('--host-dir', type=Path, help='Installed DSH node_modules/@deepseek-ai directory')
    args = parser.parse_args()
    changes = plan_changes(args.bot_dir, args.host_dir)
    pending = [(path, original, fixed) for path, original, fixed in changes if original != fixed]
    if args.check:
        for path, _, _ in pending:
            print(f'Needs patch: {path}')
        if pending:
            raise SystemExit(1)
        print('All reviewed DS Bot and shared composer fixes are present.')
        return
    publish(changes)
    print('All reviewed DS Bot and shared composer fixes applied.')
    if pending:
        print('Reload frontend resources / server modules during a maintenance window; no service restarted.')


if __name__ == '__main__':
    main()
