#!/usr/bin/env python3
"""Keep mobile 3.3.0 upstream UI and apply the scoped host tab-width fix.

The old plugin UI transforms only apply to the separate 3.2.1 / alpha.2 pair.
"""
import argparse
import json
import shutil
from pathlib import Path
if __package__:
    from .ds_bot_apply import publish, replace_once, retire_composer
else:
    from ds_bot_apply import publish, replace_once, retire_composer

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


# Preserve native pin/menu behavior; fit tabs using their rendered widths.
VIEW_LIMIT_LEGACY = '''				const updateLimit = () => {
					// Phone browsers show only Chat. Trajectory, Git, Statistics and other views stay in More.
					const phone = (0, _deepseek_ai_dsh_client_ui_primitives.isMobileDevice)() && window.matchMedia("(max-width: 1023px)").matches;
					setVisibleViewLimit(phone ? 1 : Math.max(1, Math.floor((row.clientWidth - 48) / 120)));
				};'''
VIEW_LIMIT_UPSTREAM = '''				const updateLimit = () => {
					setVisibleViewLimit(Math.max(1, Math.floor((row.clientWidth - 48) / 120)));
				};'''
VIEW_LIMIT_OLD = '''			(0, react.useLayoutEffect)(() => {
				const row = tabRow.current;
				if (row === null || !hasEntryActions) return;
				const updateLimit = () => {
					setVisibleViewLimit(Math.max(1, Math.floor((row.clientWidth - 48) / 120)));
				};
				updateLimit();
				if (typeof ResizeObserver === "undefined") return;
				const observer = new ResizeObserver(updateLimit);
				observer.observe(row);
				return () => {
					observer.disconnect();
				};
			}, [showTabs, hasEntryActions]);
'''
VIEW_MOBILE_QUERY = '''				const mobileQuery = window.matchMedia("(max-width: 1023px) and (pointer: coarse)");
'''
VIEW_MOBILE_GUARD = '''					if (!mobileQuery.matches || !row.closest('[data-mobile-nav="frame"]')) {
						setVisibleViewLimit(Math.max(1, Math.floor((row.clientWidth - 48) / 120)));
						return;
					}
'''
VIEW_CLEANUP_OLD = '''				return () => { disposed = true; observer?.disconnect(); };'''
VIEW_CLEANUP_NEW = '''				const frame = document.querySelector('[data-shell-overlay]')?.parentElement;
				const markerObserver = new MutationObserver(updateLimit);
				if (frame) markerObserver.observe(frame, { attributes: true, attributeFilter: ['data-mobile-nav'] });
				mobileQuery.addEventListener('change', updateLimit);
				return () => {
					disposed = true;
					observer?.disconnect();
					markerObserver.disconnect();
					mobileQuery.removeEventListener('change', updateLimit);
				};'''
VIEW_LIMIT_UNSCOPED = '''			(0, react.useLayoutEffect)(() => {
				const row = tabRow.current;
				if (row === null || !hasEntryActions) return;
				const updateLimit = () => {
					const lane = row.querySelector('[data-conversation-tabs]');
					const template = lane?.querySelector('[role="tab"]');
					if (!lane || !template) return;
					const preferred = [...tabs.filter((tab) => tab.id === FIXED_VIEW_ID), ...tabs.filter((tab) => tab.id !== "chat" && !unpinned.includes(tab.id))];
					const px = (value) => parseFloat(value) || 0;
					const rowStyle = getComputedStyle(row);
					const laneStyle = getComputedStyle(lane);
					const more = row.querySelector('[class*="_viewsMoreAnchor"]');
					const moreStyle = more && getComputedStyle(more);
					const available = row.clientWidth - px(rowStyle.paddingLeft) - px(rowStyle.paddingRight)
						- (more ? more.getBoundingClientRect().width + px(moreStyle.marginLeft) + px(moreStyle.marginRight) + px(rowStyle.columnGap) : 0);
					// Measure hidden candidates in the same CSS context, including localized labels.
					const probe = lane.cloneNode(false);
					probe.setAttribute('aria-hidden', 'true');
					probe.inert = true;
					for (const [name, value] of Object.entries({position: 'absolute', visibility: 'hidden', width: 'max-content', 'max-width': 'none', 'pointer-events': 'none'})) probe.style.setProperty(name, value, 'important');
					for (const tab of preferred) {
						const button = template.cloneNode(true);
						const label = button.querySelector('[class*="_tabLabel"]');
						(label || button).textContent = tab.label;
						probe.appendChild(button);
					}
					row.appendChild(probe);
					let count = 0;
					let used = px(laneStyle.paddingLeft) + px(laneStyle.paddingRight);
					try {
						for (const button of probe.children) {
							const style = getComputedStyle(button);
							used += button.getBoundingClientRect().width + px(style.marginLeft) + px(style.marginRight) + (count ? px(laneStyle.columnGap) : 0);
							if (used > available + 0.5) break;
							count++;
						}
					} finally { probe.remove(); }
					setVisibleViewLimit(Math.max(1, count));
				};
				updateLimit();
				let disposed = false;
				document.fonts?.ready.then(() => { if (!disposed) updateLimit(); });
				const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(updateLimit);
				observer?.observe(row);
				return () => { disposed = true; observer?.disconnect(); };
			}, [showTabs, hasEntryActions, tabs, unpinned]);
'''
VIEW_LIMIT_NEW = (VIEW_LIMIT_UNSCOPED
    .replace("\t\t\t\tconst updateLimit = () => {\n", VIEW_MOBILE_QUERY + "\t\t\t\tconst updateLimit = () => {\n" + VIEW_MOBILE_GUARD)
    .replace(VIEW_CLEANUP_OLD, VIEW_CLEANUP_NEW))

def patch_view_tabs(text):
    if VIEW_LIMIT_UNSCOPED in text:
        text = replace_once(text, VIEW_LIMIT_UNSCOPED, VIEW_LIMIT_NEW)
    if VIEW_LIMIT_LEGACY in text:
        text = replace_once(text, VIEW_LIMIT_LEGACY, VIEW_LIMIT_UPSTREAM)
    return replace_once(text, VIEW_LIMIT_OLD, VIEW_LIMIT_NEW)


def plan_changes(package=None, host=None):
    package = Path(package) if package is not None else Path(__file__).resolve().parents[2] / 'data/.dsh/profiles/web/node_modules/dsh-web-mobile'
    if host is None:
        executable = shutil.which('dsh')
        if executable is None:
            raise ValueError('dsh executable not found')
        host = Path(executable).resolve().parents[1] / 'node_modules/@deepseek-ai'
    conversation = Path(host) / 'dsh-client-ui-conversation'
    mobile_manifest = json.loads((package / 'package.json').read_text())
    host_manifest = json.loads((conversation / 'package.json').read_text())
    if (mobile_manifest.get('name'), mobile_manifest.get('version'),
            host_manifest.get('name'), host_manifest.get('version')) == (
            'dsh-web-mobile', '3.3.0', '@deepseek-ai/dsh-client-ui-conversation', '0.2.2-rc.1'):
        plugin_path = package / 'lib/client.js'
        plugin = plugin_path.read_text()
        path = conversation / 'lib/client.js'
        original = path.read_text()
        # The mobile package stays byte-identical to upstream. Its own Enter
        # hook yields modifier shortcuts and popup selections to the host.
        fixed = patch_view_tabs(retire_composer(original))
        return [(plugin_path, plugin, plugin), (path, original, fixed)]
    # Validate and prepare both bundles before publishing either one.
    changes = []
    for directory, name, version, transform in (
        (package, 'dsh-web-mobile', '3.2.1', patch),
        (conversation, '@deepseek-ai/dsh-client-ui-conversation', '0.2.2-alpha.2', patch_view_tabs),
    ):
        manifest = json.loads((directory / 'package.json').read_text())
        if (manifest.get('name'), manifest.get('version')) != (name, version):
            raise ValueError(f'Expected {name}@{version}; review upstream before applying')
        path = directory / 'lib/client.js'
        original = path.read_text()
        changes.append((path, original, transform(original)))
    return changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--mobile-dir', type=Path, help='Installed dsh-web-mobile package')
    parser.add_argument('--host-dir', type=Path, help='Installed DSH node_modules/@deepseek-ai directory')
    args = parser.parse_args()
    changes = plan_changes(args.mobile_dir, args.host_dir)
    if args.check:
        pending = [str(path) for path, original, fixed in changes if original != fixed]
        if pending:
            raise SystemExit('Mobile fixes missing: ' + ', '.join(pending))
    else:
        publish(changes)
    print('Reviewed mobile UI / host adaptive tabs state verified; no service restarted.')


if __name__ == '__main__':
    main()
