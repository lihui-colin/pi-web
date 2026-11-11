#!/usr/bin/env python3
"""Replace reviewed rc.1 navigator :has CSS with explicit parent state."""
from pathlib import Path

if not __package__:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from patches.common import apply_replacements, plan_host_patch, patch_cli, publish


LAYOUT_ATTRIBUTE = 'data-dsh-files-navigator-layout'
FILL_OLD = '}:has(>.k-1LKG_navigator.k-1LKG_fill)>:not(.k-1LKG_navigator){visibility:hidden}'
MOBILE_OLD = '@media (width<768px){:has(>.k-1LKG_navigator:not(.k-1LKG_wholePage))>:not(.k-1LKG_navigator){visibility:hidden}'
# Two attribute conditions preserve the old :has(nav.fill) specificity; the
# existing sibling :not() contributes the third class/attribute component.
CSS_REPLACEMENTS = (
    (FILL_OLD, '}[' + LAYOUT_ATTRIBUTE + '][' + LAYOUT_ATTRIBUTE + '~=fill]>:not(.k-1LKG_navigator){visibility:hidden}'),
    (MOBILE_OLD, '@media (width<768px){[' + LAYOUT_ATTRIBUTE + '][' + LAYOUT_ATTRIBUTE + '~=panel]>:not(.k-1LKG_navigator){visibility:hidden}'),
)
HELPER_ANCHOR = '\t\tconst RESIZE_STEP = 20;'
HELPER = '''		// Explicit navigator parent state avoids global relational CSS invalidation.
		const dshFilesNavigatorParents = new WeakMap();
		function dshTrackFilesNavigator(element, mode) {
			const parent = element?.parentElement;
			if (!parent || mode === void 0) return;
			let entries = dshFilesNavigatorParents.get(parent);
			if (!entries) {
				entries = new Map();
				dshFilesNavigatorParents.set(parent, entries);
			}
			const token = { fill: mode === "fill" };
			entries.set(element, token);
			const update = () => {
				if (entries.size === 0) {
					parent.removeAttribute("data-dsh-files-navigator-layout");
					dshFilesNavigatorParents.delete(parent);
				} else {
					const value = [...entries.values()].some((entry) => entry.fill) ? "panel fill" : "panel";
					if (parent.getAttribute("data-dsh-files-navigator-layout") !== value) parent.setAttribute("data-dsh-files-navigator-layout", value);
				}
			};
			update();
			return () => {
				// Ignore an obsolete ref cleanup after this element was registered again.
				if (entries.get(element) !== token) return;
				entries.delete(element);
				update();
			};
		}
'''
REF_OLD = '''			const navigatorRef = (0, react.useCallback)((element) => {
				navigatorDrawn(paneId, element, !page);
			}, [
				navigatorDrawn,
				paneId,
				page
			]);'''
REF_NEW = '''			const navigatorLayoutCleanup = (0, react.useRef)(void 0);
			const navigatorRef = (0, react.useCallback)((element) => {
				navigatorLayoutCleanup.current?.();
				navigatorLayoutCleanup.current = dshTrackFilesNavigator(element, page ? void 0 : mode);
				navigatorDrawn(paneId, element, !page);
			}, [
				navigatorDrawn,
				paneId,
				page,
				mode
			]);'''
REPLACEMENTS = (*CSS_REPLACEMENTS, (HELPER_ANCHOR, HELPER + HELPER_ANCHOR), (REF_OLD, REF_NEW))


def patch(text):
    if 'dshFilesNavigatorParents' in text and HELPER not in text:
        raise ValueError('Unknown navigator layout helper; inspect upstream before applying')
    installed = [new in text for _, new in REPLACEMENTS]
    if any(installed) and not all(installed):
        raise ValueError('Mixed sidebar layout patch anchors; inspect upstream before applying')
    return apply_replacements(text, REPLACEMENTS)


def plan_changes(host=None, *, read_text=Path.read_text):
    return plan_host_patch(host, 'dsh-client-ui-sidebar-files', patch, read_text=read_text)


def main():
    patch_cli(plan_changes, __doc__, {'host': '--host-dir'},
              'Sidebar navigator parent layout verified')


if __name__ == '__main__':
    main()
