#!/usr/bin/env python3
"""Apply reviewed mobile header and sidebar adjustments."""
import argparse
import json
from pathlib import Path
from ds_bot_apply import publish, replace_once

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


ROW_ANCHOR = '''  [data-mobile-nav="frame"] [data-phase] header:has([class*="_headerLeading"]) [role="tablist"] {
    width: 100% !important;
    margin-top: 4px !important;
  }'''
ROW_FIXED = ROW_ANCHOR + '''
  /* Keep views and their More menu in one row; only the tab lane may shrink. */
  html body [data-mobile-nav="frame"] [data-phase] header:has([class*="_headerLeading"]) [class*="_tabs"]:has(> [data-conversation-tabs]) {
    flex-wrap: nowrap !important;
    align-items: center !important;
    column-gap: 16px !important;
  }
  html body [data-mobile-nav="frame"] [data-phase] header:has([class*="_headerLeading"]) [data-conversation-tabs][role="tablist"] {
    flex: 0 1 auto !important;
    width: auto !important;
    min-width: 0 !important;
    height: auto !important;
    margin-top: 0 !important;
    padding-right: 0 !important;
    align-items: center !important;
  }
  html body [data-mobile-nav="frame"] [data-phase] header:has([class*="_headerLeading"]) [data-conversation-tabs] > [role="tab"],
  html body [data-mobile-nav="frame"] [data-phase] header:has([class*="_headerLeading"]) button[class*="_viewsMore"] {
    margin-top: 0 !important;
  }
'''

DRAWER_LOG_OLD = "        addReconcilerTask((0, drawer_session_log_ts_1.createDrawerSessionLogTask)(ctx)),"
DRAWER_LOG_NEW = "        // Local preference: do not inject session-log download into the sidebar."

def patch(text):
    text = replace_once(text, OLD, NEW)
    text = replace_once(text, DRAWER_LOG_OLD, DRAWER_LOG_NEW)
    text = replace_once(text, TAB_ANCHOR, TAB_FIXED)
    text = replace_once(text, ROW_ANCHOR, ROW_FIXED)
    # The layout template owns this first media block; other modules reuse the query.
    start = text.index('exports.LAYOUT_CSS = `')
    end = text.index('`;', start)
    return text[:start] + replace_once(text[start:end], ANCHOR, FIXED) + text[end:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    package = Path(__file__).resolve().parents[1] / 'data/.dsh/profiles/web/node_modules/dsh-web-mobile'
    manifest = json.loads((package / 'package.json').read_text())
    if (manifest.get('name'), manifest.get('version')) != ('dsh-web-mobile', '3.2.1'):
        raise ValueError('Expected dsh-web-mobile@3.2.1; review upstream before applying')
    path = package / 'lib/client.js'
    original = path.read_text()
    fixed = patch(original)
    if args.check:
        if fixed != original:
            raise SystemExit('Mobile header controls need patching')
    else:
        publish([(path, original, fixed)])
    print('Mobile header controls patch verified; no service restarted.')


if __name__ == '__main__':
    main()
