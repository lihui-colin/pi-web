"""Legacy mobile 3.2.1 UI transforms; never apply to mobile 3.3.0 or later.

Current mobile owns header clipping, tab spacing and Enter behavior upstream.
This module is retained only for the reviewed 3.2.1 / DSH alpha.2 pair.
"""
if __package__:
    from .ds_bot_apply import replace_once
else:
    from ds_bot_apply import replace_once

OLD = """ctx.slots.inject('conversation.session.header.actions', () => ctx.slots.register({
        name: 'conversation.session.header.actions',
        id: 'mobile-nav-toggle',"""
NEW = OLD.replace('conversation.session.header.actions', 'conversation.header.leading')
ANCHOR = '@media (max-width: 1023px) and (pointer: coarse) {'
FIXED = ANCHOR + '''
  /* Local fix: navigation belongs outside the horizontally clipped title/actions lane.
     Only reveal the leading slot when our mobile controls are mounted there. */
  html [data-mobile-nav="frame"] [data-phase] header [data-conversation-header-leading] > [data-slot="conversation.header.leading"]:has(> [data-mobile-nav="toggle"]) {
    display: contents !important;
  }
'''


TAB_ANCHOR = '  [data-mobile-nav="frame"] [data-phase] header [role="tablist"] > button {\n    flex-shrink: 0;'
TAB_FIXED = TAB_ANCHOR.replace('    flex-shrink: 0;', '    /* Mobile padding is zero: disable the host hit-area compensation too. */\n    --dsh-tab-hit-inline: 0px;\n    flex-shrink: 0;')


HEADER = 'html body [data-mobile-nav="frame"] [data-phase] header:has([class*="_headerLeading"]) '


def header_css(comment, rules):
    """Share selector scope without changing specificity or emitted CSS."""
    result = '\n  /* ' + comment + ' */\n'
    for selectors, declarations in rules:
        result += ',\n'.join('  ' + HEADER + selector for selector in selectors) + ' {\n'
        result += ''.join('    ' + value.strip() + ';\n' for value in declarations.split(';') if value.strip())
        result += '  }\n'
    return result


ROW_ANCHOR = '''  [data-mobile-nav="frame"] [data-phase] header:has([class*="_headerLeading"]) [role="tablist"] {
    width: 100% !important;
    margin-top: 4px !important;
  }'''
ROW_FIXED = ROW_ANCHOR + header_css('Keep views and their More menu in one row; only the tab lane may shrink.', [
    (('[class*="_tabs"]:has(> [data-conversation-tabs])',),
     'flex-wrap: nowrap !important; align-items: center !important; column-gap: 16px !important;'),
    (('[data-conversation-tabs][role="tablist"]',),
     'flex: 0 1 auto !important; width: auto !important; min-width: 0 !important; height: auto !important; '
     'margin-top: 0 !important; padding-right: 0 !important; align-items: center !important;'),
    (('[data-conversation-tabs] > [role="tab"]', 'button[class*="_viewsMore"]'),
     'margin-top: 0 !important;'),
])

DRAWER_LOG_OLD = "        addReconcilerTask((0, drawer_session_log_ts_1.createDrawerSessionLogTask)(ctx)),"
DRAWER_LOG_NEW = "        // Local preference: do not inject session-log download into the sidebar."

RIGHT_ICON_OLD = 'icon_compat_ts_1.IconFolderOpen, { size: 16 }'
RIGHT_ICON_NEW = 'icon_compat_ts_1.IconPanelLeft, { size: 16, className: "dsh-mobile-right-sidebar-icon" }'
RIGHT_ICON_CSS = '\n  html [data-mobile-nav="files"] svg { transform: scaleX(-1) !important; }\n'


HEADER_ACTIONS_CSS = header_css('One scroll lane for header controls; keep the title and side-panel buttons in place.', [
    (('[class*="_titleCluster"]',),
     'overflow: visible !important; min-width: 0 !important;'),
    (('[class*="_titleCluster"] > [class*="_crumbs"]',),
     'flex: 0 1 35% !important; min-width: 72px !important; max-width: 35% !important; '
     'overflow: hidden !important;'),
    (('[class*="_headerActions"]',),
     'flex: 1 1 0 !important; min-width: 0 !important; max-width: 100% !important; margin-left: 0 !important; '
     'justify-content: flex-start !important; overflow-x: auto !important; overflow-y: hidden !important; '
     'touch-action: pan-x pinch-zoom !important; overscroll-behavior-x: contain; scrollbar-width: thin;'),
    (('[class*="_headerActions"] > [data-slot="conversation.session.header.actions"] > *',),
     'flex: 0 0 auto !important; max-width: none !important; overflow: visible !important; '
     'touch-action: pan-x pinch-zoom !important; left: auto !important;'),
    (('[class*="_headerActions"] [data-team-action] > button',
      '[class*="_headerActions"] button[class*="_trigger"] > span[class]',
      '[class*="_headerActions"] > [data-slot] > span[class*="_label"]'),
     'display: inline-flex !important; flex-shrink: 0 !important; width: auto !important; '
     'max-width: none !important; overflow: visible !important; white-space: nowrap !important; '
     'text-overflow: clip !important;'),
])

def patch(text):
    text = replace_once(text, OLD, NEW)
    text = replace_once(text, RIGHT_ICON_OLD, RIGHT_ICON_NEW)
    # Host-toggle hiding must not match our newly labeled right-sidebar control.
    for label in ('button[aria-label*="sidebar" i]', 'button[aria-label*="侧边栏"]'):
        selector = 'html [data-mobile-nav="frame"] [data-conversation-header-leading] ' + label
        text = replace_once(text, selector, selector + ':not([data-mobile-nav])')
    text = replace_once(text, "'files': '文件浏览'", "'files': '打开右侧栏'")
    text = replace_once(text, "'files': 'Files'", "'files': 'Open right sidebar'")
    text = replace_once(text, DRAWER_LOG_NEW, DRAWER_LOG_OLD)
    text = replace_once(text, TAB_ANCHOR, TAB_FIXED)
    text = replace_once(text, ROW_ANCHOR, ROW_FIXED)
    # The layout template owns this first media block; other modules reuse the query.
    start = text.index('exports.LAYOUT_CSS = `')
    end = text.index('`;', start)
    layout = replace_once(text[start:end], ANCHOR, FIXED)
    layout = replace_once(layout, FIXED, FIXED + HEADER_ACTIONS_CSS)
    layout = replace_once(layout, 'exports.LAYOUT_CSS = `', 'exports.LAYOUT_CSS = `' + RIGHT_ICON_CSS)
    return text[:start] + layout + text[end:]
