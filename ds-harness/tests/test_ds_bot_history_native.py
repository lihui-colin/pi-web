import test_support  # Configure the service source import path.
import unittest
from patches.plugins.ds_bot import ds_bot_apply as p

class NativeHistoryTests(unittest.TestCase):
    def test_native_integration_is_idempotent(self):
        groups = [
            [(p.HISTORY_ANCHOR, p.HISTORY_INSERT+p.HISTORY_ANCHOR), (p.HISTORY_OLD,p.HISTORY_NEW), (p.HISTORY_HOOK,p.HISTORY_HOOK_NEW)],
            [(p.HISTORY_HOST_ROWS,p.HISTORY_HOST_ROWS_NEW),(p.HISTORY_HOST_SLOT,p.HISTORY_HOST_SLOT_NEW)],
            [(p.HISTORY_ROOT_STATE,p.HISTORY_ROOT_STATE_NEW),(p.HISTORY_HERO,p.HISTORY_HERO_NEW),(p.HISTORY_CHILD,p.HISTORY_CHILD_NEW),(p.HISTORY_DECLARE,p.HISTORY_DECLARE_NEW)] + p.HISTORY_VIEW_REPLACEMENTS,
        ]
        for pairs in groups:
            source='\n'.join(a for a,b in pairs)
            fixed=p.patch_history(source,pairs)
            self.assertEqual(p.patch_history(fixed,pairs),fixed)
    def test_unknown_source_is_rejected(self):
        with self.assertRaises(ValueError):
            p.patch_history('unknown',[(p.HISTORY_HERO,p.HISTORY_HERO_NEW)])
    def test_duplicate_source_is_rejected(self):
        with self.assertRaises(ValueError):
            p.patch_history(p.HISTORY_HERO+p.HISTORY_HERO,[(p.HISTORY_HERO,p.HISTORY_HERO_NEW)])

if __name__=='__main__':
    unittest.main()
