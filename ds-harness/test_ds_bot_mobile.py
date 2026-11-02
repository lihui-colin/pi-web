import unittest
from patches import ds_bot_mobile as p

class MobilePatchTests(unittest.TestCase):
    def source(self):
        return '\n'.join([p.GRID, p.TRACK, p.GROUP_OLD.replace('import_react16','import_react17'), p.META_CSS, p.RAIL_CSS, p.COMPOSER])

    def test_tools_only_patch_migrates_without_duplicate_css(self):
        fixed=p.patch(self.source(),'0.2.6')
        tools_only=fixed.replace(p.PHONE_CSS,p.PHONE_TOOLS_CSS)
        migrated=p.patch(tools_only,'0.2.6')
        self.assertEqual(migrated,fixed)
        self.assertEqual(migrated.count(p.PHONE_CSS),1)
        self.assertEqual(p.patch(migrated,'0.2.6'),migrated)

    def test_unknown_version_is_rejected(self):
        with self.assertRaises(ValueError):
            p.patch(self.source(),'0.2.7')

    def test_unknown_bundle_is_rejected(self):
        with self.assertRaises(ValueError):
            p.patch('unknown','0.2.6')

if __name__=='__main__':
    unittest.main()
