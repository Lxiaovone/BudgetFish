# -*- coding: utf-8 -*-
"""Core orchestrator. No chat SDK is imported here; adapters handle platforms."""

import datetime
import json
import logging
import os
import queue
import re
import threading
from pathlib import Path

import adapters
import anti_repeat
import config
import memory
import router
import security

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(config.BOT_HOME / "bot.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("feishu_companion")

config.ensure_dirs()
adapter = adapters.get_adapter()
OWNER_ID = config.OWNER_OPEN_ID

TEXT_EXTS = (".txt", ".md", ".py", ".json", ".csv", ".log", ".ini", ".cfg",
             ".bat", ".ps1", ".html", ".xml", ".yml", ".yaml", ".toml")
_core_lock = threading.Lock()

try:
    CORE_MEMORY = config.MEMORY_CORE_PATH.read_text(encoding="utf-8").strip()
except OSError:
    CORE_MEMORY = ""


def load_state():
    try:
        return json.loads(config.STATE_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def save_state(st):
    with _core_lock:
        tmp = config.STATE_PATH.with_name(config.STATE_PATH.name + ".tmp")
        tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, config.STATE_PATH)


_anti = anti_repeat.AntiRepeat(load_state().get("recent_replies") or [])


def _remember_reply(reply):
    _anti.remember(reply)
    try:
        st = load_state()
        st["recent_replies"] = list(_anti.recent)
        save_state(st)
    except Exception:
        pass


def send_text(chat_id, text, owner=False):
    safe = security.sanitize_outgoing(text, owner=owner)
    return adapter.send_text(chat_id, safe)


def _save_exchange(text, reply):
    try:
        memory.save_memory(
            "用户：%s\n助手：%s" % (text, reply),
            tags=memory.extract_tags(text),
            is_emotion_high=memory.is_high_emotion(text),
        )
    except Exception as e:
        log.warning("记忆保存失败：%s", e)


def _generate_for(text, is_owner):
    if is_owner:
        store = ""
        try:
            store = memory.retrieve_memory(text)
        except Exception as e:
            log.warning("记忆检索失败：%s", e)
        parts = []
        if CORE_MEMORY:
            parts.append("Permanent memory:\n" + CORE_MEMORY)
        if store:
            parts.append(store)
        context = "\n\n".join(parts)
        long_mode = any(k in text for k in anti_repeat.LONG_HINTS)

        reply = router.generate_reply(text, context, cloud_memory_context="")
        if not reply:
            reply = "我在，刚才走神了，再说一遍？"
        if _anti.is_repeat(reply):
            retry = router.generate_reply(
                text + "\n" + _anti.retry_hint(), context, allow_cloud=False,
                cloud_memory_context="")
            if retry:
                reply = retry
        reply = _anti.strip_repeated(reply)
        reply = _anti.polish(reply, long_mode=long_mode, is_owner=True)
        _save_exchange(text, reply)
        _remember_reply(reply)
        return reply

    reply = router.generate_reply_guest(text)
    return _anti.polish(reply or "我现在没什么想说的。",
                        long_mode=any(k in text for k in anti_repeat.LONG_HINTS),
                        is_owner=False)


# ---------------------------------------------------------------- files
def _send_file_query(text):
    t = (text or "").strip()
    for prefix in ("send file", "发送文件", "发文件"):
        if t.lower().startswith(prefix.lower()):
            return t[len(prefix):].strip(" ：:，,。.、") or None
    m = re.match(r"^(?:把|将)?\s*(.+?)\s*(?:文件)?\s*"
                 r"(?:发给我|发送给我|发我|发过来|传给我|传过来|send me)$", t, re.I)
    if m:
        q = re.sub(r"文件$", "", m.group(1).strip(" 「」『』\"'：:，,。.、")).strip()
        return q or None
    return None


def _handle_send_file(text, chat_id):
    q = _send_file_query(text)
    if not q:
        return False
    hits = [p for p in config.SEND_DIR.glob("*%s*" % q) if p.is_file()]
    if not hits:
        send_text(chat_id, "发送目录里没找到带「%s」的文件。" % q, owner=True)
        return True
    if len(hits) > 3:
        lines = ["匹配到多个文件："] + ["- %s" % p.name for p in hits[:6]]
        send_text(chat_id, "\n".join(lines), owner=True)
        return True
    ok, msg = adapter.send_file(chat_id, str(hits[0]))
    send_text(chat_id, msg, owner=True)
    if ok:
        _save_exchange(text, msg)
    return True


def _handle_attachments(msg, owner):
    if not owner:
        send_text(msg.chat_id, "访客不能发文件。", owner=False)
        return
    for att in msg.attachments:
        try:
            data = adapter.download_attachment(att)
        except Exception as e:
            log.warning("下载失败：%s", e)
            send_text(msg.chat_id, "这个文件下载失败。", owner=True)
            return
        safe = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", att.name)[:80] or "file"
        path = config.DOWNLOAD_DIR / ("%s_%s" % (
            datetime.datetime.now().strftime("%Y%m%d-%H%M%S"), safe))
        path.write_bytes(data)
        ext = Path(safe).suffix.lower()
        if ext in TEXT_EXTS and len(data) <= config.MAX_TEXT_READ:
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                text = data.decode("gbk", "ignore")
            text = text.strip()[:3000]
            if text:
                reply = _generate_for(
                    "用户发来一个文件（%s），内容节选：\n%s" % (att.name, text), True)
                send_text(msg.chat_id, "%s\n（存到 %s）" % (reply, path.name), owner=True)
                return
        send_text(msg.chat_id, "收到「%s」（%.1f KB）。" % (att.name, len(data) / 1024),
                  owner=True)


# ---------------------------------------------------------------- handler
_QUEUE = queue.Queue(maxsize=5)
_SEEN = set()
_SEEN_LOCK = threading.Lock()


def _seen(message_id):
    if not message_id:
        return False
    with _SEEN_LOCK:
        if message_id in _SEEN:
            return True
        _SEEN.add(message_id)
        if len(_SEEN) > 2000:
            _SEEN.clear()
    return False


def handle(msg):
    try:
        if _seen(msg.message_id):
            return
        if msg.is_group and not msg.mentioned:
            return
        owner = security.is_owner(msg.user_id, OWNER_ID)

        if msg.attachments:
            _handle_attachments(msg, owner)
            return

        text = (msg.text or "").strip()
        if not text:
            return

        if owner:
            st = load_state()
            st["chat_id"] = msg.chat_id
            st["last_active"] = datetime.datetime.now().isoformat(timespec="seconds")
            save_state(st)

            mode_reply = router.mode_say(text)
            if mode_reply:
                send_text(msg.chat_id, mode_reply, owner=True)
                return
            if _handle_send_file(text, msg.chat_id):
                return

        reply = _generate_for(text, owner)
        send_text(msg.chat_id, reply, owner=owner)
    except Exception:
        log.exception("消息处理失败")


def on_message(msg):
    try:
        _QUEUE.put_nowait(msg)
    except queue.Full:
        log.warning("队列满了，丢掉一条消息")


def _worker():
    while True:
        item = _QUEUE.get()
        try:
            handle(item)
        except Exception:
            log.exception("工作线程处理失败")
        finally:
            _QUEUE.task_done()


# ---------------------------------------------------------------- main
def main():
    print("物理记忆流：tag_index.json 才是真源。")
    log.info("启动；平台=%s 数据目录=%s", config.PLATFORM, config.BOT_HOME)
    try:
        log.info("记忆库：%s", memory.init())
    except Exception as e:
        log.error("记忆库初始化失败：%s", e)
    try:
        memory.start_decay_thread()
    except Exception as e:
        log.warning("衰减线程启动失败：%s", e)

    threading.Thread(target=_worker, daemon=True, name="message-worker").start()
    adapter.run(on_message)


if __name__ == "__main__":
    main()
