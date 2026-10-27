# -*- coding: utf-8 -*-
"""Security helpers: owner gate, path lock, outbound redaction."""

import os
import re
from pathlib import Path


def is_owner(sender_open_id, owner_open_id):
    sender = str(sender_open_id or "").strip()
    owner = str(owner_open_id or "").strip()
    return bool(sender) and bool(owner) and sender == owner


def safe_join(root, rel):
    """Join rel under root; reject absolute paths, traversal, UNC and ADS."""
    root = Path(root).resolve()
    rel = str(rel or "").strip()
    if not rel or "\x00" in rel:
        raise PermissionError("empty path")
    if os.path.isabs(rel) or re.match(r"^[A-Za-z]:", rel) or rel.startswith(("\\\\", "//")):
        raise PermissionError("absolute/UNC path is not allowed")
    parts = [p for p in re.split(r"[\\/]+", rel) if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        raise PermissionError("path traversal is not allowed")
    target = (root / Path(*parts)).resolve()
    if target != root and root not in target.parents:
        raise PermissionError("path escapes root")
    if ":" in target.name:
        raise PermissionError("NTFS ADS is not allowed")
    return target


def read_text_locked(root, rel, max_bytes=200 * 1024, exts=(".txt", ".md")):
    path = safe_join(root, rel)
    if not path.is_file():
        raise FileNotFoundError(str(path))
    if path.suffix.lower() not in exts:
        raise PermissionError("file type is not allowed")
    if path.stat().st_size > max_bytes:
        raise PermissionError("file is too large")
    for enc in ("utf-8", "utf-8-sig", "gbk"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return ""


_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
_IPV4 = re.compile(r"(?<![\d.])(?:%s\.){3}%s(?::\d{1,5})?(?![\d.])" % (_OCTET, _OCTET))
_IPV6 = re.compile(r"(?<![\w:])(?:[0-9A-Fa-f]{1,4}:){1,7}:(?:[0-9A-Fa-f]{1,4})?(?![\w:])")
_PATH = re.compile(
    r"(?i)(?<![\w])(?:[A-Za-z]:[\\/][^\s，。；;、）)\]】\r\n]*"
    r"|\\\\[^\s\\/]+(?:\\[^\s，。；;、）)\]】\r\n]+)+)"
)
_API_KEY = re.compile(r"(?i)\bsk-[A-Za-z0-9_\-]{12,}\b")
_FEISHU_ID = re.compile(r"\b(?:ou|oc|cli|om|on)_[A-Za-z0-9]{10,}\b")
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{16,}")


def _redact_ipv4(m):
    before = m.string[max(0, m.start() - 8):m.start()].lower().rstrip()
    if before.endswith(("version", "ver", "v")):
        return m.group(0)
    return "[IP已隐藏]"


def sanitize_outgoing(text, owner=False):
    """Owner keeps paths (useful); guest gets paths/IP/keys redacted."""
    text = str(text or "").replace("😂", "")
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    if owner:
        return text
    text = _PATH.sub("[路径已隐藏]", text)
    text = _API_KEY.sub("[密钥已隐藏]", text)
    text = _FEISHU_ID.sub("[ID已隐藏]", text)
    text = _BEARER.sub("[令牌已隐藏]", text)
    text = _IPV4.sub(_redact_ipv4, text)
    text = _IPV6.sub("[IP已隐藏]", text)
    return text


# Backwards-compatible name used by main.py
security_filter = sanitize_outgoing
