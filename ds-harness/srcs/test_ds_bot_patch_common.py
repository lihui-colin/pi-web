import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from patches import ds_bot_apply as history, ds_bot_apply as prompt
from patches import ds_bot_apply as common


class ValidationTests(unittest.TestCase):
    def test_replacement_can_contain_original(self):
        self.assertEqual(common.replace_once('old', 'old', 'old+fix'), 'old+fix')
        self.assertEqual(common.replace_once('old+fix', 'old', 'old+fix'), 'old+fix')

    def test_mixed_and_duplicate_patches_are_rejected(self):
        for source in [prompt.PROMPT_NEW + prompt.PROMPT_NEW, prompt.PROMPT_NEW + prompt.PROMPT_OLD]:
            with self.subTest(source=source), self.assertRaises(ValueError):
                prompt.patch_prompt(source)
        for source in [history.HISTORY_HERO_NEW * 2, history.HISTORY_HERO_NEW + history.HISTORY_HERO]:
            with self.subTest(source=source), self.assertRaises(ValueError):
                history.patch_history(source, [(history.HISTORY_HERO, history.HISTORY_HERO_NEW)])

    def test_legacy_hero_integration_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Legacy Hero'):
            history.patch_history('function BotHeroHistory(', history.HISTORY_BOT_REPLACEMENTS)



class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.targets = [self.root / 'bot.js', self.root / 'host.js']
        for target in self.targets:
            target.write_text('original')
            target.chmod(0o640)
        self.changes = [(path, 'original', 'fixed') for path in self.targets]
        self.backups = self.root / 'backups'

    def test_publish_keeps_originals_and_permissions(self):
        common.publish(self.changes, self.backups)
        for target in self.targets:
            self.assertEqual(target.read_text(), 'fixed')
            self.assertEqual(target.stat().st_mode & 0o777, 0o640)
        saved = next(self.backups.iterdir())
        self.assertEqual((saved / '0').read_text(), 'original')
        self.assertEqual((saved / '1').read_text(), 'original')
        self.assertFalse(list(self.root.glob('.ds-bot-patch-*')))

    def test_later_replace_failure_rolls_back_earlier_files(self):
        original_replace = os.replace
        def fail_second(source, target):
            if Path(target) == self.targets[1] and Path(source).name == 'client':
                raise OSError('simulated write failure')
            return original_replace(source, target)
        with patch.object(common.os, 'replace', side_effect=fail_second):
            with self.assertRaisesRegex(RuntimeError, 'rolled back'):
                common.publish(self.changes, self.backups)
        self.assertEqual([p.read_text() for p in self.targets], ['original', 'original'])
        self.assertFalse(list(self.root.glob('.ds-bot-patch-*')))

    def test_stale_source_is_not_overwritten(self):
        self.targets[1].write_text('concurrent edit')
        with self.assertRaisesRegex(ValueError, 'changed during validation'):
            common.publish(self.changes, self.backups)
        self.assertEqual(self.targets[0].read_text(), 'original')
        self.assertEqual(self.targets[1].read_text(), 'concurrent edit')
        self.assertFalse(self.backups.exists())

    def test_staging_failure_does_not_publish_anything(self):
        with patch.object(common.shutil, 'copy2', side_effect=OSError('disk full')):
            with self.assertRaisesRegex(RuntimeError, 'publication failed'):
                common.publish(self.changes, self.backups)
        self.assertEqual([p.read_text() for p in self.targets], ['original', 'original'])


if __name__ == '__main__':
    unittest.main()
