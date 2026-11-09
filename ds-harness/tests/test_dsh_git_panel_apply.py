"""Optional Git button removal must leave unrelated contributions intact."""
import test_support  # Configure the service source import path.
from pathlib import Path
import tempfile
import unittest

from patches.plugins.git_panel import dsh_git_panel_apply as p


class GitPanelPatchTests(unittest.TestCase):
    def test_present_absent_and_repeated_application(self):
        unrelated = 'registerGitView();registerSidebar();'
        for pill in (p.PILL, p.PILL_1131, p.PILL_1132):
            fixed = p.patch(unrelated + pill)
            self.assertEqual(fixed, unrelated + p.REMOVED)
            self.assertEqual(p.patch(fixed), fixed)
        self.assertEqual(p.patch(unrelated), unrelated)

    def test_missing_package_is_skipped(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(p.plan_changes(Path(temp) / 'missing'), [])

    def test_changed_or_duplicate_registration_is_rejected(self):
        for source in ('unknown git-panel-pill registration', p.PILL * 2, p.PILL + p.REMOVED,
                       p.PILL_1131 * 2, p.PILL + p.PILL_1131, p.PILL_1131 + p.REMOVED,
                       p.PILL_1132 * 2, p.PILL_1131 + p.PILL_1132, p.PILL_1132 + p.REMOVED):
            with self.assertRaises(ValueError):
                p.patch(source)


if __name__ == '__main__':
    unittest.main()
