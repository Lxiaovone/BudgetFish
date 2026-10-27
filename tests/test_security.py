# -*- coding: utf-8 -*-
import tempfile
import unittest
from pathlib import Path

import security


class SecurityTest(unittest.TestCase):
    def test_owner(self):
        self.assertTrue(security.is_owner("ou_owner", "ou_owner"))
        self.assertFalse(security.is_owner("ou_other", "ou_owner"))
        self.assertFalse(security.is_owner("", ""))

    def test_safe_join(self):
        root = Path(tempfile.mkdtemp(prefix="oss_sec_"))
        (root / "a.txt").write_text("ok", encoding="utf-8")
        self.assertEqual(security.read_text_locked(root, "a.txt"), "ok")
        for bad in ("../a.txt", "C:\\Windows\\win.ini", "a/../../b", "x.txt:ads"):
            with self.assertRaises(Exception):
                security.safe_join(root, bad)

    def test_guest_redaction(self):
        s = security.sanitize_outgoing(
            "path D:\\secret\\a.txt, ip 192.168.1.5, key sk-example-not-a-real-key-0001, "
            "ou_example000000000000", owner=False)
        self.assertNotIn("D:\\secret", s)
        self.assertNotIn("192.168.1.5", s)
        self.assertNotIn("sk-example", s)
        self.assertNotIn("ou_example", s)
        self.assertIn("[路径已隐藏]", s)

    def test_owner_keeps_path(self):
        s = security.sanitize_outgoing("path D:\\secret\\a.txt", owner=True)
        self.assertIn("D:\\secret\\a.txt", s)


if __name__ == "__main__":
    unittest.main(verbosity=2)
