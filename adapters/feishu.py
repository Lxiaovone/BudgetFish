# -*- coding: utf-8 -*-
"""Feishu adapter. Imported only when PLATFORM=feishu."""

import json
import logging
from pathlib import Path

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateFileRequest,
    CreateFileRequestBody,
    CreateMessageRequest,
    CreateMessageRequestBody,
    GetMessageResourceRequest,
    P2ImMessageReceiveV1,
)

import config
from .base import Adapter, Attachment, IncomingMessage

log = logging.getLogger("feishu_companion.feishu")


class FeishuAdapter(Adapter):
    name = "feishu"

    def __init__(self):
        if not config.FEISHU_APP_ID or not config.FEISHU_APP_SECRET:
            raise RuntimeError("FEISHU_APP_ID / FEISHU_APP_SECRET is missing")
        self.client = (
            lark.Client.builder()
            .app_id(config.FEISHU_APP_ID)
            .app_secret(config.FEISHU_APP_SECRET)
            .log_level(lark.LogLevel.WARNING)
            .build()
        )

    def run(self, on_message):
        def handler(data: P2ImMessageReceiveV1):
            try:
                msg = self._to_message(data)
                if msg is not None:
                    on_message(msg)
            except Exception:
                log.exception("failed to parse event")

        dispatcher = (lark.EventDispatcherHandler.builder("", "")
                      .register_p2_im_message_receive_v1(handler).build())
        ws = lark.ws.Client(config.FEISHU_APP_ID, config.FEISHU_APP_SECRET,
                            event_handler=dispatcher,
                            log_level=lark.LogLevel.WARNING)
        log.info("connecting to Feishu...")
        ws.start()

    def _to_message(self, data):
        event = data.event
        msg = event.message
        sender = event.sender
        if getattr(sender, "sender_type", "") == "app":
            return None
        user_id = ""
        try:
            user_id = sender.sender_id.open_id
        except Exception:
            pass

        text = ""
        attachments = []
        if msg.message_type == "text":
            text = json.loads(msg.content or "{}").get("text", "")
            for m in (msg.mentions or []):
                text = text.replace(m.key, "")
        else:
            info = json.loads(msg.content or "{}")
            key = info.get("file_key") or info.get("image_key") or ""
            name = str(info.get("file_name") or ("image.png" if msg.message_type == "image"
                                                 else "file"))
            if key:
                attachments.append(Attachment(
                    name=name, key=key, kind=msg.message_type,
                    message_id=msg.message_id,
                ))

        return IncomingMessage(
            message_id=msg.message_id,
            user_id=str(user_id or ""),
            chat_id=msg.chat_id,
            text=text.strip(),
            is_group=(msg.chat_type == "group"),
            mentioned=bool(msg.mentions) if msg.chat_type == "group" else True,
            attachments=attachments,
            raw=msg,
        )

    def send_text(self, chat_id, text):
        body = (CreateMessageRequestBody.builder()
                .receive_id(chat_id).msg_type("text")
                .content(json.dumps({"text": text}, ensure_ascii=False)).build())
        req = (CreateMessageRequest.builder().receive_id_type("chat_id")
               .request_body(body).build())
        resp = self.client.im.v1.message.create(req)
        if not resp.success():
            log.error("send failed code=%s msg=%s", resp.code, resp.msg)
            return False
        return True

    def send_file(self, chat_id, path):
        path = Path(path)
        if not path.is_file():
            return False, "file not found"
        if path.stat().st_size > config.MAX_UPLOAD_MB * 1024 * 1024:
            return False, "file larger than %d MB" % config.MAX_UPLOAD_MB
        try:
            with open(path, "rb") as f:
                body = (CreateFileRequestBody.builder()
                        .file_type("stream").file_name(path.name).file(f).build())
                resp = self.client.im.v1.file.create(
                    CreateFileRequest.builder().request_body(body).build())
            if not resp.success():
                if resp.code == 99991672:
                    return False, ("missing scope im:resource:upload "
                                   "(upload file V2)")
                return False, "upload failed: %s" % (resp.msg or resp.code)
            key = getattr(getattr(resp, "data", None), "file_key", "") or ""
            if not key:
                return False, "upload returned no file_key"
            msg_body = (CreateMessageRequestBody.builder()
                        .receive_id(chat_id).msg_type("file")
                        .content(json.dumps({"file_key": key}, ensure_ascii=False)).build())
            msg_resp = self.client.im.v1.message.create(
                CreateMessageRequest.builder().receive_id_type("chat_id")
                .request_body(msg_body).build())
            if not msg_resp.success():
                return False, "file sent but message failed"
            return True, "sent: %s" % path.name
        except Exception as e:
            log.exception("send file failed")
            return False, "send file failed: %s" % str(e)[:80]

    def download_attachment(self, attachment):
        kind = "image" if attachment.kind == "image" else "file"
        req = (GetMessageResourceRequest.builder()
               .message_id(attachment.message_id).file_key(attachment.key)
               .type(kind).build())
        resp = self.client.im.v1.message.resource.get(req)
        if not resp.success():
            raise RuntimeError("download failed: %s" % (resp.msg or resp.code))
        return resp.file.read()
