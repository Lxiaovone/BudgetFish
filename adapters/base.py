# -*- coding: utf-8 -*-
"""Platform adapter contract. The core never imports a chat SDK directly."""

from dataclasses import dataclass, field
from typing import Any, Callable, List


@dataclass
class Attachment:
    name: str
    key: str
    kind: str = "file"          # file / image / audio / media
    message_id: str = ""
    data: bytes = b""
    mime: str = ""


@dataclass
class IncomingMessage:
    message_id: str
    user_id: str
    chat_id: str
    text: str = ""
    is_group: bool = False
    mentioned: bool = True
    attachments: List[Attachment] = field(default_factory=list)
    raw: Any = None


class Adapter:
    """Implement this to support another chat platform."""

    name = "base"

    def run(self, on_message: Callable[[IncomingMessage], None]) -> None:
        """Blocking entry point. Call on_message for each incoming message."""
        raise NotImplementedError

    def send_text(self, chat_id: str, text: str) -> bool:
        raise NotImplementedError

    def send_file(self, chat_id: str, path: str):
        """Return (ok: bool, message: str)."""
        raise NotImplementedError

    def download_attachment(self, attachment: Attachment) -> bytes:
        raise NotImplementedError
