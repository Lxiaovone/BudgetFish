# -*- coding: utf-8 -*-
"""Physical memory store (plain os/json, one memory per TXT).

Design rules:
  1. 一条记忆一个文件，绝对不 append；
  2. tag_index.json 只挂载路径，不存全文；
  3. 日常 7 天 -> 模糊；进模糊时 os.utime 刷新 mtime；模糊再 30 天 -> 归档；
  4. 模糊记忆召回时拼【模糊的记忆】前缀；
  5. JSON is only a cache; rebuild it from TXT headers on startup/corruption.

TXT 头部（重建索引靠它，纯文本可读）：
    # tags: 考试, 高数
    # created: 2026-10-27T12:30:00
    # tier: daily
    ---
    用户：下周三考试

对外：
    init()
    save_memory(content, tags, is_emotion_high) -> path
    retrieve_memory(user_input) -> str
    decay_task() / decay_loop() / start_decay_thread()
    rebuild_index() / stats()
"""

import datetime
import json
import logging
import os
import re
import shutil
import threading
import time
from pathlib import Path

log = logging.getLogger("feishu_companion.memory")

from config import BOT_HOME, MEM_DAILY_TTL_DAYS, MEM_FUZZY_TTL_DAYS, MEM_EMOTION_HIGH

CORE_DIR = BOT_HOME / "Mem_Core"
DAILY_DIR = BOT_HOME / "Mem_Daily"
FUZZY_DIR = BOT_HOME / "Mem_Fuzzy"
ARCHIVE_DIR = BOT_HOME / "Mem_Archive"
INDEX_PATH = BOT_HOME / "tag_index.json"

DIRS = (CORE_DIR, DAILY_DIR, FUZZY_DIR, ARCHIVE_DIR)
FOLDER_TIER = {
    CORE_DIR.name: "core",
    DAILY_DIR.name: "daily",
    FUZZY_DIR.name: "fuzzy",
    ARCHIVE_DIR.name: "archive",
}

DAILY_TTL = MEM_DAILY_TTL_DAYS * 86400
FUZZY_TTL = MEM_FUZZY_TTL_DAYS * 86400
EMOTION_HIGH = MEM_EMOTION_HIGH
MAX_TAGS = 8
MAX_CONTENT = 2000
MAX_FILE_CHARS = 700
MAX_CONTEXT_CHARS = 1500

TAG_HINTS = (
    "考试", "数学", "课", "作业", "论文", "项目", "代码",
    "密码", "生日", "吃饭", "睡觉", "游戏", "心情", "开心", "难过",
    "生气", "旅行", "电影", "音乐", "工作", "学习", "预算", "电脑", "手机",
    "重要", "记住", "别忘",
)
STOP_TAGS = {
    "今天", "现在", "什么", "怎么", "可以", "一个", "这个", "那个", "助手",
    "用户", "我们", "你们", "他们", "就是", "不是", "还是", "已经", "因为",
    "所以", "但是", "然后", "时候", "东西", "事情", "感觉", "觉得", "知道",
    "没有", "真的", "有点", "一下", "帮我", "给我", "这边", "那边",
}
POS_WORDS = ("开心", "高兴", "喜欢", "谢谢", "厉害", "棒", "哈哈", "嘿嘿",
             "期待", "感动", "幸福", "顺利", "成功", "好耶", "可爱", "爽")
NEG_WORDS = ("难过", "伤心", "生气", "气死", "讨厌", "烦", "累", "崩溃",
             "害怕", "焦虑", "失败", "失望", "呜", "哭", "难受", "委屈")

_LOCK = threading.RLock()


# ---------------------------------------------------------------- 基础
def _rel(path):
    return path.resolve().relative_to(BOT_HOME).as_posix()


def _abs(rel):
    p = (BOT_HOME / str(rel)).resolve()
    if p != BOT_HOME and BOT_HOME not in p.parents:
        raise ValueError("索引路径越界：%s" % rel)
    return p


def _atomic_write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _atomic_write_json(path, data):
    text = json.dumps(data, ensure_ascii=False, indent=1)
    _atomic_write_text(path, text)


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _bigrams(s):
    s = re.sub(r"[\s\W_]+", "", (s or "").lower())
    if len(s) < 2:
        return {s} if s else set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


# ---------------------------------------------------------------- 初始化 / 索引
def ensure_layout():
    for d in DIRS:
        d.mkdir(parents=True, exist_ok=True)
    if not INDEX_PATH.exists():
        rebuild_index()


def _read_tags(path):
    """从 TXT 头部读 # tags: a, b。"""
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            head = f.read(2000)
    except OSError:
        return []
    m = re.search(r"(?im)^#\s*tags?\s*[:：]\s*(.+)$", head)
    if not m:
        return []
    return normalize_tags(re.split(r"[,，、;；]+", m.group(1)))


def _strip_header(text):
    if text.lstrip().startswith("# tags"):
        idx = text.find("\n---\n")
        if idx >= 0:
            return text[idx + 5:]
    return text


def rebuild_index():
    """TXT 是真源；扫描三个可检索目录，重建 tag_index.json。"""
    with _LOCK:
        tags = {}
        for folder in (CORE_DIR, DAILY_DIR, FUZZY_DIR):
            for path in sorted(folder.glob("*.txt")):
                rel = _rel(path)
                for tag in _read_tags(path):
                    tags.setdefault(tag, [])
                    if rel not in tags[tag]:
                        tags[tag].append(rel)
        data = {
            "version": 1,
            "rebuilt_at": _now_iso(),
            "tags": tags,
        }
        _atomic_write_json(INDEX_PATH, data)
        log.info("记忆索引已重建：%d 个标签 / %d 个文件",
                 len(tags), len({p for v in tags.values() for p in v}))
        return data


def _read_index():
    if not INDEX_PATH.exists():
        return rebuild_index()
    try:
        with open(INDEX_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("tags"), dict):
            raise ValueError("索引格式不对")
        return data
    except Exception as e:
        log.warning("tag_index.json 损坏，按 TXT 重建：%s", e)
        try:
            return rebuild_index()
        except Exception as e2:
            log.error("重建索引失败：%s", e2)
            return {"version": 1, "tags": {}}


# ---------------------------------------------------------------- 标签 / 情绪
def normalize_tags(tags):
    if tags is None:
        return []
    if isinstance(tags, str):
        parts = re.split(r"[,，、;；\s]+", tags)
    else:
        parts = list(tags)
    out = []
    for t in parts:
        t = re.sub(r"[\x00-\x1f]", "", str(t or "")).strip().lower()[:30]
        if t and t not in out:
            out.append(t)
    return out[:MAX_TAGS]


def extract_tags(text):
    """规则抽标签：已知词 + 短中文词；不调模型。"""
    s = str(text or "")
    hits = []
    for kw in TAG_HINTS:
        if kw in s:
            hits.append(kw)
    # 口语里“考高数”不一定出现“考试”，补一个
    if "考" in s or "考试" in s:
        hits.append("考试")
    if "吃" in s:
        hits.append("吃饭")

    for tok in re.findall(r"[\u4e00-\u9fa5]{2,}|[A-Za-z][A-Za-z0-9_+-]{2,}", s):
        tok = tok.lower()
        if tok in STOP_TAGS:
            continue
        if len(tok) <= 4:
            hits.append(tok)
        else:
            for kw in TAG_HINTS:
                if kw in tok:
                    hits.append(kw)
    return normalize_tags(hits)


def emotion_score(text):
    """0~1 情绪/重要度；不调模型。"""
    s = str(text or "")
    score = 0.5
    score += min(s.count("！") + s.count("!"), 3) * 0.08
    score += min(s.count("？") + s.count("?"), 3) * 0.02
    pos = sum(s.count(w) for w in POS_WORDS)
    neg = sum(s.count(w) for w in NEG_WORDS)
    score += min(max(pos, neg), 3) * 0.05
    if any(w in s for w in ("太", "超级", "非常", "特别", "巨", "好")):
        score += 0.04
    for kw, w in (("重要", 0.12), ("记住", 0.12), ("别忘", 0.12),
                  ("答应", 0.10), ("约定", 0.10), ("密码", 0.16),
                  ("钥匙", 0.14), ("生日", 0.14), ("考试", 0.10),
                  ("截止", 0.10), ("提醒我", 0.10)):
        if kw in s:
            score += w
    if len(s) >= 60:
        score += 0.05
    return round(max(0.03, min(0.97, score)), 3)


def is_high_emotion(text):
    return emotion_score(text) >= EMOTION_HIGH


# ---------------------------------------------------------------- 文件名
def _summary(content):
    s = ""
    for line in str(content or "").replace("\r\n", "\n").splitlines():
        if line.strip():
            s = line.strip()
            break
    s = re.sub(r"^(用户|助手|你|我)[:：]\s*", "", s)
    s = re.sub(r'[\\/:*?"<>|]', "", s)
    s = re.sub(r"[\x00-\x1f]", "", s)
    s = re.sub(r"\s+", " ", s).strip(" .")
    return s[:24] or "记忆"


def _filename(content):
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    return "%s_%s.txt" % (ts, _summary(content))


def _unique_path(folder, name):
    path = folder / name
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for i in range(1, 100):
        p = folder / ("%s_%d%s" % (stem, i, suffix))
        if not p.exists():
            return p
    return folder / ("%s_%d%s" % (stem, int(time.time() * 1000), suffix))


# ---------------------------------------------------------------- 写
def save_memory(content, tags=None, is_emotion_high=False):
    """一条记忆一个 TXT；绝不 append。返回文件路径。"""
    content = str(content or "").strip()
    if not content:
        return ""
    content = content[:MAX_CONTENT]
    tag_list = normalize_tags(tags if tags is not None else extract_tags(content))
    if not tag_list:
        tag_list = ["未分类"]

    folder = CORE_DIR if bool(is_emotion_high) else DAILY_DIR
    tier = FOLDER_TIER[folder.name]
    header = (
        "# tags: %s\n"
        "# created: %s\n"
        "# tier: %s\n"
        "---\n"
        % (", ".join(tag_list), _now_iso(), tier)
    )

    with _LOCK:
        ensure_layout()
        path = _unique_path(folder, _filename(content))
        _atomic_write_text(path, header + content + "\n")

        # 索引只是缓存；写失败也不影响 TXT 真源，下次启动会重建
        try:
            data = _read_index()
            rel = _rel(path)
            for tag in tag_list:
                arr = data["tags"].setdefault(tag, [])
                if rel not in arr:
                    arr.append(rel)
            _atomic_write_json(INDEX_PATH, data)
        except Exception as e:
            log.warning("写索引失败（TXT 已落盘，稍后重建）：%s", e)
        log.info("记忆已保存：%s", path.name)
        return str(path)


# ---------------------------------------------------------------- 读
def _ranked(scores):
    def key(item):
        rel, sc = item
        return (-sc, -_mtime(_abs(rel)))
    return sorted(scores.items(), key=key)


def retrieve_memory(user_input):
    """按 tag_index 匹配，取权重最高的 1~2 个文件，拼前缀返回。"""
    q = str(user_input or "").strip()
    if not q:
        return ""
    q_low = q.lower()
    q_tags = set(extract_tags(q))
    q_grams = _bigrams(q)

    with _LOCK:
        ensure_layout()
        data = _read_index()
        tags = data.get("tags") or {}
        scores = {}
        for tag, paths in tags.items():
            if not tag or tag == "未分类":
                continue
            hit = tag in q_low or tag in q_tags
            if not hit:
                t_grams = _bigrams(tag)
                inter = q_grams & t_grams
                if len(inter) >= 2 and len(inter) / max(1, len(t_grams)) >= 0.5:
                    hit = True
            if not hit:
                continue
            for rel in paths:
                scores[rel] = scores.get(rel, 0) + 1

        if not scores:
            return ""

        parts = []
        used = 0
        for rel, _score in _ranked(scores)[:2]:
            try:
                path = _abs(rel)
                if not path.is_file():
                    continue
                with open(path, encoding="utf-8", errors="ignore") as f:
                    text = _strip_header(f.read())
                body = re.sub(r"\s+", " ", text).strip()[:MAX_FILE_CHARS]
                if not body:
                    continue
                tier = FOLDER_TIER.get(path.parent.name, "daily")
                if tier == "fuzzy":
                    block = "【模糊的记忆】：唔，助手隐约记得…… %s" % body
                else:
                    block = "【清晰的记忆】：%s" % body
                if used + len(block) > MAX_CONTEXT_CHARS:
                    block = block[:max(0, MAX_CONTEXT_CHARS - used)]
                if block:
                    parts.append(block)
                    used += len(block)
            except Exception as e:
                log.warning("读记忆失败（%s）：%s", rel, e)
        return "\n\n".join(parts)


# ---------------------------------------------------------------- 衰减
def _move_unique(src, dst_dir):
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    if dst.exists():
        for i in range(1, 100):
            p = dst_dir / ("%s_%d%s" % (src.stem, i, src.suffix))
            if not p.exists():
                dst = p
                break
    shutil.move(str(src), str(dst))
    return dst


def decay_task():
    """日常 7 天 -> 模糊（刷新 mtime）；模糊 30 天 -> 归档。"""
    counts = {"daily_to_fuzzy": 0, "fuzzy_to_archive": 0}
    now = time.time()
    with _LOCK:
        ensure_layout()
        for path in list(DAILY_DIR.glob("*.txt")):
            try:
                if now - _mtime(path) > DAILY_TTL:
                    dst = _move_unique(path, FUZZY_DIR)
                    # 关键：进模糊时重置 mtime，让它在模糊库再活 30 天
                    os.utime(dst, None)
                    counts["daily_to_fuzzy"] += 1
                    log.info("日常 -> 模糊：%s", dst.name)
            except Exception as e:
                log.warning("日常转模糊失败（%s）：%s", path.name, e)

        for path in list(FUZZY_DIR.glob("*.txt")):
            try:
                if now - _mtime(path) > FUZZY_TTL:
                    dst = _move_unique(path, ARCHIVE_DIR)
                    counts["fuzzy_to_archive"] += 1
                    log.info("模糊 -> 归档：%s", dst.name)
            except Exception as e:
                log.warning("模糊转归档失败（%s）：%s", path.name, e)

        if counts["daily_to_fuzzy"] or counts["fuzzy_to_archive"]:
            # 文件移动后路径变了；索引直接按 TXT 重建，最稳
            try:
                rebuild_index()
            except Exception as e:
                log.warning("移动后重建索引失败：%s", e)
    return counts


def decay_loop(interval=3600):
    while True:
        try:
            decay_task()
        except Exception as e:
            log.warning("衰减任务异常（已忽略）：%s", e)
        time.sleep(max(60, int(interval)))


def start_decay_thread(interval=3600):
    t = threading.Thread(target=decay_loop, args=(interval,),
                         daemon=True, name="mem-decay")
    t.start()
    return t


# ---------------------------------------------------------------- 启动 / 统计
def init():
    # 启动时遍历所有 TXT，重建一遍 JSON（TXT 才是真源）
    for d in DIRS:
        d.mkdir(parents=True, exist_ok=True)
    rebuild_index()
    return stats()


def stats():
    out = {}
    for d in DIRS:
        try:
            out[d.name] = len(list(d.glob("*.txt")))
        except OSError:
            out[d.name] = 0
    out["index"] = str(INDEX_PATH)
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    print("home:", BOT_HOME)
    print("init:", init())
    p = save_memory("测试：下周三考高数，很重要，别忘", ["考试", "高数"], False)
    print("saved:", p)
    print("retrieve:", retrieve_memory("高数考试"))
    print("decay:", decay_task())
    print("stats:", stats())
