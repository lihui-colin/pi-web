import test_support  # Configure the service source import path.
import unittest
from patches.plugins.ds_bot import ds_bot_apply as p

class MobilePatchTests(unittest.TestCase):
    def source(self):
        return '\n'.join([p.MOBILE_GRID, p.MOBILE_TRACK, p.MOBILE_GROUP_OLD, p.MOBILE_META_CSS, p.MOBILE_RAIL_CSS, p.MOBILE_COMPOSER])

    def test_layout_patch_is_idempotent(self):
        fixed = p.patch_mobile(self.source())
        self.assertEqual(p.patch_mobile(fixed), fixed)
        self.assertEqual(fixed.count(p.MOBILE_PHONE_CSS), 1)
        self.assertEqual(fixed.count(p.MOBILE_COMPOSER_CSS), 1)

    def test_unknown_bundle_is_rejected(self):
        with self.assertRaises(ValueError):
            p.patch_mobile('unknown')

    def test_existing_voice_position_patch_migrates(self):
        fixed = p.patch_mobile(self.source())
        previous = fixed.replace(p.VOICE_POSITION_CSS, p.VOICE_POSITION_LEGACY_CSS)
        self.assertEqual(p.patch_mobile(previous), fixed)
        self.assertNotIn(p.VOICE_POSITION_LEGACY_CSS, fixed)

if __name__=='__main__':
    unittest.main()
