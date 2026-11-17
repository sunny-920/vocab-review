"""從本機 Wiktionary 資料庫（data/wiktionary.db）查字源，給 AI 拆字根用。

每次只查這個字需要的幾筆（不到 0.01 秒）：
  1. 這個字的字源文字和結構化標記（例如 suffix: rely + -able）
  2. 每一塊的英文意思（rely、-able；拉丁字根 levare…）
  3. 來源字（拉丁文、希臘文…）再往上查一層，看它怎麼組成（relevare = re- + levare）
  4. 衍生字（給家族用）
查不到就回傳 None，AI 就不寫拆解（不讓它猜）。
"""
import json
import re
import sqlite3
import threading
import unicodedata

from . import config

DB_PATH = config.ROOT / "data" / "wiktionary.db"
_local = threading.local()

AFFIX_TEMPLATES = {"af", "affix", "suffix", "suf", "prefix", "pre", "confix", "con", "compound", "com", "surf"}
SOURCE_TEMPLATES = {"der", "inh", "bor", "lbor", "der+", "inh+", "bor+", "lbor+", "uder", "ubor", "slbor", "obor"}
CLASSICAL = ("la", "grc")  # 拆字根最有用的來源語言（la-lat、la-med… 也算）
LANG_NAMES = {
    "la": "拉丁文", "la-lat": "後期拉丁文", "la-med": "中世紀拉丁文", "la-new": "新拉丁文", "VL.": "通俗拉丁文",
    "grc": "古希臘文", "fro": "古法語", "frm": "中古法語", "xno": "盎格魯諾曼語", "fr": "法語",
    "enm": "中古英語", "ang": "古英語", "non": "古諾斯語", "gem-pro": "原始日耳曼語", "it": "義大利文",
    "es": "西班牙文", "de": "德文", "nl": "荷蘭文", "en": "英文",
}


def available() -> bool:
    return DB_PATH.exists()


def _con():
    con = getattr(_local, "con", None)
    if con is None:
        con = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True, check_same_thread=False)
        con.row_factory = sqlite3.Row
        _local.con = con
    return con


def norm_key(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower().strip()


def _rows(word: str, langs: tuple[str, ...]) -> list[sqlite3.Row]:
    q = ",".join("?" * len(langs))
    return _con().execute(
        f"SELECT * FROM entries WHERE key=? AND lang_code IN ({q}) ORDER BY id", (norm_key(word), *langs)
    ).fetchall()


_START = re.compile(r"\b(From|Borrowed|Learned borrowing|Semi-learned|Inherited|Back-formation|Blend|Clipping|"
                    r"Coined|Compound|Calque|Univerbation|Equivalent to|By surface analysis)\b")


def _clean_text(text: str) -> str:
    """字源文字前面常有「Etymology tree」那一串語言清單，從第一個 From / Borrowed… 開始取。"""
    t = re.sub(r"\s+", " ", text or "").strip()
    m = _START.search(t)
    if m:
        t = t[m.start():]
    elif t.startswith("Etymology tree"):
        return ""
    return t[:450]


def _args(t: dict) -> dict:
    return t.get("args") or {}


def _affix_parts(templates: list[dict]) -> list[str]:
    """結構化標記裡的組成：suffix(rely, able) → ['rely', '-able']"""
    for t in templates:
        name, a = t.get("name"), _args(t)
        if name in ("ety", "etymon"):  # 新式字源樹：… :afeq diction -ary
            vals = [a[k] for k in sorted((k for k in a if k.isdigit()), key=int)]
            for i, v in enumerate(vals):
                if v in (":af", ":afeq", ":surf", ":compound"):
                    parts = [p.split("<")[0] for p in vals[i + 1:] if p and not p.startswith(":")]
                    parts = [p.split(":", 1)[-1] for p in parts]
                    parts = [p for p in parts if p and p not in LANG_NAMES]  # 去掉 en 這種語言代碼
                    if len(parts) >= 2:
                        return parts
            continue
        if name not in AFFIX_TEMPLATES:
            continue
        nums = [a.get(str(i), "").strip() for i in range(2, 8)]
        nums = [n for n in nums if n]
        if name in ("suffix", "suf") and len(nums) >= 2:
            return [nums[0]] + ["-" + n.lstrip("-") for n in nums[1:]]
        if name in ("prefix", "pre") and len(nums) >= 2:
            return [nums[0].rstrip("-") + "-"] + nums[1:]
        if name in ("confix", "con") and len(nums) >= 2:
            return [nums[0].rstrip("-") + "-"] + nums[1:-1] + ["-" + nums[-1].lstrip("-")]
        if len(nums) >= 2:
            return nums
    return []


def _source(templates: list[dict]) -> dict | None:
    """來源字：優先拉丁文、希臘文（拆字根最有用）。"""
    found = []
    for t in templates:
        if t.get("name") not in SOURCE_TEMPLATES:
            continue
        a = _args(t)
        lang, w = a.get("2", ""), a.get("3", "")
        if not w or w.startswith("*") or not lang:
            continue
        gloss = a.get("t") or a.get("gloss") or a.get("5") or ""
        found.append({"lang": lang, "word": w, "gloss": gloss})
    for s in found:
        if s["lang"].split("-")[0] in CLASSICAL:
            return s
    return found[0] if found else None


_FORM_OF = re.compile(r"^(alternative|obsolete|archaic|dated|nonstandard|rare)?\s*(form|spelling|plural|"
                      r"simple past|past|present participle|third-person|misspelling|abbreviation|initialism)\b.*\bof\b", re.I)
_POS_ORDER = {"suffix": 0, "prefix": 0, "verb": 1, "noun": 2, "adj": 3, "adv": 4}


def gloss(word: str, lang: str = "en") -> str:
    """一個字（或字首、字尾）的英文意思，很短。跳過「…的複數」「Detected.」這種沒用的。"""
    langs = (lang,) if lang != "la" else ("la", "la-lat", "la-med", "la-new")
    rows = sorted(_rows(word, langs), key=lambda r: _POS_ORDER.get(r["pos"] or "", 9))
    for r in rows:
        for g in json.loads(r["glosses"] or "[]"):
            g = re.sub(r"\s+", " ", g).strip()
            if g and not _FORM_OF.match(g) and len(g) > 10:
                return g[:80]
    for r in rows:
        g = json.loads(r["glosses"] or "[]")
        if g:
            return g[0][:80]
    return ""


def _best_entry(word: str):
    rows = [r for r in _rows(word, ("en",)) if r["etymology_text"] or r["etymology_templates"] not in (None, "[]")]
    return rows[0] if rows else None


def lookup(word: str, lemma: str | None = None) -> dict | None:
    """回傳 {text, parts:[{part, gloss}], source:{lang, word, gloss, parts}, derived:[...]}；查不到 None。"""
    if not available() or not word:
        return None
    try:
        e = _best_entry(word) or (_best_entry(lemma) if lemma else None)
    except sqlite3.Error:
        return None
    if not e:
        return None
    templates = json.loads(e["etymology_templates"] or "[]")
    parts = [{"part": p, "gloss": gloss(p, "en")} for p in _affix_parts(templates)]
    src = _source(templates)
    if src:
        lang = src["lang"]
        src["lang_name"] = LANG_NAMES.get(lang, lang)
        src["gloss"] = src["gloss"] or gloss(src["word"], "la" if lang.startswith("la") else lang)
        # 來源字再往上查一層：relevare = re- + levare
        sl = (lang,) if not lang.startswith("la") else ("la", "la-lat", "la-med", "la-new")
        srows = _rows(src["word"], sl)
        sparts = []
        for r in srows:
            sparts = _affix_parts(json.loads(r["etymology_templates"] or "[]"))
            if sparts:
                break
        lg = "la" if lang.startswith("la") else lang
        src["parts"] = [{"part": p, "gloss": gloss(p, lg)} for p in sparts]
    derived = [d for d in json.loads(e["derived"] or "[]") if " " not in d and "-" not in d][:40]
    return {"word": e["word"], "text": _clean_text(e["etymology_text"]), "parts": parts,
            "source": src, "derived": derived}


def describe(info: dict) -> str:
    """整理成給 AI 看的幾行。"""
    lines = []
    if info.get("text"):
        lines.append(f"字源說明（英文）：{info['text']}")
    if info.get("parts"):
        lines.append("組成：" + " + ".join(f"{p['part']}（{p['gloss'] or '?'}）" for p in info["parts"]))
    s = info.get("source")
    if s:
        line = f"來源：{s['lang_name']} {s['word']}" + (f"（{s['gloss']}）" if s.get("gloss") else "")
        if s.get("parts"):
            line += "，由 " + " + ".join(f"{p['part']}（{p['gloss'] or '?'}）" for p in s["parts"]) + " 組成"
        lines.append(line)
    return "\n".join(lines)


def relations(word: str) -> dict:
    """Wiktionary 的同義字、反義字、相關字、衍生字（只取詞條本身列的，不含各個意思底下的雜項）。"""
    out = {"synonyms": [], "antonyms": [], "related": [], "derived": []}
    if not available() or not word:
        return out
    try:
        rows = _rows(word, ("en",))
    except sqlite3.Error:
        return out
    for r in rows:
        e = json.loads(r["raw"])
        for k in out:
            for x in e.get(k) or []:
                w = (x.get("word") or "").strip()
                if w and " " not in w and w.lower() != word.lower() and w not in out[k]:
                    out[k].append(w)
    return out
