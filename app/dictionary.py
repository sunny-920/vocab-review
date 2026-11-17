"""離線字典（ECDICT 精簡版）：查詢、原形偵測、字根、近義字辨析。

ECDICT 原文是簡體中文，查詢時用 OpenCC 轉成台灣繁體。
"""
import re
import sqlite3
import threading

from opencc import OpenCC

from . import config

_cc = OpenCC("s2twp")
_cc_lock = threading.Lock()

# ECDICT exchange 欄位的變化形代碼
FORM_NAMES = {
    "p": "過去式",
    "d": "過去分詞",
    "i": "現在分詞",
    "3": "第三人稱單數",
    "r": "比較級",
    "t": "最高級",
    "s": "複數",
}


def to_tw(text: str) -> str:
    if not text:
        return text
    with _cc_lock:
        out = _cc.convert(text)
    out = out.replace("臺", "台")  # 台灣日常用「台」（OpenCC 會轉成「臺」）
    # OpenCC 對已經是繁體的「演算法」會再轉一次，變成「演演算法」
    # 「運算」也會被轉成「運運算」（例如 operator 的「運算元」）
    out = out.replace("演演算", "演算").replace("運運算", "運算")
    # 其他 OpenCC 把已經是繁體的詞再轉一次造成的錯
    for bad, good in (("強呼叫", "強調用"), ("說明瞭", "說明了"), ("證明瞭", "證明了"), ("表明瞭", "表明了"),
                      ("例項", "實例")):
        out = out.replace(bad, good)
    return out


def available() -> bool:
    return config.DICT_PATH.exists()


def _connect():
    con = sqlite3.connect(f"file:{config.DICT_PATH.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _clean_phonetic(p: str) -> str:
    if not p:
        return ""
    return p.replace("ә", "ə").replace(":", "ː").replace("'", "ˈ").replace(",", "ˌ")


def _parse_exchange(ex: str) -> dict:
    out = {}
    for part in (ex or "").split("/"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k] = v
    return out


def _entry(word: str):
    if not available() or not word:
        return None
    con = _connect()
    try:
        rows = con.execute(
            "SELECT * FROM entries WHERE key=? ORDER BY frq=0, frq", (word.lower(),)
        ).fetchall()
    finally:
        con.close()
    if not rows:
        return None
    for r in rows:  # 大小寫完全相同的優先
        if r["word"] == word:
            return r
    return rows[0]


def lookup(word: str):
    r = _entry(word)
    if r is None:
        return None
    lines = [to_tw(line.strip()) for line in r["translation"].split("\n") if line.strip()]
    return {
        "word": r["word"],
        "phonetic": _clean_phonetic(r["phonetic"]),
        "translation": lines,
        "tag": r["tag"],
    }


def lemma_of(word: str):
    """如果 word 是變化形，回傳 {lemma, forms}；不是就回傳 None。"""
    r = _entry(word)
    if r is None:
        return None
    ex = _parse_exchange(r["exchange"])
    lemma = ex.get("0")
    if not lemma or lemma.lower() == word.lower():
        return None
    forms = [FORM_NAMES[c] for c in ex.get("1", "") if c in FORM_NAMES]
    return {"lemma": lemma, "forms": forms}


def roots_for(word: str) -> list[dict]:
    if not available():
        return []
    con = _connect()
    try:
        rows = con.execute(
            """SELECT r.root, r.meaning, r.class FROM root_words w
               JOIN roots r ON r.id = w.root_id WHERE w.word=? LIMIT 4""",
            (word.lower(),),
        ).fetchall()
    finally:
        con.close()
    return [{**dict(r), "root": re.sub(r"\d+$", "", r["root"])} for r in rows]  # serv2 → serv


def forms_of(word: str) -> list[str]:
    """變化形：過去式、分詞、複數、比較級…（例句填空用）"""
    r = _entry(word)
    if r is None:
        return []
    ex = _parse_exchange(r["exchange"])
    return [v for k, v in ex.items() if k in FORM_NAMES and v]


def resemble_for(word: str) -> list[dict]:
    if not available():
        return []
    con = _connect()
    try:
        rows = con.execute(
            """SELECT g.words, g.body FROM resemble_words w
               JOIN resemble g ON g.id = w.group_id WHERE w.word=? LIMIT 2""",
            (word.lower(),),
        ).fetchall()
    finally:
        con.close()
    return [{"words": r["words"], "body": to_tw(r["body"])} for r in rows]


_POS_RE = re.compile(r"^((?:[a-z]+\.\s*)+)\s*(.*)$")
_DOMAIN_RE = re.compile(r"^\[(.+?)\]\s*(.*)$")


def meanings_from_dict(word: str) -> list[dict]:
    """AI 失敗時，直接用字典解釋產生意思清單。"""
    info = lookup(word)
    if not info:
        return []
    out = []
    for line in info["translation"]:
        pos, domain, body = "", "", line
        m = _DOMAIN_RE.match(body)
        if m:
            domain, body = m.group(1), m.group(2)
            if domain in ("網路", "網絡"):  # ECDICT 的 [网络] 是「網路釋義」，不是領域
                if out:
                    continue
                domain = ""
        m = _POS_RE.match(body)
        if m:
            pos, body = m.group(1).strip(), m.group(2)
        terms = [t.strip() for t in re.split(r"[,，;；]", body) if t.strip()]
        if not terms:
            continue
        out.append({
            "pos": pos,
            "zh": "、".join(terms[:3]),
            "domain": "電腦" if domain == "計" else domain,
            "is_primary": not out,
            "source": "dict",
        })
    return out[:5]


_SUFFIXES = sorted([
    "ations", "ation", "itions", "ition", "tions", "tion", "sions", "sion", "ions", "ion",
    "ments", "ment", "ness", "ities", "ity", "ive", "able", "ible", "ance", "ence",
    "ers", "er", "ors", "or", "al", "ically", "ally", "ly", "ing", "ed", "ous", "ful", "less",
    "ize", "ise", "es", "s", "e",
], key=len, reverse=True)


def family_of(word: str, limit: int = 8) -> list[str]:
    """同一家族的常見字（字典裡開頭相同的衍生字），給 AI 寫「家族連結」當參考。"""
    if not available() or not word or " " in word.strip():
        return []
    w = word.lower().strip()
    stem = w
    for suf in _SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            stem = w[: -len(suf)]
            break
    stem = w[:max(len(stem), min(len(w) - 2, 6), 5)]  # 太短的字根會抓到不相關的字（reli → relieve、insta → install）
    lemma = lemma_of(word)
    con = _connect()
    try:
        rows = con.execute(
            """SELECT word, exchange FROM entries WHERE key LIKE ? AND frq>0 AND frq<25000
               ORDER BY frq LIMIT 40""",
            (stem.replace("%", "").replace("_", "") + "%",),
        ).fetchall()
    finally:
        con.close()
    out = []
    if lemma:
        out.append(lemma["lemma"])
    for r in rows:
        x = r["word"]
        if " " in x or "-" in x or x[:1].isupper() or "0:" in (r["exchange"] or ""):
            continue  # 片語、專有名詞、變化形（過去式、複數…）不要
        if x.lower() not in (o.lower() for o in out):
            out.append(x)
    return out[:limit]


def roots_for_family(word: str) -> list[dict]:
    """自己查不到字根時，借用同家族字的（evaluation → evaluate 的 e- + val）。"""
    got = roots_for(word)
    if got:
        return got
    for f in family_of(word):
        if f.lower() != word.lower():
            got = roots_for(f)
            if got:
                return [{**r, "via": f} for r in got]
    return []


def _edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _terms(word: str) -> set[str]:
    info = lookup(word)
    if not info:
        return set()
    out = set()
    for line in info["translation"][:3]:
        line = re.sub(r"^(\[[^\]]*\]\s*)?([a-z]+\.\s*)*", "", line)
        out |= {t.strip() for t in re.split(r"[,，;；]", line) if t.strip()}
    return out


def _same_meaning(a: str, b: str) -> bool:
    """拼法變體（judgment / judgement、color / colour）：只差多一個字母、意思也重疊。
    affect / effect 這種換字母的不算（是真的容易搞混）。"""
    if abs(len(a) - len(b)) != 1 or _edit_distance(a, b) != 1:
        return False
    return bool(_terms(a) & _terms(b))


def lookalikes(word: str, limit: int = 5) -> list[str]:
    """拼字很像、容易搞混的常見字（adapt/adopt、affect/effect、consistent/constant）。
    不含同一個字的變化形和衍生字。"""
    if not available() or not word or " " in word.strip() or len(word) < 4:
        return []
    w = word.lower().strip()
    lem = lemma_of(w)
    base = lem["lemma"].lower() if lem else w
    n = len(w)
    con = _connect()
    try:
        rows = con.execute(
            """SELECT word, exchange FROM entries
               WHERE (key LIKE ? OR key LIKE ?) AND length(key) BETWEEN ? AND ? AND frq>0 AND frq<20000
               ORDER BY frq LIMIT 3000""",
            (w[0] + "%", "_" + w[1:3] + "%", max(3, n - 3), n + 3),
        ).fetchall()
    finally:
        con.close()
    out = []
    maxd = 1 if n <= 5 else 2
    for r in rows:
        x = r["word"]
        xl = x.lower()
        if xl in (w, base) or " " in x or "-" in x or x[:1].isupper() or "0:" in (r["exchange"] or ""):
            continue
        b, xs = re.sub(r"(e|y)$", "", base), re.sub(r"(e|y)$", "", xl)
        if xl.startswith(b) or base.startswith(xs):
            continue  # 同一家族（predict / prediction、evaluate / evaluation）
        if _edit_distance(w, xl) <= maxd and not _same_meaning(w, xl):
            out.append(x)
        if len(out) >= limit:
            break
    return out


def is_common(word: str, max_rank: int = 30000) -> bool:
    """常見字（ECDICT 詞頻排名內），用來過濾 Wiktionary 衍生字裡的罕見字。"""
    r = _entry(word)
    return bool(r and r["frq"] and r["frq"] < max_rank)


_STOP_CHARS = set("的性地化者物人事之於與和而或可能使被得了是在有為一不")


def meaning_chars(word: str) -> set[str]:
    """字典中文意思裡的字（去掉「的、性、地…」這種沒意義的字），用來判斷兩個字意思近不近。"""
    out = set()
    for t in _terms(word):
        t = re.sub(r"\[[^\]]*\]|[（(].*?[)）]|[A-Za-z.]", "", t)
        out |= {c for c in t if "\u4e00" <= c <= "\u9fff" and c not in _STOP_CHARS}
    return out


def close_words(a: str, b: str) -> bool:
    """兩個字是不是真的容易搞混：拼字很像、開頭 4 個字母一樣、或字典意思有 2 個以上相同的中文字。
    例：consistent/constant（開頭）、individual/personal（個、體）；reliable/suitable 不算。"""
    a, b = a.lower(), b.lower()
    if a[:4] == b[:4] and len(a) >= 4 and len(b) >= 4:
        return True
    if _edit_distance(a, b) <= (1 if len(a) <= 5 else 2):
        return True
    return len(meaning_chars(a) & meaning_chars(b)) >= 2


_TECH_DOMAINS = {"資料庫", "程式設計", "機器學習", "網路", "資安", "硬體", "雲端", "電腦", "科技", "軟體", "人工智慧"}


def _chars_of(text: str) -> set[str]:
    text = re.sub(r"\[[^\]]*\]|[（(].*?[)）]|[A-Za-z.]", "", text)
    return {c for c in text if "\u4e00" <= c <= "\u9fff" and c not in _STOP_CHARS}


def domain_ok(word: str, zh: str, domain: str) -> bool:
    """AI 標的領域可不可信：
    - 字典裡有同一類領域標記（科技類看 [計]）的意思，而且跟這個意思有相同的字（table 的資料表 ↔ [計] 表格）
    - 或這個意思根本不是字典裡的一般意思（instance 的「物件」）
    「不變的」「足夠的」「採用」這種一般意思，就算句子在講機器學習，也不標。"""
    info = lookup(word)
    if not info or not domain:
        return bool(domain)
    mine = _chars_of(zh)
    tech = domain in _TECH_DOMAINS
    general = set()
    for line in info["translation"]:
        m = re.match(r"^\[([^\]]+)\]", line)
        if m and m.group(1) not in ("網路", "網絡"):
            if (m.group(1) == "計") == tech and mine & _chars_of(line):
                return True
        else:
            general |= _chars_of(line)
    return len(mine & general) < 2
