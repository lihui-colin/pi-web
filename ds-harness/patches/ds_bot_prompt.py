#!/usr/bin/env python3
"""Adapt ds-bot 0.2.5 to DSH's prompt-only assembly waterfall."""
import json
from pathlib import Path
import sys


OLD = '        tools: assembled.tools.filter(tool => !HIDDEN_TOOLS.includes(tool.name)),'
NEW = '''        // New DSH attaches provider-owned tools after the prompt waterfall.
        // Older hosts still expose tools here; preserve their filtering.
        ...(Array.isArray(assembled.tools) ? {
          tools: assembled.tools.filter(tool => !HIDDEN_TOOLS.includes(tool.name)),
        } : {}),'''


def patch(text):
    if NEW in text:
        return text
    if text.count(OLD) != 1:
        raise ValueError('Unrecognized ds-bot tools.js; review upstream before applying')
    return text.replace(OLD, NEW, 1)


def main():
    package = (Path(sys.argv[1]) if len(sys.argv) > 1 else
               Path(__file__).resolve().parents[1] / 'data/.dsh/profiles/web/node_modules/ds-bot')
    manifest = json.loads((package / 'package.json').read_text())
    if manifest.get('name') != 'ds-bot' or manifest.get('version') != '0.2.5':
        raise SystemExit('This patch supports ds-bot 0.2.5 only; review other versions separately')
    target = package / 'src/host/tools.js'
    original = target.read_text()
    fixed = patch(original)
    if fixed != original:
        target.write_text(fixed)
        print('Applied ds-bot prompt assembly compatibility fix')
    else:
        print('ds-bot prompt assembly fix already applied')


if __name__ == '__main__':
    main()
