# -*- coding: utf-8 -*-
"""V6 双轨记忆的测试（2026-11-13 跟着 memory.py 一起升级）。

老测试是按「7 天转模糊 / 30 天归档」写的，那套已经废了；
现在是 real = fast + slow，real<=0 归档，0<real<25 算模糊。
"""
import datetime
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

HOME = tempfile.mkdtemp(prefix="oss_memory_")
os.environ["BOT_HOME"] = HOME

import memory as mm  # noqa: E402


def _rel_of(path):
    return mm._rel(Path(path))


def _patch_item(rel, **kw):
    """直接改索引里某条记忆的分数/日期，用来模拟时间流逝。"""
    data = mm._read_index()
    item = data["items"].setdefault(rel, {})
    item.update(kw)
    mm._atomic_write_json(mm.INDEX_PATH, data)


class MemoryTest(unittest.TestCase):
    def setUp(self):
        self._reset()

    def _reset(self):
        for d in (mm.CORE_DIR, mm.DAILY_DIR, mm.FUZZY_DIR, mm.ARCHIVE_DIR):
            for p in d.glob("*.txt"):
                p.unlink()
        if mm.INDEX_PATH.exists():
            mm.INDEX_PATH.unlink()
        mm.init()

    # ---------------- 基础 ----------------
    def test_one_file_per_memory(self):
        p1 = mm.save_memory("用户说周三考试", ["考试"], False)
        p2 = mm.save_memory("用户说周五交论文", ["论文"], False)
        self.assertNotEqual(p1, p2)
        self.assertEqual(len(list(mm.DAILY_DIR.glob("*.txt"))), 2)

    def test_index_mounts_paths_only(self):
        mm.save_memory("周三考试", ["考试"], False)
        data = json.loads(mm.INDEX_PATH.read_text(encoding="utf-8"))
        blob = json.dumps(data, ensure_ascii=False)
        self.assertIn("Mem_Daily/", blob)
        self.assertNotIn("用户说周三考试", blob)
        self.assertEqual(data["version"], 2)

    def test_filename_cleanup(self):
        p = Path(mm.save_memory('路径 C:\\a/b:c*?"<>| 测试', ["测试"], False))
        for ch in '\\/:*?"<>|':
            self.assertNotIn(ch, p.name)
        self.assertTrue(p.name.endswith(".txt"))

    def test_tag_and_emotion(self):
        self.assertTrue(mm.is_high_emotion("太开心了！！！"))
        self.assertFalse(mm.is_high_emotion("今天中午吃了白饭"))
        self.assertIn("考试", mm.extract_tags("下周三考试"))

    # ---------------- V6 双轨 ----------------
    def test_new_memory_starts_full_fast(self):
        p = mm.save_memory("周三考试很重要", ["考试"], False)
        item = mm._read_index()["items"][_rel_of(p)]
        self.assertAlmostEqual(item["fast"], mm.INIT_FAST, places=2)
        self.assertAlmostEqual(item["slow"], mm.INIT_SLOW, places=2)
        # 快轨封顶：绝不能超过 FAST_CAP
        self.assertLessEqual(item["fast"], mm.FAST_CAP)

    def test_emotion_memory_decays_slower(self):
        p = mm.save_memory("特别难过的事", ["心情"], True)
        item = mm._read_index()["items"][_rel_of(p)]
        self.assertGreaterEqual(item["slow"], mm.INIT_SLOW_EMOTION)

    def test_fuzzy_state_adds_uncertain_prefix(self):
        p = mm.save_memory("周三考试很重要", ["考试"], False)
        rel = _rel_of(p)
        # real = 10 + 5 = 15 < 25 → 模糊
        _patch_item(rel, fast=10.0, slow=5.0)
        ctx = mm.retrieve_memory("考试")
        self.assertIn("【这是一段模糊的记忆", ctx)

    def test_dead_memory_not_recalled(self):
        p = mm.save_memory("周三考试很重要", ["考试"], False)
        rel = _rel_of(p)
        _patch_item(rel, fast=0.0, slow=0.0)
        self.assertEqual(mm.retrieve_memory("考试"), "")

    def test_hit_reinforces_scores(self):
        p = mm.save_memory("周三考试很重要", ["考试"], False)
        rel = _rel_of(p)
        _patch_item(rel, fast=10.0, slow=5.0)
        mm.retrieve_memory("考试")
        item = mm._read_index()["items"][rel]
        self.assertAlmostEqual(item["fast"], 20.0, places=2)   # +10
        self.assertGreaterEqual(item["slow"], 6.0)             # 慢轨也涨

    def test_decay_tombstone_archives(self):
        p = mm.save_memory("临时记一句", ["闲聊"], False)
        rel = _rel_of(p)
        old = (datetime.date.today() - datetime.timedelta(days=40)).isoformat()
        _patch_item(rel, fast=4.0, slow=1.0, last_decay=old)
        counts = mm.decay_task()
        self.assertEqual(counts["tombstoned"], 1)
        self.assertEqual(len(list(mm.ARCHIVE_DIR.glob("*.txt"))), 1)
        self.assertNotIn(rel, mm._read_index()["items"])

    def test_core_never_decays(self):
        p = mm.save_memory("生日是 5 月 1 日", ["生日"], True)
        rel = _rel_of(p)
        old = (datetime.date.today() - datetime.timedelta(days=365)).isoformat()
        _patch_item(rel, last_decay=old)
        before = mm._read_index()["items"][rel]["slow"]
        mm.decay_task()
        self.assertTrue(Path(p).exists())
        self.assertAlmostEqual(mm._read_index()["items"][rel]["slow"], before, places=2)

    def test_decay_aborts_when_too_many_die(self):
        paths = [mm.save_memory("第%d条" % i, ["测试"], False) for i in range(5)]
        old = (datetime.date.today() - datetime.timedelta(days=40)).isoformat()
        data = mm._read_index()
        for p in paths:
            data["items"][_rel_of(p)].update({"fast": 2.0, "slow": 0.5, "last_decay": old})
        mm._atomic_write_json(mm.INDEX_PATH, data)
        counts = mm.decay_task()
        self.assertTrue(counts["aborted"])
        self.assertEqual(counts["tombstoned"], 0)          # 熔断后一个都不动

    def test_rebuild_from_txt(self):
        mm.save_memory("周三考试", ["考试", "学习"], False)
        mm.INDEX_PATH.write_text("{broken", encoding="utf-8")
        mm.init()
        data = json.loads(mm.INDEX_PATH.read_text(encoding="utf-8"))
        self.assertIn("考试", data["tags"])
        self.assertEqual(data["version"], 2)

    def test_stats_reports_alive(self):
        mm.save_memory("周三考试", ["考试"], False)
        s = mm.stats()
        self.assertGreaterEqual(s.get("alive", 0), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
