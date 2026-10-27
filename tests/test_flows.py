# -*- coding: utf-8 -*-
import json
import os
import tempfile
import types
import unittest

from adapters.base import IncomingMessage

HOME = tempfile.mkdtemp(prefix="oss_flow_")
os.environ["BOT_HOME"] = HOME
os.environ["FEISHU_APP_ID"] = "cli_test"
os.environ["FEISHU_APP_SECRET"] = "secret_test"
os.environ["OWNER_OPEN_ID"] = "ou_owner_test"
os.environ["HUMAN_DELAY"] = "0"

import main as m  # noqa: E402


def event(open_id, text, mid):
    return IncomingMessage(message_id=mid, user_id=open_id, chat_id="oc_test", text=text)


class FlowTest(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.saved = []
        self._orig = (m.router.generate_reply, m.router.generate_reply_guest)
        m._SEEN.clear()
        m.OWNER_ID = "ou_owner_test"
        m._anti.recent.clear()
        m._anti.asked.clear()
        m.send_text = lambda chat_id, text, owner=False: (
            self.sent.append((m.security.sanitize_outgoing(text, owner=owner), owner)) or True)
        m.router.generate_reply = lambda text, memory="", **kw: "Reply D:\\private\\a.txt"
        m.router.generate_reply_guest = lambda text: "Guest D:\\private\\a.txt ip 10.0.0.5"

    def tearDown(self):
        m.router.generate_reply, m.router.generate_reply_guest = self._orig

    def test_owner_saves_memory_and_keeps_path(self):
        m.handle(event("ou_owner_test", "remember the exam", "om_1"))
        self.assertEqual(len(self.sent), 1)
        self.assertTrue(self.sent[0][1])
        self.assertIn("D:\\private\\a.txt", self.sent[0][0])
        self.assertGreaterEqual(len(list(m.memory.DAILY_DIR.glob("*.txt")))
                                + len(list(m.memory.CORE_DIR.glob("*.txt"))), 1)

    def test_guest_no_memory_and_redacted(self):
        before = list(m.memory.DAILY_DIR.glob("*.txt")) + list(m.memory.CORE_DIR.glob("*.txt"))
        m.handle(event("ou_guest", "hello", "om_2"))
        after = list(m.memory.DAILY_DIR.glob("*.txt")) + list(m.memory.CORE_DIR.glob("*.txt"))
        self.assertEqual(len(after), len(before))
        self.assertFalse(self.sent[0][1])
        self.assertNotIn("D:\\private", self.sent[0][0])
        self.assertNotIn("10.0.0.5", self.sent[0][0])

    def test_duplicate_ignored(self):
        ev = event("ou_owner_test", "hi", "om_dup")
        m.handle(ev)
        m.handle(ev)
        self.assertEqual(len(self.sent), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
