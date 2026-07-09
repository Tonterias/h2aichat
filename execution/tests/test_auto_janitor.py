#!/usr/bin/env python3
"""
Tests para limpieza de buzones en AutoJanitor.
"""
import unittest
import tempfile
import shutil
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from dashboard.auto_janitor import AutoJanitor
from engine import ConversationEngine


class TestMailboxCleaning(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.engine = ConversationEngine(base_path=self.test_dir)
        self.janitor = AutoJanitor(base_path=self.test_dir)
        self.engine.register_participant("miguel", "po", "human", "m@h.local")

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_no_orphans_when_empty(self):
        orphans = self.janitor.scan_orphan_mailboxes()
        self.assertEqual(len(orphans), 0)

    def test_no_orphans_when_valid(self):
        self.assertEqual(len(self.janitor.scan_orphan_mailboxes()), 0)

    def test_detect_orphan_mailbox(self):
        orphan_dir = self.test_dir / "mailboxes" / "fantasma"
        orphan_dir.mkdir(parents=True, exist_ok=True)
        orphans = self.janitor.scan_orphan_mailboxes()
        self.assertIn("fantasma", orphans)

    def test_dry_run_does_not_delete(self):
        orphan_dir = self.test_dir / "mailboxes" / "fantasma"
        orphan_dir.mkdir(parents=True, exist_ok=True)
        result = self.janitor.clean_mailboxes(dry_run=True)
        self.assertIn("fantasma", self.janitor.scan_orphan_mailboxes())
        self.assertTrue(result["dry_run"])

    def test_clean_deletes_orphan(self):
        orphan_dir = self.test_dir / "mailboxes" / "fantasma"
        orphan_dir.mkdir(parents=True, exist_ok=True)
        self.janitor.clean_mailboxes(dry_run=False)
        orphans = self.janitor.scan_orphan_mailboxes()
        self.assertNotIn("fantasma", orphans)

    def test_active_participant_not_inactive(self):
        inactive = self.janitor.scan_inactive_participants(days=30)
        self.assertNotIn("miguel", inactive)

    def test_render_mailbox_status(self):
        orphan_dir = self.test_dir / "mailboxes" / "fantasma"
        orphan_dir.mkdir(parents=True, exist_ok=True)
        status = self.janitor.render_mailbox_status()
        self.assertIn("fantasma", status)
        self.assertIn("Participantes registrados: 1", status)
        self.assertIn("Buzones huerfanos", status)


if __name__ == "__main__":
    unittest.main()
