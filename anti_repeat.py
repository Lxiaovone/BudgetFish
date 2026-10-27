# -*- coding: utf-8 -*-
"""Anti-repetition and lightweight reply polishing."""

import re

LONG_HINTS = ("代码", "写一个", "写个", "详细", "解释一下", "原理", "教程", "步骤", "怎么实现")
MAX_SHORT_CHARS = 40
BAN_PHRASES = (
    "有啥好玩", "有什么好玩", "啥新鲜", "什么新鲜", "分享一下",
    "新皮肤", "新壁纸", "换了壁纸", "新成员", "听说", "外面天气",
)
FALLBACKS = (
    "换个说法吧。",
    "让我重新组织一下语言。",
    "等我想一下，刚才词穷了。",
)


def _bigrams(s):
    s = re.sub(r"[\s\W_]+", "", (s or "").lower())
    if len(s) < 2:
        return {s} if s else set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def similarity(a, b):
    sa, sb = _bigrams(a), _bigrams(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / min(len(sa), len(sb))


def _strip_sentences(text, bad):
    parts = re.split(r"(?<=[。！？!?])", text)
    return "".join(p for p in parts if p.strip() and not bad(p)).strip()


class AntiRepeat(object):
    def __init__(self, recent=None):
        self.recent = list(recent or [])[-5:]
        self.asked = []
        self._fb = 0

    def is_repeat(self, reply):
        return any(similarity(reply, c) >= 0.6 for c in self.recent if c)

    def remember(self, reply):
        self.recent.append(reply)
        del self.recent[:-5]

    def strip_repeated(self, reply):
        if not self.recent:
            return reply
        out = _strip_sentences(
            reply, lambda s: any(similarity(s, h) >= 0.6 for h in self.recent)
        )
        if out:
            return out
        fb = FALLBACKS[self._fb % len(FALLBACKS)]
        self._fb += 1
        return fb

    def _strip_asked(self, reply):
        parts = re.split(r"(?<=[。！？!?])", reply)
        kept = []
        for p in parts:
            s = p.strip()
            if not s:
                continue
            is_q = s.endswith(("？", "?"))
            if is_q and any(similarity(s, q) >= 0.45 for q in self.asked[-8:]):
                continue
            if is_q:
                self.asked.append(s)
                del self.asked[:-8]
            kept.append(p)
        return "".join(kept).strip() or reply

    def polish(self, reply, long_mode=False, is_owner=True):
        if not reply:
            return reply
        reply = re.sub(r"\[[^\[\]]{0,12}\]", "", reply)
        reply = re.sub(r"\s{2,}", " ", reply).strip()
        if not reply:
            return ""

        cleaned = _strip_sentences(reply, lambda s: any(b in s for b in BAN_PHRASES))
        if cleaned:
            reply = cleaned

        if long_mode:
            return reply

        if is_owner:
            reply = self._strip_asked(reply)
            if self.recent and self.recent[-1].rstrip().endswith(("？", "?")):
                cut = _strip_sentences(
                    reply, lambda s: s.rstrip().endswith(("？", "?"))
                )
                if cut:
                    reply = cut

        if len(reply) > MAX_SHORT_CHARS:
            head = reply[:MAX_SHORT_CHARS]
            pos = max(head.rfind("。"), head.rfind("！"), head.rfind("？"))
            reply = reply[:pos + 1] if pos > 12 else head.rstrip("，、 ,") + "。"
        return reply

    def retry_hint(self):
        return "你刚才那句话太像了，换一种完全不同的说法。"
