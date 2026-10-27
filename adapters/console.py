# -*- coding: utf-8 -*-
"""Console adapter: useful for local testing and for writing new adapters."""

import shutil
import sys
import uuid
from pathlib import Path

from .base import Adapter, IncomingMessage


class ConsoleAdapter(Adapter):
    name = "console"

    def __init__(self, user_id="local-user", chat_id="console"):
        self.user_id = user_id
        self.chat_id = chat_id

    def run(self, on_message):
        print("Console adapter. Type a message, Ctrl+C to quit.")
        while True:
            try:
                text = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return
            if not text:
                continue
            on_message(IncomingMessage(
                message_id=uuid.uuid4().hex,
                user_id=self.user_id,
                chat_id=self.chat_id,
                text=text,
            ))

    def send_text(self, chat_id, text):
        print("assistant> %s" % text)
        return True

    def send_file(self, chat_id, path):
        src = Path(path)
        dst = Path.cwd() / src.name
        try:
            if src.resolve() != dst.resolve():
                shutil.copy2(src, dst)
            return True, "file ready: %s" % dst
        except OSError as e:
            return False, "copy failed: %s" % e

    def download_attachment(self, attachment):
        return attachment.data
