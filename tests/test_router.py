# -*- coding: utf-8 -*-
import os
import tempfile
import unittest

HOME = tempfile.mkdtemp(prefix="oss_router_")
os.environ["BOT_HOME"] = HOME
os.environ["HUMAN_DELAY"] = "0"

import router as br  # noqa: E402

ORIG_PING = br.ping_local


class RouterTest(unittest.TestCase):
    def setUp(self):
        br.ping_local = ORIG_PING
        br.config.HUMAN_DELAY = False
        br.config.GUEST_CLOUD_DAILY = 1
        br.config.MODE_PATH = br.config.BOT_HOME / "brain_mode.json"
        br.config.QUOTA_PATH = br.config.BOT_HOME / "quota.json"
        for p in (br.config.MODE_PATH, br.config.QUOTA_PATH):
            try:
                p.unlink()
            except OSError:
                pass

    def test_ping_model_check(self):
        br._session = lambda: type("S", (), {"get": lambda *a, **k: type("R", (), {
            "status_code": 200,
            "json": lambda self: {"models": [{"name": br.config.MODEL_NAME + ":latest"}]},
        })()})()
        self.assertTrue(br.ping_local())

    def test_local_success(self):
        br.ping_local = lambda: True
        br._ask_local = lambda u, m, g: "LOCAL"
        br._ask_cloud = lambda u, m, g: self.fail("cloud should not run")
        self.assertEqual(br.generate_reply("hi", "ctx"), "LOCAL")

    def test_cloud_fallback(self):
        br.ping_local = lambda: False
        br._ask_local = lambda u, m, g: self.fail("local should not run")
        br._ask_cloud = lambda u, m, g: ("CLOUD", "cloud")
        self.assertEqual(br.generate_reply("hi", ""), "CLOUD")

    def test_local_error_cloud(self):
        br.ping_local = lambda: True

        def boom(u, m, g):
            raise RuntimeError("down")

        br._ask_local = boom
        br._ask_cloud = lambda u, m, g: ("CLOUD", "cloud")
        self.assertEqual(br.generate_reply("hi", ""), "CLOUD")

    def test_guest_has_no_memory(self):
        seen = {}
        br.ping_local = lambda: True

        def local(u, m, g):
            seen["m"], seen["g"] = m, g
            return "GUEST"

        br._ask_local = local
        self.assertEqual(br.generate_reply_guest("hi"), "GUEST")
        self.assertEqual(seen["m"], "")
        self.assertTrue(seen["g"])

    def test_guest_quota(self):
        br._quota_consume(True)
        ok, why = br._quota_check(True)
        self.assertFalse(ok)
        self.assertIn("quota", why)
        self.assertTrue(br._quota_check(False)[0])

    def test_mode_switch(self):
        self.assertEqual(br.get_mode(), br.MODE_AUTO)
        self.assertTrue(br.mode_say("local"))
        self.assertEqual(br.get_mode(), br.MODE_LOCAL)
        self.assertTrue(br.mode_say("auto"))
        self.assertEqual(br.get_mode(), br.MODE_AUTO)


if __name__ == "__main__":
    unittest.main(verbosity=2)
