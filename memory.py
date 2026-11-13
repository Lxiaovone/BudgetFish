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

# ---------------------------- V6 双轨打分（2026-11-13 从真机 v6_memory_gate 对齐） ----------------------------
# 老版是「7 天转模糊、30 天归档」，靠文件 mtime 判生死：一句话说过一次就死，
# 说过十次也死，人和机器都看不出区别。V6 改成两条轨：
#   fast 短期热度（封顶 40，命中和曝光会涨，衰减快）
#   slow 长期沉淀（每次命中 +1，衰减慢，能扛住一段时间没人提）
# 规则：real = fast + slow；real<=0 判死（墓碑，进归档）；0<real<25 判模糊（注入时加不确定前缀）。
FAST_CAP = 40.0
INIT_FAST = 40.0
INIT_SLOW = 3.0
INIT_SLOW_EMOTION = 8.0
FUZZY_HIGH = 25.0
HIT_FAST = 10.0
HIT_SLOW = 1.0
FAST_DECAY_RATE = 0.8
FAST_SUB_FLOOR = 5.0
FAST_SUB_STEP = 2.0
SLOW_DECAY_STEP = 1.0
ZERO_EPS = 0.5
MAX_CATCHUP_DAYS = 14
MAX_KILL_RATIO = 0.30
SLOW_DEDUP_SEC = 1800.0
FUZZY_PREFIX = "【这是一段模糊的记忆，请用不确定的语气回答】"


def _today():
    return datetime.date.today().isoformat()


def score_of(item):
    """一条记忆的双轨分数。返回 (real, display, state, rank)。

    排序必须用 rank，不能用 real：slow 无上限，一条被反复提的旧记忆会永久霸榜。
    """
    item = item or {}
    fast = max(0.0, float(item.get("fast") or 0.0))
    slow = max(0.0, float(item.get("slow") or 0.0))
    real = fast + slow
    display = max(0.0, min(real, 100.0))
    if real <= 0.0:
        state = "dead"
    elif real < FUZZY_HIGH:
        state = "fuzzy"
    else:
        state = "normal"
    rank = 0.6 * min(slow, 100.0) / 100.0 + 0.4 * min(fast, FAST_CAP) / FAST_CAP
    return real, display, state, rank


def decay_step(fast, slow):
    """衰减一天。低段必须走减法，否则永远到不了 0，墓碑就是死代码。"""
    fast = max(0.0, float(fast))
    slow = max(0.0, float(slow))
    if fast > FAST_SUB_FLOOR:
        fast *= FAST_DECAY_RATE
    else:
        fast -= FAST_SUB_STEP
    if fast < ZERO_EPS:
        fast = 0.0
    slow = max(0.0, slow - SLOW_DECAY_STEP)
    if fast + slow < ZERO_EPS:
        fast = slow = 0.0
    return round(fast, 2), round(slow, 2)


def missed_days(last_iso, today=None, cap=MAX_CATCHUP_DAYS):
    """关机补算天数（封顶 14 天，避免出差回来全失忆）。"""
    if isinstance(today, str):
        try:
            today = datetime.date.fromisoformat(today[:10])
        except ValueError:
            today = datetime.date.today()
    today = today or datetime.date.today()
    if not last_iso:
        return 0
    try:
        last = datetime.date.fromisoformat(str(last_iso)[:10])
    except ValueError:
        return 0
    return max(0, min(cap, (today - last).days))

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
    """TXT 是真源；扫描可检索目录重建 v2 索引（标签 + 双轨分）。"""
    with _LOCK:
        tags = {}
        items = {}
        today = _today()
        for folder in (CORE_DIR, DAILY_DIR, FUZZY_DIR):
            tier = FOLDER_TIER.get(folder.name, "daily")
            for path in sorted(folder.glob("*.txt")):
                rel = _rel(path)
                if tier == "core":
                    fast, slow = FAST_CAP, 100.0      # 永久记忆：不参与衰减
                elif tier == "fuzzy":
                    fast, slow = 10.0, 5.0            # 老的模糊区文件：补一个偏低的分
                else:
                    fast, slow = INIT_FAST, INIT_SLOW
                items[rel] = {"fast": fast, "slow": slow, "hit_date": "",
                              "slow_date": "", "last_decay": today}
                for tag in _read_tags(path):
                    tags.setdefault(tag, [])
                    if rel not in tags[tag]:
                        tags[tag].append(rel)
        data = {
            "version": 2,
            "rebuilt_at": _now_iso(),
            "tags": tags,
            "items": items,
        }
        _atomic_write_json(INDEX_PATH, data)
        log.info("记忆索引已重建：%d 个标签 / %d 条记忆", len(tags), len(items))
        return data


def _read_index():
    """读 v2 索引；v1（只有 tags）或损坏 → 按 TXT 重建。"""
    if not INDEX_PATH.exists():
        return rebuild_index()
    try:
        with open(INDEX_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("索引不是对象")
        if data.get("version") != 2 or not isinstance(data.get("items"), dict):
            raise ValueError("旧版索引（v1），按 V6 重建")
        if not isinstance(data.get("tags"), dict):
            data["tags"] = {}
        return data
    except Exception as e:
        log.warning("tag_index.json 需要重建：%s", e)
        try:
            return rebuild_index()
        except Exception as e2:
            log.error("重建索引失败：%s", e2)
            return {"version": 2, "tags": {}, "items": {}}


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
    """一条记忆一个 TXT；绝不 append。返回文件路径。

    V6：新记忆快轨直接给满（INIT_FAST），慢轨只留一点；情绪强的慢轨起点更高（记得更久）。
    """
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

        try:
            data = _read_index()
            rel = _rel(path)
            if tier == "core":
                fast, slow = FAST_CAP, 100.0
            else:
                fast = INIT_FAST
                slow = INIT_SLOW_EMOTION if bool(is_emotion_high) else INIT_SLOW
            data.setdefault("items", {})[rel] = {
                "fast": fast, "slow": slow, "hit_date": "",
                "slow_date": "", "last_decay": _today(),
            }
            for tag in tag_list:
                arr = data.setdefault("tags", {}).setdefault(tag, [])
                if rel not in arr:
                    arr.append(rel)
            _atomic_write_json(INDEX_PATH, data)
        except Exception as e:
            log.warning("写索引失败（TXT 已落盘，稍后重建）：%s", e)
        log.info("记忆已保存：%s（fast=%s slow=%s）", path.name, INIT_FAST, INIT_SLOW)
        return str(path)


# ---------------------------------------------------------------- 读
def _ranked(entries):
    """按 (标签命中数, rank, 新旧) 排序。"""
    def key(entry):
        rel, weight, item = entry
        _real, _display, _state, rank = score_of(item)
        return (-weight, -rank, -_mtime(_abs(rel)))

    return sorted(entries, key=key)


def retrieve_memory(user_input):
    """标签召回 + 双轨排序；模糊记忆加不确定前缀，墓碑永不出现。"""
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
        items = data.get("items") or {}

        hits = {}
        for tag, rels in tags.items():
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
            for rel in rels:
                item = items.get(rel)
                if not item:
                    continue
                if score_of(item)[2] == "dead":      # 墓碑不进上下文
                    continue
                hits[rel] = hits.get(rel, 0) + 1

        if not hits:
            return ""

        entries = [(rel, w, items.get(rel) or {}) for rel, w in hits.items()]
        parts = []
        used = 0
        changed = False
        now = time.time()
        for rel, _w, item in _ranked(entries)[:2]:
            real, _display, state, _rank = score_of(item)
            try:
                path = _abs(rel)
                if not path.is_file():
                    continue
                with open(path, encoding="utf-8", errors="ignore") as f:
                    text = _strip_header(f.read())
                body = re.sub(r"\s+", " ", text).strip()[:MAX_FILE_CHARS]
                if not body:
                    continue
                prefix = FUZZY_PREFIX if state == "fuzzy" else "【记忆】"
                block = "%s %s" % (prefix, body)
                if used + len(block) > MAX_CONTEXT_CHARS:
                    block = block[:max(0, MAX_CONTEXT_CHARS - used)]
                if block:
                    parts.append(block)
                    used += len(block)
            except Exception as e:
                log.warning("读记忆失败（%s）：%s", rel, e)

            # 命中回血：快轨 +10（封顶），慢轨 30 分钟内只 +1
            if rel.startswith(CORE_DIR.name + "/"):
                continue
            item["fast"] = min(FAST_CAP, float(item.get("fast") or 0.0) + HIT_FAST)
            last_slow = 0.0
            if item.get("slow_date"):
                try:
                    last_slow = datetime.datetime.fromisoformat(item["slow_date"]).timestamp()
                except ValueError:
                    last_slow = 0.0
            if now - last_slow > SLOW_DEDUP_SEC:
                item["slow"] = float(item.get("slow") or 0.0) + HIT_SLOW
                item["slow_date"] = _now_iso()
            item["hit_date"] = _now_iso()
            changed = True

        if changed:
            try:
                _atomic_write_json(INDEX_PATH, data)
            except Exception as e:
                log.warning("回血写索引失败：%s", e)
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
    """每日衰减：双轨各降一天；归零的进归档（墓碑）；一次干掉太多就熔断。"""
    today = _today()
    counts = {"decayed": 0, "tombstoned": 0, "aborted": False}
    with _LOCK:
        ensure_layout()
        data = _read_index()
        items = data.get("items") or {}
        tags = data.get("tags") or {}
        if not items:
            return counts

        plans = []
        for rel, item in items.items():
            if rel.startswith(CORE_DIR.name + "/"):      # 永久记忆不衰减
                continue
            days = missed_days(item.get("last_decay"), today)
            if days <= 0:
                continue
            fast = float(item.get("fast") or 0.0)
            slow = float(item.get("slow") or 0.0)
            for _ in range(days):
                fast, slow = decay_step(fast, slow)
            plans.append((rel, fast, slow))

        kills = [pl for pl in plans if pl[1] + pl[2] <= 0.0]
        if plans and len(kills) > max(1, int(len(plans) * MAX_KILL_RATIO)):
            counts["aborted"] = True
            log.warning("衰减熔断：本次会归档 %d / %d 条（>30%%），已中止。"
                        "请先看看 last_decay 是不是被写坏了。", len(kills), len(plans))
            return counts

        for rel, fast, slow in plans:
            item = items[rel]
            item["fast"], item["slow"] = fast, slow
            item["last_decay"] = today
            counts["decayed"] += 1

        for rel, _fast, _slow in kills:
            path = _abs(rel)
            try:
                if path.exists():
                    _move_unique(path, ARCHIVE_DIR)
            except Exception as e:
                log.warning("归档失败（%s）：%s", rel, e)
                continue
            items.pop(rel, None)
            for tag in list(tags):
                if rel in tags[tag]:
                    tags[tag] = [x for x in tags[tag] if x != rel]
                    if not tags[tag]:
                        tags.pop(tag, None)
            counts["tombstoned"] += 1
            log.info("墓碑 -> 归档：%s", rel)

        data["tags"], data["items"] = tags, items
        data["updated"] = _now_iso()
        _atomic_write_json(INDEX_PATH, data)
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
    try:
        items = _read_index().get("items") or {}
        states = {"normal": 0, "fuzzy": 0, "dead": 0}
        for item in items.values():
            states[score_of(item)[2]] += 1
        out["alive"] = states["normal"] + states["fuzzy"]
        out["normal"] = states["normal"]
        out["fuzzy"] = states["fuzzy"]
    except Exception:
        pass
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
    item = _read_index()["items"].get(_rel(__import__("pathlib").Path(p)))
    print("scores:", item, "→ score_of:", score_of(item)[:3])
    print("decay:", decay_task())
    print("stats:", stats())
