"""文章閱讀：排版（規則＋AI）、查字、標出資料庫裡的字、文章的單字表。

排版的原則：AI 只決定「每一行是標題、新段落、接上一段還是雜訊」，文字本身一律不經過 AI，
所以不會被改字或漏句。
"""
import html
import json
import re
import threading
import traceback

from . import ai, db, dictionary, srs, words

LAYOUT_BATCH = 50  # 一次給 AI 幾行
SPLIT_OVER = 700   # 一段超過幾個字元，就請 AI 看要不要再切段
SPLIT_CHUNK = 3500  # 一次給 AI 看多長（太長的段落分批）
MIN_PARA = 120     # 切出來的段落至少多長（太短就併回上一段，避免切得太碎）

_jobs: dict[int, dict] = {}  # article_id -> {"done": n, "total": n}
_jobs_lock = threading.Lock()


class ArticleError(Exception):
    pass


# ================= 清掉複製來的格式 =================
_HTML_TAGS = r"(?:b|i|u|s|em|strong|span|div|p|br|a|font|sup|sub|mark|small|code|li|ul|ol|h[1-6]|blockquote)"


def clean_inline(text: str) -> str:
    """文章內文只要純文字：拿掉粗體、斜體、刪除線、程式碼、連結等格式符號和 HTML 標籤（文字留著）。"""
    s = text
    s = re.sub(r"[\u200b-\u200d\u2060\ufeff\u00ad]", "", s)            # 看不見的字元、軟連字號
    s = re.sub(rf"<{_HTML_TAGS}\b[^>]*>|</{_HTML_TAGS}>", "", s, flags=re.I)
    if re.search(r"&(?:[a-z]+|#\d+|#x[0-9a-f]+);", s, re.I):
        s = html.unescape(s)
    s = s.replace("\u00a0", " ")
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)                          # 圖片
    s = re.sub(r"\[([^\]]+)\]\((?:https?://|/|#)[^)]*\)", r"\1", s)     # [文字](網址) → 文字
    s = re.sub(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1", r"\2", s)              # **粗體**、__粗體__
    s = re.sub(r"~~(?=\S)(.+?)(?<=\S)~~", r"\1", s)                     # ~~刪除線~~
    s = re.sub(r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])", r"\1", s)  # *斜體*
    s = re.sub(r"(?<![\w_])_(?=\S)([^_\n]+?)(?<=\S)_(?![\w_])", r"\1", s)    # _斜體_（snake_case 不動）
    s = re.sub(r"`([^`\n]+)`", r"\1", s)                                # `程式碼`
    return s


# ================= 排版 =================
_MD_HEAD = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$")
_MD_LIST = re.compile(r"^(?:[-*+•●▪])\s+(.*)$")


def _lines(raw: str) -> list[dict]:
    """原文 → 非空白行（記錄前面有沒有空行）。複製來的 Markdown 標題（## …）、條列（- …）、引用（> …）記下來當排版依據。"""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"<br\s*/?>|</p>|</div>|</li>|</h[1-6]>", "\n", text, flags=re.I)
    out, blank = [], False
    for line in text.split("\n"):
        s = re.sub(r"[ \t]+", " ", clean_inline(line)).strip()
        if not s or re.fullmatch(r"[-*_=]{3,}", s):  # 空行、分隔線
            blank = True
            continue
        item = {"text": s, "blank_before": blank}
        if m := _MD_HEAD.match(s):
            item.update(text=m.group(2), md="h", level=2 if len(m.group(1)) <= 2 else 3)
        elif m := _MD_LIST.match(s):
            item.update(text=m.group(1), md="li")
        elif s.startswith("> "):
            item.update(text=s[2:].strip(), md="q")
        if item["text"]:
            out.append(item)
        blank = False
    return out


def _join(a: str, b: str) -> str:
    """把斷行接回來；行尾的連字號：去掉後是真的字才去掉（con- + tinue），不然保留（well- + known）。"""
    if a.endswith("-") and b[:1].islower():
        m = re.search(r"([A-Za-z]+)-$", a)
        n = re.match(r"[A-Za-z]+", b)
        if m and n and dictionary.lookup(m.group(1) + n.group(0)):
            return a[:-1] + b
        return a + b
    return a + " " + b


def _is_heading(text: str) -> bool:
    return (len(text.split()) <= 12 and not re.search(r"[.!?,;:]$", text)
            and not text[:1].islower() and not text.endswith('"'))


def _rule_labels(lines: list[dict]) -> list[str]:
    """沒有 AI 時的判斷：h 標題、p 新段落、c 接上一段。"""
    if not lines:
        return []
    has_blank = any(l["blank_before"] for l in lines[1:])
    lens = sorted(len(l["text"]) for l in lines)
    median = lens[len(lens) // 2]
    labels = []
    for i, l in enumerate(lines):
        t = l["text"]
        if i == 0 or l["blank_before"]:
            labels.append("p")
        elif has_blank:
            labels.append("c")  # 有空行分段的文章：沒空行就是同一段
        elif median > 150:
            labels.append("p")  # 網頁複製：一行就是一段
        else:
            prev = lines[i - 1]["text"]
            ended = re.search(r"[.!?:\"”)]$", prev)
            labels.append("p" if ended and len(prev) < median * 0.8 else "c")
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        if labels[-1] == "p" and _is_heading(t) and (
                nxt is None or nxt["blank_before"] or not has_blank
                or (len(t.split()) <= 8 and nxt["text"][:1].isupper())):  # 短標題，下一行大寫開頭的新句子
            labels[-1] = "h"
    return _md_labels(lines, labels)


def _md_labels(lines: list[dict], labels: list[str]) -> list[str]:
    """原文用 Markdown 標好的標題、條列、引用，照原文的（AI、規則都不能改）。"""
    return [l.get("md") or lab for l, lab in zip(lines, labels)]


def build_body(lines: list[dict], labels: list[str]) -> list[dict]:
    blocks: list[dict] = []
    for l, lab in zip(lines, labels):
        t = l["text"]
        if lab == "c" and blocks and blocks[-1]["t"] == "h" and (not _is_heading(t) or re.search(r"[.!?]\s", t)):
            blocks.append({"t": "p", "text": t})  # 標題後面接的是內文，不是標題的後半
        elif lab == "c" and blocks and blocks[-1]["t"] in ("p", "h", "li", "q"):
            blocks[-1]["text"] = _join(blocks[-1]["text"], t)
        elif lab in ("x", "li", "q"):
            blocks.append({"t": lab, "text": t})
        elif lab == "h":
            blocks.append({"t": "h", "text": t, **({"l": l["level"]} if l.get("level") else {})})
        else:
            blocks.append({"t": "p", "text": t})
    return blocks


def rule_layout(raw: str) -> list[dict]:
    lines = _lines(raw)
    return build_body(lines, _rule_labels(lines))


def _keep_break(lines: list[dict], i: int, lab: str) -> bool:
    """原文本來就分開的段落，AI 不可以併成一段（只能改成標題、雜訊）。
    - 前面有空行
    - 上一行是完整的一句話結尾，而且這行本身就是一整段（很長，網頁複製常見）"""
    if lab != "c" or i == 0:
        return False
    if lines[i]["blank_before"]:
        return True
    prev = lines[i - 1]["text"]
    return bool(re.search(r"[.!?:\"”)]$", prev)) and len(prev) > 150 and lines[i]["text"][:1].isupper()


# ---- 太長的段落：AI 找分段點和藏在裡面的小標題 ----
# AI 只回答「新段落從哪幾個字開始」「標題是哪幾個字」，程式到原文裡找到再切；找不到就不切，原文一個字都不會變。
_QMAP = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-"})
_SENT_END = re.compile(r"[.!?:][\"”’')\]]*$")


def _chunks(text: str, size: int) -> list[tuple[int, str]]:
    """切成每塊不超過 size 的片段，只在句子結尾切。回傳 [(在原文的位置, 片段)]。"""
    out, start = [], 0
    while len(text) - start > size:
        cut = None
        for m in re.finditer(r"[.!?][\"”’')\]]*\s+(?=[A-Z\"“])", text[start:start + size]):
            cut = start + m.end()
        if not cut or cut <= start:
            cut = start + size
        out.append((start, text[start:cut]))
        start = cut
    out.append((start, text[start:]))
    return out


def _find(norm: str, words: str, frm: int) -> int:
    """在（正規化過的）原文裡找 AI 抄的那幾個字，要在字的開頭；找不到回傳 -1。"""
    w = " ".join(words.split()).translate(_QMAP).lower().strip()
    if len(w) < 3:
        return -1
    i = norm.find(w, frm)
    while i >= 0 and i > 0 and norm[i - 1].isalnum():
        i = norm.find(w, i + 1)
    return i


def split_long(text: str) -> list[dict]:
    norm = text.translate(_QMAP).lower()  # 一個字元對一個字元，位置不變
    cuts = []  # (位置, 'p'|'h', 標題結尾)
    for off, chunk in _chunks(text, SPLIT_CHUNK):
        if off > 0:
            cuts.append((off, "p", off))  # 分批的地方先當成分段（後面太短會併回去）
        try:
            items = ai.split_points(chunk)
        except ai.AIError:
            continue
        pos = off
        for it in items:
            i = _find(norm, it["first_words"], pos)
            if i < 0 or i >= off + len(chunk):
                continue
            before = text[:i].rstrip()
            if i > 0 and not _SENT_END.search(before):
                continue  # 只能在句子結尾後面切
            if it["type"] == "h":
                head = " ".join(it["first_words"].split())
                end = i + len(head)
                ht = text[i:end].strip()
                after = text[end:].lstrip()
                # 真的小標題後面接的是「新的一句話」（大寫開頭）；接小寫、逗號的是句子的前半，不是標題
                if (len(ht.split()) > 12 or _SENT_END.search(ht) or not after
                        or not re.match(r"[A-Z\"“‘']", after) or ht.endswith(",")):
                    continue
                cuts.append((i, "h", end))
                pos = end
            else:
                cuts.append((i, "p", i))
                pos = i + 1
    blocks, cur = [], 0
    for i, kind, end in sorted(set(cuts)):
        if i < cur:
            continue
        seg = text[cur:i].strip()
        if seg:
            blocks.append({"t": "p", "text": seg})
        if kind == "h":
            blocks.append({"t": "h", "text": text[i:end].strip(), "l": 3})
            cur = end
        else:
            cur = i
    tail = text[cur:].strip()
    if tail:
        blocks.append({"t": "p", "text": tail})
    # 太短的段落併回上一段（標題後面的第一段不併）
    merged = []
    for b in blocks:
        if b["t"] == "p" and merged and merged[-1]["t"] == "p" and (len(b["text"]) < MIN_PARA or len(merged[-1]["text"]) < MIN_PARA):
            merged[-1]["text"] += " " + b["text"]
        else:
            merged.append(b)
    return merged or [{"t": "p", "text": text}]


def _batches(n: int, size: int) -> list[tuple[int, int]]:
    """把 n 行切成每批最多 size 行；最後一批太小（少於 10 行）就併進前一批——
    只給 AI 一兩行時它常常亂回（實際發生過：101 行的文章，最後一批只有 1 行，整篇排版失敗）。"""
    out = [(i, min(i + size, n)) for i in range(0, n, size)]
    if len(out) > 1 and out[-1][1] - out[-1][0] < 10:
        out[-2] = (out[-2][0], out[-1][1])
        out.pop()
    return out


def _ai_layout(aid: int, raw: str) -> list[dict]:
    lines = _lines(raw)
    labels = _rule_labels(lines)  # AI 漏掉的行用規則補
    with _jobs_lock:
        _jobs[aid] = {"done": 0, "total": len(lines)}
    failed = 0
    for start, end in _batches(len(lines), LAYOUT_BATCH):
        chunk = lines[start:end]
        rows = [{"n": start + i + 1, "text": l["text"], "blank_before": l["blank_before"],
                 "prev_end": (lines[start + i - 1]["text"][-40:] if start + i > 0 else "")}
                for i, l in enumerate(chunk)]
        got = {}
        for attempt in range(2):  # AI 偶爾回傳壞掉的格式：再試一次
            try:
                got = ai.layout_labels(rows)
                break
            except ai.AIError:
                if attempt == 1:
                    failed += 1  # 還是失敗：這一批就用規則排版，不要整篇放棄
        for n, lab in got.items():
            if start < n <= end and not _keep_break(lines, n - 1, lab):
                labels[n - 1] = lab
        with _jobs_lock:
            _jobs[aid]["done"] = end
    # 小寫開頭、前面沒空行的行幾乎都是句子的後半，AI 說是新段落也接回上一段（「in her life, she hoped…」）
    for i in range(1, len(lines)):
        if labels[i] == "p" and not lines[i]["blank_before"] and lines[i]["text"][:1].islower():
            labels[i] = "c"
    if failed and failed == len(_batches(len(lines), LAYOUT_BATCH)):
        raise ai.AIError("AI 排版失敗（每一批都無法解析），目前用規則排版")
    if labels:
        labels[0] = labels[0] if labels[0] in ("h", "li", "q", "x") else "p"  # 第一行不能是「接上一段」
    labels = _md_labels(lines, labels)
    body = build_body(lines, labels)
    # 一段太長（複製時換行不見了）→ 請 AI 找出該分段、藏在裡面的小標題的地方
    out = []
    long_ids = [i for i, b in enumerate(body) if b["t"] == "p" and len(b["text"]) > SPLIT_OVER]
    with _jobs_lock:
        if aid in _jobs:
            _jobs[aid] = {"done": 0, "total": len(long_ids), "phase": "split"}
    for i, b in enumerate(body):
        if i in long_ids:
            out.extend(split_long(b["text"]))
            with _jobs_lock:
                if aid in _jobs:
                    _jobs[aid]["done"] += 1
        else:
            out.append(b)
    return out


def start_layout(aid: int) -> None:
    def run():
        try:
            with db.tx() as con:
                r = con.execute("SELECT raw_text FROM articles WHERE id=?", (aid,)).fetchone()
            if not r:
                return
            body = _ai_layout(aid, r["raw_text"])
            with db.tx() as con:
                con.execute("UPDATE articles SET body_ai=?, layout_state='ready' WHERE id=? AND layout_state='pending'",
                            (json.dumps(body, ensure_ascii=False), aid))
        except Exception as e:
            if not isinstance(e, ai.AIError):
                traceback.print_exc()
            with db.tx() as con:
                con.execute("UPDATE articles SET layout_state='rule', layout_error=? WHERE id=?", (str(e)[:300], aid))
        finally:
            with _jobs_lock:
                _jobs.pop(aid, None)
    threading.Thread(target=run, name=f"layout-{aid}", daemon=True).start()


def resume_jobs() -> None:
    with db.tx() as con:
        ids = [r["id"] for r in con.execute("SELECT id FROM articles WHERE layout_state='pending'")]
    for aid in ids:
        start_layout(aid)


# ================= 文章 =================
def create(con, title: str, source: str, raw: str) -> int:
    raw = raw.strip()
    if not raw:
        raise ArticleError("文章內容是空的")
    title = title.strip() or (_lines(raw)[0]["text"][:60])
    if con.execute("SELECT 1 FROM articles WHERE title=?", (title,)).fetchone():
        raise ArticleError(f"已經有一篇叫「{title}」的文章，請換個標題")
    return con.execute(
        "INSERT INTO articles(title,source,raw_text,body,layout_state) VALUES (?,?,?,?,'pending')",
        (title, source.strip(), raw, json.dumps(rule_layout(raw), ensure_ascii=False)),
    ).lastrowid


def summary_list(con) -> list[dict]:
    out = []
    for r in con.execute("SELECT * FROM articles ORDER BY COALESCE(opened_at, created_at) DESC"):
        n = con.execute("SELECT COUNT(*) FROM article_words WHERE article_id=?", (r["id"],)).fetchone()[0]
        np = con.execute("SELECT COUNT(*) FROM article_phrases WHERE article_id=?", (r["id"],)).fetchone()[0]
        out.append({"id": r["id"], "title": r["title"], "source": r["source"], "created_at": r["created_at"],
                    "opened_at": r["opened_at"], "words": n, "phrases": np, "chars": len(r["raw_text"]),
                    "has_note": bool(r["note"].strip())})
    return out


# ================= 片語與文法（手填） =================
def _phrase_row(r) -> dict:
    return {"id": r["id"], "text": r["text"], "zh": r["zh"], "note": r["note"], "sentence": r["sentence"],
            "created_at": r["created_at"], "forms": _phrase_forms(r["text"]), "word_forms": _word_forms(r["text"])}


def _word_forms(text: str) -> dict:
    """片語裡每個字的變化形（took、taken → take），前端比對文章時用。"""
    out = {}
    for w in re.findall(r"[A-Za-z]+", text)[:10]:
        lw = w.lower()
        if lw not in out and len(lw) > 2:
            out[lw] = sorted({f.lower() for f in dictionary.forms_of(lw)})
    return out


def _phrase_forms(text: str) -> list[str]:
    """片語的變化形（第一個字換成過去式、ing…），文章裡寫 arrived in 也能對到 arrive in。"""
    words_ = text.split()
    if not words_ or not re.fullmatch(r"[A-Za-z]+", words_[0]):
        return [text]
    rest = " ".join(words_[1:])
    out = {text}
    for f in dictionary.forms_of(words_[0].lower()):
        out.add((f + " " + rest).strip())
    return sorted(out)


def phrases(con, aid: int) -> list[dict]:
    return [_phrase_row(r) for r in con.execute(
        "SELECT * FROM article_phrases WHERE article_id=? ORDER BY id", (aid,))]


def all_phrases(con) -> list[dict]:
    """所有文章的片語與文法（集中看的那一頁），新的在前面。"""
    out = []
    for r in con.execute(
            "SELECT p.*, a.title FROM article_phrases p JOIN articles a ON a.id=p.article_id ORDER BY p.id DESC"):
        out.append({**_phrase_row(r), "article_id": r["article_id"], "article_title": r["title"]})
    return out


def _clean_phrase(text: str, zh: str, note: str, sentence: str) -> tuple[str, str, str, str]:
    text = " ".join((text or "").split())
    if not text:
        raise ArticleError("片語或文法不能是空的")
    if len(text) > 200:
        raise ArticleError("片語或文法太長了（最多 200 字）")
    return (text, " ".join((zh or "").split())[:300], (note or "").strip()[:2000],
            " ".join((sentence or "").split())[:1000])


def add_phrase(con, aid: int, text: str, zh: str, note: str, sentence: str) -> dict:
    if not con.execute("SELECT 1 FROM articles WHERE id=?", (aid,)).fetchone():
        raise ArticleError("找不到這篇文章")
    text, zh, note, sentence = _clean_phrase(text, zh, note, sentence)
    pid = con.execute("INSERT INTO article_phrases(article_id,text,zh,note,sentence) VALUES (?,?,?,?,?)",
                      (aid, text, zh, note, sentence)).lastrowid
    return _phrase_row(con.execute("SELECT * FROM article_phrases WHERE id=?", (pid,)).fetchone())


def update_phrase(con, pid: int, text: str, zh: str, note: str, sentence: str) -> dict:
    if not con.execute("SELECT 1 FROM article_phrases WHERE id=?", (pid,)).fetchone():
        raise ArticleError("找不到這筆片語")
    text, zh, note, sentence = _clean_phrase(text, zh, note, sentence)
    con.execute("UPDATE article_phrases SET text=?, zh=?, note=?, sentence=? WHERE id=?", (text, zh, note, sentence, pid))
    return _phrase_row(con.execute("SELECT * FROM article_phrases WHERE id=?", (pid,)).fetchone())


def delete_phrase(con, pid: int) -> None:
    con.execute("DELETE FROM article_phrases WHERE id=?", (pid,))


def article_words(con, aid: int) -> list[dict]:
    out = []
    for r in con.execute("SELECT * FROM article_words WHERE article_id=? ORDER BY id", (aid,)):
        w = words.find(con, r["lemma"])
        st = None
        if w:
            full = con.execute("SELECT * FROM words WHERE id=?", (w["id"],)).fetchone()
            st = {"id": w["id"], "status": full["status"], "light": srs.light(full) if full["status"] == "active" else None}
        local = bool(r["local"]) and not w  # 後來加進單字庫的，就不再是灰色
        forms = sorted({r["lemma"].lower(), r["surface"].lower(), *(f.lower() for f in dictionary.forms_of(r["lemma"]))} - {""}) if local else []
        out.append({"id": r["id"], "lemma": r["lemma"], "surface": r["surface"], "sentence": r["sentence"],
                    "meaning": r["meaning"], "note": r["note"], "word": st, "local": local, "forms": forms})
    return out


def load(con, aid: int, touch: bool = False) -> dict:
    r = con.execute("SELECT * FROM articles WHERE id=?", (aid,)).fetchone()
    if not r:
        raise ArticleError("找不到這篇文章")
    if touch:
        con.execute("UPDATE articles SET opened_at=datetime('now','localtime') WHERE id=?", (aid,))
    with _jobs_lock:
        job = dict(_jobs[aid]) if aid in _jobs else None
    return {
        "id": r["id"], "title": r["title"], "source": r["source"], "note": r["note"],
        "body": json.loads(r["body"]), "layout_state": r["layout_state"], "layout_job": job,
        "layout_error": r["layout_error"], "created_at": r["created_at"],
        "words": article_words(con, aid), "phrases": phrases(con, aid), "read_pi": r["read_pi"],
    }


def apply_ai_layout(con, aid: int) -> None:
    r = con.execute("SELECT body_ai FROM articles WHERE id=? AND layout_state='ready'", (aid,)).fetchone()
    if not r:
        raise ArticleError("AI 排版還沒好")
    con.execute("UPDATE articles SET body=?, layout_state='ai' WHERE id=?", (r["body_ai"], aid))


def body_from_markdown(md: str) -> list[dict]:
    """手動編輯的排版（Markdown）→ 文章內容。只認整段的格式：## 大標、### 小標、- 條列、> 引用、~ 雜訊；
    空一行是新的一段；段落裡的粗體、斜體等符號自動拿掉。"""
    blocks: list[dict] = []
    para: list[str] = []

    def flush():
        if para:
            blocks.append({"t": "p", "text": " ".join(para)})
            para.clear()

    for raw in (md or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = re.sub(r"[ \t]+", " ", clean_inline(raw)).strip()
        if not line or re.fullmatch(r"[-*_=]{3,}", line):
            flush()
            continue
        if m := _MD_HEAD.match(line):
            flush()
            if m.group(2):
                blocks.append({"t": "h", "text": m.group(2), "l": 2 if len(m.group(1)) <= 2 else 3})
        elif m := _MD_LIST.match(line):
            flush()
            blocks.append({"t": "li", "text": m.group(1)})
        elif line.startswith(">"):
            flush()
            if line[1:].strip():
                blocks.append({"t": "q", "text": line[1:].strip()})
        elif line.startswith("~"):
            flush()
            if line[1:].strip():
                blocks.append({"t": "x", "text": line[1:].strip()})
        else:
            para.append(line)
    flush()
    if not blocks:
        raise ArticleError("文章內容是空的")
    return blocks


def set_body(con, aid: int, md: str) -> None:
    """存手動排版；之後 AI 排版不會自動蓋過去（要你按「重新 AI 排版」再按「套用」才會換）。"""
    if not con.execute("SELECT 1 FROM articles WHERE id=?", (aid,)).fetchone():
        raise ArticleError("找不到這篇文章")
    body = body_from_markdown(md)
    con.execute("UPDATE articles SET body=?, body_ai='', layout_state='manual', layout_error=NULL, "
                "updated_at=datetime('now','localtime') WHERE id=?", (json.dumps(body, ensure_ascii=False), aid))


def set_read_pos(con, aid: int, pi: int) -> None:
    """記住讀到第幾段（不改 updated_at）。"""
    con.execute("UPDATE articles SET read_pi=? WHERE id=?", (max(0, int(pi)), aid))


def update(con, aid: int, title: str | None, source: str | None, note: str | None) -> None:
    r = con.execute("SELECT title FROM articles WHERE id=?", (aid,)).fetchone()
    if not r:
        raise ArticleError("找不到這篇文章")
    if title is not None:
        title = title.strip()
        if not title:
            raise ArticleError("標題不能是空的")
        if title != r["title"]:
            if con.execute("SELECT 1 FROM articles WHERE title=? AND id<>?", (title, aid)).fetchone():
                raise ArticleError(f"已經有一篇叫「{title}」的文章")
            # 從這篇存的例句，出處跟著改（自由複習的「來源」篩選才找得到）
            con.execute("UPDATE examples SET source_title=? WHERE source='context' AND source_title=?", (title, r["title"]))
            con.execute("UPDATE articles SET title=? WHERE id=?", (title, aid))
    if source is not None:
        con.execute("UPDATE articles SET source=? WHERE id=?", (source.strip(), aid))
    if note is not None:
        con.execute("UPDATE articles SET note=? WHERE id=?", (note, aid))
    con.execute("UPDATE articles SET updated_at=datetime('now','localtime') WHERE id=?", (aid,))


def delete(con, aid: int) -> None:
    con.execute("DELETE FROM article_words WHERE article_id=?", (aid,))
    con.execute("DELETE FROM article_phrases WHERE article_id=?", (aid,))
    con.execute("DELETE FROM articles WHERE id=?", (aid,))


# ================= 查字 =================
def _norm_sel(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().strip(".,;:!?\"'“”‘’()[]{}")).strip()


def quick_lookup(con, text: str) -> dict:
    """選取後馬上顯示：字典、原形、資料庫裡有沒有。"""
    sel = _norm_sel(text)
    if not sel:
        raise ArticleError("沒有選到字")
    lem = dictionary.lemma_of(sel) if " " not in sel else None
    if not lem and sel[:1].isupper() and " " not in sel:
        lem2 = dictionary.lemma_of(sel.lower())
        lem = lem2 or ({"lemma": sel.lower(), "forms": []} if dictionary.lookup(sel.lower()) and not dictionary.lookup(sel) else None)
    lemma = lem["lemma"] if lem else sel
    info = dictionary.lookup(lemma) or dictionary.lookup(sel)
    return {
        "selected": sel,
        "lemma": lemma,
        "forms": lem["forms"] if lem else [],
        "dict": info,
        "existing": _existing(con, lemma) or _existing(con, sel),
    }


def _existing(con, word: str):
    w = words.find(con, word)
    if not w:
        return None
    r = con.execute("SELECT * FROM words WHERE id=?", (w["id"],)).fetchone()
    return {"id": r["id"], "word": r["word"], "status": r["status"],
            "light": srs.light(r) if r["status"] == "active" else None}


def _short_meaning(text: str) -> str:
    terms = [re.sub(r"^(指|表示|意思是|是)", "", t).strip(" 。.") for t in re.split(r"[、，,;；/]", text or "")]
    terms = [t for t in terms if t and len(t) <= 8]
    return "、".join(dict.fromkeys(terms[:2]))


def _dict_first(info) -> str:
    if not info or not info["translation"]:
        return ""
    line = re.sub(r"^(\[[^\]]*\]\s*)?([a-z]+\.\s*)+", "", info["translation"][0])
    return _short_meaning(line)


def explain(con, text: str, sentence: str, paragraph: str) -> dict:
    q = quick_lookup(con, text)
    res = ai.explain_in_context(q["selected"], q["lemma"], sentence, paragraph,
                                q["dict"]["translation"] if q["dict"] else [])
    # 型態以字典為準（AI 常把過去式說成原形）
    if q["forms"] and q["selected"].lower() != q["lemma"].lower() and (not res["form"] or "原形" in res["form"]):
        res["form"] = "、".join(q["forms"])
    # 意思要像單字卡：最多 2 個短說法；AI 寫成句子就改用字典的第一個意思
    res["meaning"] = _short_meaning(res["meaning"]) or _dict_first(q["dict"])
    res["phrase_meaning"] = _short_meaning(res.get("phrase_meaning", ""))
    if len(res.get("note", "")) > 40:
        res["note"] = ""
    lemma = res["lemma"] or q["lemma"]
    res["existing"] = _existing(con, lemma)
    if res.get("phrase"):
        res["phrase_existing"] = _existing(con, res["phrase"])
    # 單字庫裡已經有的字：這句的意思是學過的哪一個，還是新的意思
    ex = res["existing"]
    res["known_meanings"], res["match"] = [], None
    if ex and ex.get("status") == "active" and res["meaning"]:
        ms = [dict(r) for r in con.execute(
            "SELECT pos, zh FROM meanings WHERE word_id=? ORDER BY sort, id", (ex["id"],))]
        res["known_meanings"] = ms
        res["match"] = _match_meaning(ex["word"], sentence, res["meaning"], ms)
    return res


def _match_meaning(word: str, sentence: str, meaning: str, ms: list[dict]) -> int:
    """先看中文字有沒有重疊（便宜）；都沒重疊再問 AI（說法不同但意思一樣，例如最後／終於）。"""
    if not ms:
        return -1
    ctx = {c for c in meaning if "一" <= c <= "鿿"}
    terms = [t for t in re.split(r"[、，,；;]", meaning) if t.strip()]
    for i, m in enumerate(ms):
        mt = [t for t in re.split(r"[、，,；;]", m["zh"]) if t.strip()]
        if any(a.strip() == b.strip() for a in terms for b in mt):
            return i
        if len(ctx & {c for c in m["zh"] if "一" <= c <= "鿿"}) >= 2:
            return i
    try:
        return ai.match_meaning(word, sentence, meaning, ms)
    except ai.AIError:
        return -1


def add_meaning(con, aid: int, wid: int, pos: str, zh: str, surface: str, sentence: str) -> dict:
    """把「在這句的意思」加到單字庫裡的字（不設成主要意思），這句存成原文例句，記在這篇的單字表。"""
    w = con.execute("SELECT word, status FROM words WHERE id=?", (wid,)).fetchone()
    if not w or w["status"] != "active":
        raise ArticleError("找不到這個單字")
    zh = (zh or "").strip()
    if not zh:
        raise ArticleError("意思是空的")
    if not con.execute("SELECT 1 FROM meanings WHERE word_id=? AND zh=?", (wid, zh)).fetchone():
        n = con.execute("SELECT COALESCE(MAX(sort), -1) + 1 FROM meanings WHERE word_id=?", (wid,)).fetchone()[0]
        con.execute("INSERT INTO meanings(word_id, pos, zh, domain, is_primary, source, sort) VALUES (?,?,?,?,0,'user',?)",
                    (wid, (pos or "").strip(), zh, "", n))
    res = add_word(con, aid, w["word"], surface, sentence, zh)
    con.execute("UPDATE article_words SET meaning=? WHERE article_id=? AND lemma=?", (zh, aid, w["word"]))
    return res


def add_word(con, aid: int, lemma: str, surface: str, sentence: str, meaning: str) -> dict:
    """從文章加入生字：新字送 AI 整理；學過的字只加例句（不算重新輸入）。都會記在這篇的單字表。"""
    a = con.execute("SELECT title FROM articles WHERE id=?", (aid,)).fetchone()
    if not a:
        raise ArticleError("找不到這篇文章")
    lemma = words.norm_word(lemma)
    if not lemma:
        raise ArticleError("單字是空的")
    sentence = re.sub(r"\s+", " ", sentence or "").strip()
    meaning = (meaning or "").strip()
    w = words.find(con, lemma)
    action = "queued"
    wid = None
    if w:
        wid = w["id"]
        lemma = w["word"]
        action = "existing"
        if sentence and not con.execute("SELECT 1 FROM examples WHERE word_id=? AND en=?", (wid, sentence)).fetchone():
            con.execute("INSERT INTO examples(word_id,en,source,source_title,sort) VALUES (?,?,'context',?,-1)",
                        (wid, sentence, a["title"]))
    else:
        res = words.add_batch(con, a["title"], [{"word": lemma, "zh": meaning, "contexts": [sentence] if sentence else []}])
        wid = res[0]["id"]
    con.execute(
        """INSERT INTO article_words(article_id,lemma,surface,sentence,meaning) VALUES (?,?,?,?,?)
           ON CONFLICT(article_id,lemma) DO UPDATE SET
             sentence=CASE WHEN article_words.sentence='' THEN excluded.sentence ELSE article_words.sentence END,
             meaning=CASE WHEN article_words.meaning='' THEN excluded.meaning ELSE article_words.meaning END,
             local=0""",
        (aid, lemma, surface.strip(), sentence, meaning),
    )
    return {"action": action, "id": wid, "word": lemma}


def _base_form(text: str) -> str:
    """改成原形：arrived → arrive、termites → termite；兩個字以上的：bush pigs → bush pig（最後一個字的複數）、
    took off → take off（第一個字的動詞變化）。字典查不到就照原樣。"""
    parts = (text or "").split()
    if not parts:
        return ""
    if len(parts) == 1:
        lo = dictionary.lemma_of(parts[0])
        return lo["lemma"] if lo else parts[0]
    last = dictionary.lemma_of(parts[-1])
    if last and "複數" in last["forms"]:
        return " ".join(parts[:-1] + [last["lemma"]])
    first = dictionary.lemma_of(parts[0])
    if first and set(first["forms"]) & {"過去式", "過去分詞", "現在分詞", "第三人稱單數"}:
        return " ".join([first["lemma"]] + parts[1:])
    return text


def add_local_word(con, aid: int, lemma: str, surface: str, sentence: str, meaning: str) -> dict:
    """只記在這篇文章（灰色，不進單字庫）：專有名詞、很少用到的字，例如 binoculars、bush pig。"""
    if not con.execute("SELECT 1 FROM articles WHERE id=?", (aid,)).fetchone():
        raise ArticleError("找不到這篇文章")
    lemma = _base_form(words.norm_word(lemma))
    if not lemma:
        raise ArticleError("單字是空的")
    if words.find(con, lemma):
        raise ArticleError(f"「{lemma}」已經在單字庫裡了")
    sentence = re.sub(r"\s+", " ", sentence or "").strip()
    con.execute(
        """INSERT INTO article_words(article_id,lemma,surface,sentence,meaning,local) VALUES (?,?,?,?,?,1)
           ON CONFLICT(article_id,lemma) DO UPDATE SET local=1,
             sentence=CASE WHEN article_words.sentence='' THEN excluded.sentence ELSE article_words.sentence END,
             meaning=CASE WHEN excluded.meaning<>'' THEN excluded.meaning ELSE article_words.meaning END""",
        (aid, lemma, (surface or "").strip(), sentence, (meaning or "").strip()),
    )
    return {"word": lemma}


def set_word_meaning(con, aid: int, awid: int, meaning: str) -> None:
    con.execute("UPDATE article_words SET meaning=? WHERE id=? AND article_id=?", ((meaning or "").strip()[:300], awid, aid))


def set_word_note(con, aid: int, awid: int, note: str) -> None:
    con.execute("UPDATE article_words SET note=? WHERE id=? AND article_id=?", (note, awid, aid))


def remove_word(con, aid: int, awid: int) -> None:
    """只從這篇的單字表拿掉，單字本身不刪。"""
    con.execute("DELETE FROM article_words WHERE id=? AND article_id=?", (awid, aid))


# ================= 標出資料庫裡的字 =================
def scan_targets(con, lights=("red", "yellow")) -> list[dict]:
    """紅燈、黃燈的字和它們的變化形，讓前端在文章裡標出來。"""
    out = []
    for r in con.execute("SELECT * FROM words WHERE status='active'"):
        lt = srs.light(r)
        if lt not in lights:
            continue
        forms = {r["word"].lower()}
        if " " not in r["word"]:
            forms.update(f.lower() for f in dictionary.forms_of(r["word"]))
        m = con.execute("SELECT zh FROM meanings WHERE word_id=? ORDER BY sort, id LIMIT 1", (r["id"],)).fetchone()
        out.append({"id": r["id"], "word": r["word"], "light": lt, "forms": sorted(forms), "zh": m["zh"] if m else ""})
    return out
