#!/usr/bin/env python3
"""Remove mobile's extra composer file button and apply the host tab-width fix.

The old plugin UI transforms only apply to the separate 3.2.1 / alpha.2 pair.
"""
import argparse
import json
from pathlib import Path
if not __package__:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from patches.common import COMPONENT_ROOT, host_directory, publish, read_change, replace_once
from patches.plugins.ds_bot.ds_bot_apply import retire_composer

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


COMPOSER_FILE_BUTTON = '''    ctx.slots.inject('conversation.input.left', () => ctx.slots.register({
        name: 'conversation.input.left',
        id: 'mobile-nav-file-upload',
        order: 10,
        locale: locales_ts_1.NS,
        inject: () => ({}),
    }, ComposerFileButton_tsx_1.ComposerFileButton));'''
COMPOSER_FILE_BUTTON_REMOVED = '    // Local preference: omit the extra mobile composer file button.'


def patch_composer_file_button(text):
    if COMPOSER_FILE_BUTTON not in text and 'mobile-nav-file-upload' not in text:
        return text
    return replace_once(text, COMPOSER_FILE_BUTTON, COMPOSER_FILE_BUTTON_REMOVED)


def plan_changes(package=None, host=None, *, read_text=Path.read_text):
    package = Path(package) if package is not None else COMPONENT_ROOT / 'data/.dsh/profiles/web/node_modules/dsh-web-mobile'
    host = host_directory(host)
    conversation = Path(host) / 'dsh-client-ui-conversation'
    mobile_manifest = json.loads((package / 'package.json').read_text())
    host_manifest = json.loads((conversation / 'package.json').read_text())
    if (mobile_manifest.get('name') == 'dsh-web-mobile'
            and mobile_manifest.get('version') in ('3.3.0', '3.3.1')
            and (host_manifest.get('name'), host_manifest.get('version')) == (
                '@deepseek-ai/dsh-client-ui-conversation', '0.2.2-rc.1')):
        plugin_path = package / 'lib/client.js'
        plugin = read_text(plugin_path)
        path = conversation / 'lib/client.js'
        original = read_text(path)
        # Reviewed upstream 522db94f552d89934f814853ad10c96f31eba6da (3.3.0):
        # 3.3.1 at 4e71eb67de7dac9d8b2572757c81e47aa32a32fb keeps these
        # layout and Enter sources unchanged (drawer/packaging fixes only).
        # layout.css.ts owns header clipping and tab hit-area/layout fixes;
        # composer-enter-newline.ts yields modifier shortcuts and popup selections.
        # Omit the extra file button; retire the conflicting host Enter hook
        # and retain measured tab fitting, which is still absent upstream.
        fixed = patch_view_tabs(retire_composer(original))
        return [(plugin_path, plugin, patch_composer_file_button(plugin)), (path, original, fixed)]
    # Legacy 3.2.1 only: it predates those upstream fixes.
    # Load old UI transforms only for the reviewed legacy version pair.
    if (mobile_manifest.get('name'), mobile_manifest.get('version'),
            host_manifest.get('name'), host_manifest.get('version')) != (
            'dsh-web-mobile', '3.2.1', '@deepseek-ai/dsh-client-ui-conversation', '0.2.2-alpha.2'):
        raise ValueError('Unsupported mobile / host pair; review upstream before applying')
    from patches.plugins.mobile.dsh_mobile_legacy import patch
    # Both manifests were validated above; prepare both before publishing either.
    return [
        read_change(package / 'lib/client.js', patch, read_text=read_text),
        read_change(conversation / 'lib/client.js', patch_view_tabs, read_text=read_text),
    ]


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
