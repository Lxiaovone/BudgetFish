# -*- coding: utf-8 -*-
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

HOME = tempfile.mkdtemp(prefix="oss_memory_")
os.environ["BOT_HOME"] = HOME
os.environ["MEM_DAILY_TTL_DAYS"] = "7"
os.environ["MEM_FUZZY_TTL_DAYS"] = "30"

import memory as mm  # noqa: E402


class MemoryTest(unittest.TestCase):
    def setUp(self):
        mm.init()

    def _reset(self):
        for d in (mm.CORE_DIR, mm.DAILY_DIR, mm.FUZZY_DIR, mm.ARCHIVE_DIR):
            for p in d.glob("*.txt"):
                p.unlink()
        if mm.INDEX_PATH.exists():
            mm.INDEX_PATH.unlink()
        mm.init()

    def test_one_file_per_memory(self):
        self._reset()
        p1 = mm.save_memory("用户说周三考试", ["考试"], False)
        p2 = mm.save_memory("用户说周五交论文", ["论文"], False)
        self.assertNotEqual(p1, p2)
        self.assertEqual(len(list(mm.DAILY_DIR.glob("*.txt"))), 2)

    def test_index_mounts_paths_only(self):
        self._reset()
        mm.save_memory("周三考试", ["考试"], False)
        data = json.loads(mm.INDEX_PATH.read_text(encoding="utf-8"))
        blob = json.dumps(data, ensure_ascii=False)
        self.assertIn("Mem_Daily/", blob)
        self.assertNotIn("用户说周三考试", blob)

    def test_fuzzy_prefix_and_archive(self):
        self._reset()
        mm.save_memory("周三考试很重要", ["考试"], False)
        path = list(mm.DAILY_DIR.glob("*.txt"))[0]
        old = time.time() - 8 * 86400
        os.utime(path, (old, old))
        mm.decay_task()
        moved = list(mm.FUZZY_DIR.glob("*.txt"))
        self.assertEqual(len(moved), 1)
        self.assertAlmostEqual(os.path.getmtime(moved[0]), time.time(), delta=15)

        ctx = mm.retrieve_memory("考试")
        self.assertIn("【模糊的记忆】", ctx)

        os.utime(moved[0], (time.time() - 31 * 86400,) * 2)
        mm.decay_task()
        self.assertEqual(len(list(mm.ARCHIVE_DIR.glob("*.txt"))), 1)
        self.assertEqual(mm.retrieve_memory("考试"), "")

    def test_core_never_decays(self):
        self._reset()
        p = mm.save_memory("生日是 5 月 1 日", ["生日"], True)
        os.utime(p, (time.time() - 365 * 86400,) * 2)
        mm.decay_task()
        self.assertTrue(Path(p).exists())

    def test_rebuild_from_txt(self):
        self._reset()
        mm.save_memory("周三考试", ["考试", "学习"], False)
        mm.INDEX_PATH.write_text("{broken", encoding="utf-8")
        mm.init()
        data = json.loads(mm.INDEX_PATH.read_text(encoding="utf-8"))
        self.assertIn("考试", data["tags"])

    def test_filename_cleanup(self):
        self._reset()
        p = Path(mm.save_memory('路径 C:\\a/b:c*?"<>| 测试', ["测试"], False))
        for ch in '\\/:*?"<>|':
            self.assertNotIn(ch, p.name)
        self.assertTrue(p.name.endswith(".txt"))

    def test_tag_and_emotion(self):
        self.assertTrue(mm.is_high_emotion("太开心了！！！"))
        self.assertFalse(mm.is_high_emotion("今天中午吃了白饭"))
        self.assertIn("考试", mm.extract_tags("下周三考试"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
