import unittest
from patches import ds_bot_history_native as p

class NativeHistoryTests(unittest.TestCase):
    def test_native_integration_is_idempotent(self):
        groups = [
            [(p.ANCHOR, p.INSERT+p.ANCHOR), (p.OLD,p.NEW), (p.HOOK,p.HOOK_NEW)],
            [(p.HOST_ROWS,p.HOST_ROWS_NEW),(p.HOST_SLOT,p.HOST_SLOT_NEW)],
            [(p.ROOT_STATE,p.ROOT_STATE_NEW),(p.HERO,p.HERO_NEW),(p.CHILD,p.CHILD_NEW),(p.DECLARE,p.DECLARE_NEW)] + p.VIEW_REPLACEMENTS,
        ]
        for pairs in groups:
            source='\n'.join(a for a,b in pairs)
            fixed=p.patch(source,pairs)
            self.assertEqual(p.patch(fixed,pairs),fixed)
    def test_unknown_source_is_rejected(self):
        with self.assertRaises(ValueError):
            p.patch('unknown',[(p.HERO,p.HERO_NEW)])
    def test_duplicate_source_is_rejected(self):
        with self.assertRaises(ValueError):
            p.patch(p.HERO+p.HERO,[(p.HERO,p.HERO_NEW)])

if __name__=='__main__':
    unittest.main()
