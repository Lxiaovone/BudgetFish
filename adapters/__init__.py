# -*- coding: utf-8 -*-
"""Adapter factory. Add new platforms here without touching the core."""


def get_adapter(name=None):
    import config

    name = (name or config.PLATFORM).strip().lower()
    if name == "console":
        from .console import ConsoleAdapter
        return ConsoleAdapter(user_id=config.CONSOLE_USER_ID)
    if name == "feishu":
        from .feishu import FeishuAdapter
        return FeishuAdapter()
    raise ValueError("unknown platform %r; available: console, feishu" % name)
