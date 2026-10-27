# -*- coding: utf-8 -*-
"""Central configuration. Everything personal comes from .env."""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _int(name, default):
    try:
        return int(os.getenv(name) or default)
    except ValueError:
        return int(default)


def _float(name, default):
    try:
        return float(os.getenv(name) or default)
    except ValueError:
        return float(default)


def _bool(name, default=True):
    v = (os.getenv(name) or ("1" if default else "0")).strip().lower()
    return v not in ("0", "false", "no", "off")


BOT_HOME = Path(os.getenv("BOT_HOME") or (BASE_DIR / "data")).resolve()
BOT_HOME.mkdir(parents=True, exist_ok=True)

PLATFORM = (os.getenv("PLATFORM") or "console").strip().lower()
CONSOLE_USER_ID = (os.getenv("CONSOLE_USER_ID") or "local-user").strip()

FEISHU_APP_ID = (os.getenv("FEISHU_APP_ID") or "").strip()
FEISHU_APP_SECRET = (os.getenv("FEISHU_APP_SECRET") or "").strip()
OWNER_OPEN_ID = (os.getenv("OWNER_OPEN_ID") or "").strip()

OLLAMA_BASE_URL = (os.getenv("OLLAMA_BASE_URL") or "http://127.0.0.1:11434/v1").strip()
MODEL_NAME = (os.getenv("MODEL_NAME") or "your-local-model").strip()
LOCAL_TIMEOUT = _float("LOCAL_TIMEOUT", 30)
LOCAL_MAX_TOKENS = _int("LOCAL_MAX_TOKENS", 300)

CLOUD_ENABLED = _bool("CLOUD_ENABLED", True)
CLOUD_API_KEY = (os.getenv("CLOUD_API_KEY") or "").strip()
CLOUD_BASE_URL = (os.getenv("CLOUD_BASE_URL") or "https://api.deepseek.com/v1").strip()
CLOUD_MODEL = (os.getenv("CLOUD_MODEL") or "deepseek-chat").strip()
CLOUD_TIMEOUT = _float("CLOUD_TIMEOUT", 45)
CLOUD_MAX_TOKENS = _int("CLOUD_MAX_TOKENS", 500)
OWNER_CLOUD_DAILY = _int("OWNER_CLOUD_DAILY", 20)
GUEST_CLOUD_DAILY = _int("GUEST_CLOUD_DAILY", 3)

HUMAN_DELAY = _bool("HUMAN_DELAY", True)
PROBE_CONNECT_TIMEOUT = _float("PROBE_CONNECT_TIMEOUT", 0.2)
PROBE_READ_TIMEOUT = _float("PROBE_READ_TIMEOUT", 0.3)

MEM_DAILY_TTL_DAYS = _int("MEM_DAILY_TTL_DAYS", 7)
MEM_FUZZY_TTL_DAYS = _int("MEM_FUZZY_TTL_DAYS", 30)
MEM_EMOTION_HIGH = _float("MEM_EMOTION_HIGH", 0.72)

ASSISTANT_NAME = (os.getenv("ASSISTANT_NAME") or "YourAI").strip()
MAX_UPLOAD_MB = _int("MAX_UPLOAD_MB", 30)
MAX_TEXT_READ = _int("MAX_TEXT_READ", 200 * 1024)

STATE_PATH = BOT_HOME / "state.json"
MEMORY_CORE_PATH = BOT_HOME / "memory_core.md"
PERSONA_PATH = BASE_DIR / "prompts" / "persona.txt"
PERSONA_EXAMPLE_PATH = BASE_DIR / "prompts" / "persona.example.txt"
SEND_DIR = BOT_HOME / "send"
DOWNLOAD_DIR = BOT_HOME / "downloads"
QUOTA_PATH = BOT_HOME / "quota.json"
MODE_PATH = BOT_HOME / "brain_mode.json"


def ensure_dirs():
    for p in (BOT_HOME, SEND_DIR, DOWNLOAD_DIR):
        p.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    print("BASE_DIR", BASE_DIR)
    print("BOT_HOME", BOT_HOME)
    print("OWNER_OPEN_ID_SET", bool(OWNER_OPEN_ID))
