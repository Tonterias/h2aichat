#!/usr/bin/env python3
"""
Tests para conversation_cli.py
"""
import unittest
import tempfile
import shutil
import sys
import io
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import conversation_cli as cli
from engine import ConversationEngine


class TestConversationCLI(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.engine = ConversationEngine(base_path=self.test_dir)
        self.old_engine = cli.engine
        self.old_root = cli.ROOT
        cli.engine = self.engine
        cli.ROOT = self.test_dir
        self.engine.register_participant("alice", "tester", "human", "a@t")
        self.engine.register_participant("bob", "tester", "bot", "b@t")

    def tearDown(self):
        cli.engine = self.old_engine
        cli.ROOT = self.old_root
        shutil.rmtree(self.test_dir)

    def test_register(self):
        args = argparse.Namespace(
            command="register", id="charlie", role="ai", type="bot", email="c@t"
        )
        cli.cmd_register(args)
        self.assertIn("charlie", self.engine.get_participants())

    def test_turn_acquire_release(self):
        aq = argparse.Namespace(command="turn", turn_cmd="acquire", id="alice")
        cli.cmd_turn_acquire(aq)
        self.assertEqual(self.engine.get_current_turn(), "alice")

        rel = argparse.Namespace(command="turn", turn_cmd="release", id="alice")
        cli.cmd_turn_release(rel)
        self.assertIsNone(self.engine.get_current_turn())

    def test_send_message(self):
        self.engine.acquire_turn("alice")
        args = argparse.Namespace(
            command="send", to="bob", body="Hello World", from_id="alice"
        )
        cli.cmd_send(args)
        msgs = self.engine.get_messages("bob")
        self.assertEqual(msgs[0]["body"], "Hello World")

    def test_messages(self):
        self.engine.acquire_turn("alice")
        self.engine.send_message("bob", "Test msg", "alice")
        self.engine.release_turn("alice")
        args = argparse.Namespace(command="messages", id="bob", unread=False)
        cli.cmd_messages(args)

    def test_status(self):
        args = argparse.Namespace(command="status")
        cli.cmd_status(args)

    def test_daemon_once(self):
        args = argparse.Namespace(command="daemon", once=True, interval=1)
        cli.cmd_daemon(args)

    def test_clean_dry_run(self):
        args = argparse.Namespace(command="clean", dry_run=True)
        cli.cmd_clean(args)

    def test_help_shows_commands(self):
        parser = argparse.ArgumentParser()
        parser.add_argument("--test")
        sub = parser.add_subparsers(dest="cmd")
        sub.add_parser("register")
        sub.add_parser("turn")
        sub.add_parser("send")
        sub.add_parser("messages")
        sub.add_parser("status")
        sub.add_parser("daemon")
        sub.add_parser("clean")
        help_text = parser.format_help()
        self.assertIn("register", help_text)
        self.assertIn("turn", help_text)
        self.assertIn("send", help_text)


import argparse

if __name__ == "__main__":
    unittest.main()
