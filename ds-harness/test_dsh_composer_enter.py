import json
import subprocess
import unittest
from patches import dsh_composer_enter as p

# Original Enter callback from DSH conversation 0.2.2-alpha.2.
UPSTREAM = '''(event) => {
				if (event !== null && (event.altKey || event.getModifierState("AltGraph") || event.ctrlKey && event.metaKey || event.shiftKey && (event.ctrlKey || event.metaKey))) return true;
				if (event?.shiftKey === true) return false;
				if (event !== null && isComposingEvent(event, recentlyComposing)) return true;
				if (handlers.arbitrate("enter", false) !== "pass") {
					event?.preventDefault();
					return true;
				}
				event?.preventDefault();
				if (event?.repeat === true) return true;
				if (!handlers.canSubmit()) return true;
				handlers.submit(event?.ctrlKey === true || event?.metaKey === true);
				return true;
			}'''


class ComposerEnterTests(unittest.TestCase):
    def test_idempotent_and_unknown_bundle_rejected(self):
        fixed = p.patch(UPSTREAM)
        self.assertEqual(p.patch(fixed), fixed)
        with self.assertRaises(ValueError):
            p.patch('unknown editor')

    def test_mobile_newlines_desktop_submission_and_ime(self):
        script = r"""
const assert = require('node:assert/strict');
let mobile, composing, submitted, prevented, popup, arbitrated, newlines;
const Ue$2 = Symbol('INSERT_LINE_BREAK_COMMAND');
const editor = {dispatchCommand: (command, selectStart) => {
  assert.equal(command, Ue$2); assert.equal(selectStart, false); newlines++; return true;
}};
const _deepseek_ai_dsh_client_ui_primitives = {isMobileDevice: () => mobile};
const recentlyComposing = () => composing;
const isComposingEvent = (event, recent) => event.isComposing || recent();
const handlers = {
  arbitrate: () => {arbitrated++; return popup ? 'consumed' : 'pass'},
  canSubmit: () => true, submit: () => submitted++,
};
const enter = eval('(' + CALLBACK + ')');
function check(touch, flags, expected, options = {}) {
  mobile = touch; composing = options.composing ?? false;
  popup = options.popup ?? false; submitted = prevented = arbitrated = newlines = 0;
  const event = flags === null ? null : {
    getModifierState: () => false, preventDefault: () => prevented++, ...flags,
  };
  const consumed = enter(event);
  assert.equal(submitted, expected, JSON.stringify({touch, flags, options}));
  if (touch && !composing && !flags?.isComposing) {
    assert.equal(consumed, !flags?.shiftKey);
    assert.equal(newlines, flags?.shiftKey ? 0 : 1);
    assert.equal(prevented, flags === null || flags?.shiftKey ? 0 : 1);
    assert.equal(arbitrated, 0);
  }
}
check(true, {}, 0);
check(true, null, 0);
check(true, {shiftKey:true}, 0);
check(true, {ctrlKey:true}, 0);
check(true, {}, 0, {popup:true});
check(true, {isComposing:true}, 0);
check(true, {}, 0, {composing:true});
check(false, {}, 1);
check(false, {shiftKey:true}, 0);
check(false, {ctrlKey:true}, 1);
check(false, {metaKey:true}, 1);
check(false, {repeat:true}, 0);
check(false, {isComposing:true}, 0);
check(false, {}, 0, {composing:true});
check(false, {}, 0, {popup:true});
""".replace('CALLBACK', json.dumps(p.patch(UPSTREAM)))
        subprocess.run(['node', '-e', script], check=True, capture_output=True, text=True)

if __name__ == '__main__':
    unittest.main()
