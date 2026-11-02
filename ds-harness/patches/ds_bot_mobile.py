#!/usr/bin/env python3
"""Apply the ds-bot 0.2.4/0.2.5 / dsh-web-mobile layout compatibility fix.

Usage: python3 ds-harness/patches/ds_bot_mobile.py [path/to/ds-bot]
Only reviewed 0.2.4/0.2.5 client bundles are supported; unknown versions fail closed.
"""
from pathlib import Path
import json
import sys

GRID = '[class*="_frame"][data-sidebar-collapsed][data-rightbar-collapsed]:has(>[class*="_sidebarCol"]){grid-template-columns:0px minmax(0,1fr) 0px!important}'
GRID_FIXED = GRID + '''
/* dsh-web-mobile removes the host sidebar from grid flow on touch screens. */
@media (max-width:1023px) and (pointer:coarse){
html [data-mobile-nav="frame"][data-sidebar-collapsed][data-rightbar-collapsed]:has(>[class*="_sidebarCol"]){grid-template-columns:minmax(0,1fr) 0 0!important}
}'''
TRACK = '''var sidebarTrackWidth = () => typeof document === "undefined" ? null : document.querySelector('[class*="_sidebarCol"]')?.getBoundingClientRect().width ?? null;'''
TRACK_FIXED = '''var sidebarTrackWidth = () => {
  if (typeof document === "undefined") return null;
  const column = document.querySelector('[class*="_sidebarCol"]');
  if (!column) return null;
  // An overlay drawer occupies no layout track, even when its box has width.
  const position = getComputedStyle(column).position;
  return position === "absolute" || position === "fixed" ? 0 : column.getBoundingClientRect().width;
};'''


PHONE_CSS = '''
/* Phone reading layout: use the chat width, float tools instead of reserving 82px. */
@media (max-width:640px) and (pointer:coarse){
  body .bt-msg,body .bt-astack[data-lead]>.bt-msg{max-width:100%}
  body .bt-msg>.bt-msg-line{max-width:100%;min-width:0}
  body .bt-tools{top:-14px;right:0;left:auto;margin-left:0;transform:none;padding:2px;border-radius:999px;background:var(--bt-card);box-shadow:0 4px 14px rgba(0,0,0,.14)}
  body .bt-tools::after{display:none}
}
'''


GROUP_OLD = '''      { className: "bt-group-name", style: flat ? void 0 : { color: inkText(colorOf(bot)) } },
      flat ? lead : null,
      bot.name,
      room2?.admin === bot.id ? (0, import_react16.createElement)("span", { className: "bt-group-role" }, t("Admin")) : null,
      Number.isFinite(time) ? (0, import_react16.createElement)("span", { className: "bt-group-time", title: clockLabel(time) }, messageClock(time)) : null,
      took ? (0, import_react16.createElement)("span", { className: "bt-group-took", title: t("Ran for {duration}", { duration: took }) }, took) : null
    ),
    (0, import_react16.createElement)(Bubbles, { texts: texts2, roster, selfId: bot.id, actions, sessionId: room2?.id, msgKey, useUi, lead: flat ? null : lead, whole })'''
GROUP_NEW = GROUP_OLD.replace('className: "bt-group-name"', 'className: "bt-group-name bt-reply-meta"').replace('      flat ? lead : null,\n', '').replace('      took ?', '      lead,\n      took ?').replace('useUi, lead: flat ? null : lead, whole', 'useUi, whole')
GROUP_LEFT = GROUP_NEW.replace('      lead,\n', '').replace('      Number.isFinite(time) ?', '      lead,\n      Number.isFinite(time) ?')
META_CSS = '.bt-group-name>.bt-lead{margin:0 8px 0 0}'
META_FIXED = META_CSS + '''
/* Keep the clickable sender avatar beside the timestamp, outside the bubble. */
.bt-group-name.bt-reply-meta{display:flex;align-items:center;flex-wrap:wrap;column-gap:.4em;margin-inline-start:0}
.bt-group-name.bt-reply-meta>.bt-lead{margin:0}
'''


RAIL_CSS = '.bt-rail .bt-row{justify-content:center;width:56px;height:56px;min-height:56px;padding:0;border-radius:16px}'
RAIL_FIXED = RAIL_CSS + '''
/* Narrow navigation remains identifiable on both mouse and touch screens. */
.bt-rail .bt-row[title]{flex-direction:column;flex-shrink:0;width:90%;height:auto;min-height:0;padding:.45em .25em;gap:.25em}
.bt-rail .bt-row[title]::after{content:attr(title);display:block;flex:none;width:100%;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:center;font-size:.75rem;line-height:1.3;font-weight:500;color:var(--bt-ink)}
.bt-rail .bt-rail-top{align-self:stretch}
'''


def patch(text, version='0.2.4'):
    react_name = {'0.2.4': 'import_react16', '0.2.5': 'import_react17'}.get(version)
    if react_name is None:
        raise ValueError('This patch supports ds-bot 0.2.4/0.2.5 only; review other versions separately')
    group_old, group_new, group_left = (
        value.replace('import_react16', react_name)
        for value in (GROUP_OLD, GROUP_NEW, GROUP_LEFT)
    )
    if group_new in text:
        text = text.replace(group_new, group_left, 1)
    for old, new in ((GRID, GRID_FIXED), (TRACK, TRACK_FIXED),
                     (GRID_FIXED, GRID_FIXED + PHONE_CSS), (group_old, group_left),
                     (META_CSS, META_FIXED), (RAIL_CSS, RAIL_FIXED)):
        if new in text:
            continue
        if text.count(old) != 1:
            raise ValueError('Unrecognized ds-bot bundle; inspect upstream before applying')
        text = text.replace(old, new, 1)
    return text


def main():
    package = (Path(sys.argv[1]) if len(sys.argv) > 1 else
               Path(__file__).resolve().parents[1] / 'data/.dsh/profiles/web/node_modules/ds-bot')
    manifest = json.loads((package / 'package.json').read_text())
    version = manifest.get('version')
    if manifest.get('name') != 'ds-bot' or version not in ('0.2.4', '0.2.5'):
        raise SystemExit('This patch supports ds-bot 0.2.4/0.2.5 only; review other versions separately')
    target = package / 'client.js'
    original = target.read_text()
    fixed = patch(original, version)
    if fixed != original:
        target.write_text(fixed)
        print(f'Applied ds-bot {version} mobile layout fix; refresh the Web page')
    else:
        print('ds-bot mobile layout fix already applied')


if __name__ == '__main__':
    main()
