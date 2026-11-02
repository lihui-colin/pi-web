import unittest
from patches.ds_bot_history import (
    ANCHOR, OLD, HOOK, HOST_ROWS, HOST_SLOT, patch, patch_host,
)


class HistoryPatchTests(unittest.TestCase):
    def test_bot_history_moves_out_of_trigger_once(self):
        fixed = patch('\n'.join([ANCHOR, OLD, HOOK]))
        self.assertEqual(patch(fixed), fixed)
        self.assertNotIn(OLD, fixed)
        self.assertEqual(fixed.count('function BotHistory('), 1)

    def test_host_slot_keeps_native_flow_and_is_idempotent(self):
        fixed = patch_host(HOST_ROWS + '\n' + HOST_SLOT)
        self.assertEqual(patch_host(fixed), fixed)
        self.assertIn('...rows,', fixed)
        self.assertEqual(fixed.count('"conversation.chat.node"'), 1)

    def test_unknown_source_is_rejected(self):
        for apply in [patch, patch_host]:
            with self.assertRaises(ValueError):
                apply('unknown bundle')


if __name__ == '__main__':
    unittest.main()
