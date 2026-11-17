"""複習：每日佇列、題目、記錄作答、推翻判定。"""
import json
import random
import re

from . import config, dictionary, grading, srs, words

ANSWER_KINDS = ("answer_ok", "answer_ng", "retry_ok", "retry_ng")


# ---------- 題目 ----------

def _cloze_pattern(word: str, forms: list[str]):
    """在例句裡找這個字（含變化形）的正規表示式。"""
    if " " in word.strip():
        body = r"\s+".join(re.escape(p) for p in word.split()) + r"(?:s|es)?"
        return re.compile(rf"(?<![A-Za-z]){body}(?![A-Za-z])", re.I)
    cands = sorted({word, *forms}, key=len, reverse=True)
    return re.compile(rf"(?<![A-Za-z])(?:{'|'.join(re.escape(c) for c in cands)})(?![A-Za-z])", re.I)


def _cloze_fallback(word: str):
    stem = word[:-1] if len(word) > 4 and word[-1] in "ey" else word
    return re.compile(rf"(?<![A-Za-z]){re.escape(stem)}[a-z]{{0,3}}(?![A-Za-z])", re.I)


def build_cloze(word: str, examples: list[dict]) -> list[dict]:
    pat = _cloze_pattern(word, dictionary.forms_of(word))
    fallback = _cloze_fallback(word) if " " not in word else None
    out = []
    for e in examples:
        m = pat.search(e["en"]) or (fallback.search(e["en"]) if fallback else None)
        if m:
            out.append({
                "before": e["en"][: m.start()],
                "answer": m.group(0),
                "after": e["en"][m.end():],
                "zh": e["zh"],
                "source": e["source"],
            })
    return out


def _example_pools(examples: list[dict], sources: set[str] | None) -> list[list[dict]]:
    """題目用哪些例句（依序找，第一組能用的就用）：
    1. 自由複習有選「出處文章」→ 那幾篇的原文句子
    2. AI 例句（一般複習都用這個；原文句子常常很長或在講別的事，當題目會干擾）
    3. 都沒有 AI 例句時，才用其他原文句子"""
    ctx = [e for e in examples if e["source"] == "context"]
    pools = []
    if sources:
        pools.append([e for e in ctx if e.get("source_title") in sources])
    pools.append([e for e in examples if e["source"] != "context"])
    pools.append(ctx)
    return [p for p in pools if p]


def question(con, wid: int, today: str, sources: set[str] | None = None) -> dict:
    w = words.load(con, wid, with_dict=True)
    r = con.execute("SELECT added_day, relearn_day FROM words WHERE id=?", (wid,)).fetchone()
    pools = _example_pools(w["examples"], sources)
    w["cloze"] = next((c for c in (build_cloze(w["word"], p) for p in pools) if c), [])
    w["hint_example"] = pools[0][0] if pools else None  # 英→中的「例句提示」
    w["prompt_meanings"] = [m for m in w["meanings"] if m["is_primary"]] or w["meanings"][:1]
    w["learning"] = srs.is_learning(r, today)
    return w


def _ordered(con, ids: list[int], shuffle: bool) -> list[int]:
    """照單字卡的分類順序排（同分類的相關字相鄰）；shuffle=True 時同分類內打亂。"""
    groups = words.browse(con)
    wanted = set(ids)
    out = []
    seen = set()
    for g in groups:
        # 只照主分類排（其他分類裡重複列出的字略過），同一個字只出一次
        part = [w["id"] for w in g["words"] if w["id"] in wanted and not w.get("secondary") and w["id"] not in seen]
        seen.update(part)
        if shuffle:
            random.shuffle(part)
        out.extend(part)
    missing = [i for i in ids if i not in set(out)]  # 理論上不會有
    return out + missing


# ---------- 每日複習 ----------

def _done_daily_today(con, today: str) -> set[int]:
    rows = con.execute(
        f"""SELECT DISTINCT word_id FROM events
            WHERE day=? AND kind IN ({','.join('?' * len(ANSWER_KINDS))})
              AND json_extract(detail,'$.session')='daily'""",
        (today, *ANSWER_KINDS),
    )
    return {r["word_id"] for r in rows}


def daily_state(con) -> dict:
    today = srs.today_str()
    done = _done_daily_today(con, today)
    rows = con.execute("SELECT * FROM words WHERE status='active'").fetchall()
    # 今天的新字（手動設成「我已經會了」的除外）
    new = [r for r in rows if srs.is_learning(r, today) and r["correct_count"] < srs.GRADUATE_AT]
    new_ids = {r["id"] for r in new}
    due = [
        r for r in rows
        if r["id"] not in new_ids and r["correct_count"] < srs.GRADUATE_AT
        and r["due_day"] and r["due_day"] <= today
    ]
    # 選字的優先順序：紅燈 → 過期最久 → 遺忘次數多
    due.sort(key=lambda r: (not r["is_red"], r["due_day"], -r["forget_count"], r["id"]))
    pending_new = sorted((r for r in new if r["id"] not in done), key=lambda r: r["id"])
    return {
        "today": today,
        "pending": [r["id"] for r in due] + [r["id"] for r in pending_new],
        "due": len(due),
        "due_red": sum(1 for r in due if r["is_red"]),
        "new": len(pending_new),
        "done": len(done),
    }


def daily_round(con, shuffle: bool) -> dict:
    st = daily_state(con)
    limit = int(config.load_settings()["daily_limit"])
    pick = st["pending"][:limit]
    ids = _ordered(con, pick, shuffle)
    return {
        "questions": [question(con, i, st["today"]) for i in ids],
        "remaining": max(0, len(st["pending"]) - len(pick)),
        "limit": limit,
        "state": {k: v for k, v in st.items() if k != "pending"},
    }


def free_list(con, ids: list[int], shuffle: bool, sources: list[str] | None = None) -> dict:
    today = srs.today_str()
    active = {
        r["id"] for r in con.execute(
            f"SELECT id FROM words WHERE status='active' AND id IN ({','.join('?' * len(ids))})", ids)
    } if ids else set()
    ordered = _ordered(con, [i for i in ids if i in active], shuffle)
    return {
        "questions": [question(con, i, today, set(sources or []) or None) for i in ordered],
        "limit": int(config.load_settings()["daily_limit"]),
    }


# ---------- 作答 ----------

def _result(con, wid: int, ev_id: int, grade: dict, effect: dict) -> dict:
    return {
        "event_id": ev_id,
        "correct": grade["correct"],
        "method": grade["method"],
        "reason": grade["reason"],
        "counted": effect["counted"],
        "effect": effect["effect"],
        "word": words.load(con, wid, with_dict=True),
    }


def answer(con, wid: int, mode: str, given: str, expected: str, session: str, retry: bool) -> dict:
    w = words.load(con, wid)
    if not w or w["status"] != "active":
        raise words.WordError("找不到這個單字")
    if mode == "en2zh":
        grade = grading.grade_zh(con, w, given)
    else:
        grade = grading.grade_en(given, expected or w["word"])
    snap = srs.snapshot(con, wid)
    effect = srs.apply_answer(con, wid, grade["correct"], session, retry)
    detail = {
        "session": session, "mode": mode, "answer": given, "expected": expected,
        "retry": retry, "correct": grade["correct"], "method": grade["method"],
        "snapshot": snap, "effect": effect["effect"],
    }
    kind = ("retry" if retry else "answer") + ("_ok" if grade["correct"] else "_ng")
    ev_id = con.execute(
        "INSERT INTO events(word_id,day,kind,detail) VALUES (?,?,?,?)",
        (wid, srs.today_str(), kind, json.dumps(detail, ensure_ascii=False)),
    ).lastrowid
    return _result(con, wid, ev_id, grade, effect)


def override(con, ev_id: int, correct: bool) -> dict:
    """「我其實答對了／其實錯了」：還原作答前的狀態，用新的判定重算。"""
    ev = con.execute("SELECT * FROM events WHERE id=?", (ev_id,)).fetchone()
    if not ev or ev["kind"] not in ANSWER_KINDS:
        raise words.WordError("找不到這次作答")
    later = con.execute(
        f"""SELECT 1 FROM events WHERE word_id=? AND id>?
            AND kind IN ({','.join('?' * len(ANSWER_KINDS))})""",
        (ev["word_id"], ev_id, *ANSWER_KINDS),
    ).fetchone()
    if later:
        raise words.WordError("這個字之後又作答過，不能再修改這一次的判定")
    d = json.loads(ev["detail"])
    wid = ev["word_id"]
    srs.restore(con, wid, d["snapshot"])
    effect = srs.apply_answer(con, wid, correct, d["session"], d["retry"])
    if d["mode"] == "en2zh" and d["answer"].strip():
        grading.remember_override(con, wid, d["answer"], correct)  # 下次同樣的說法直接判定
    d.update({"correct": correct, "overridden": True, "effect": effect["effect"]})
    kind = ("retry" if d["retry"] else "answer") + ("_ok" if correct else "_ng")
    con.execute("UPDATE events SET kind=?, detail=? WHERE id=?", (kind, json.dumps(d, ensure_ascii=False), ev_id))
    grade = {"correct": correct, "method": "override", "reason": "你修改了判定" + ("，這個說法以後都算對" if correct and d["mode"] == "en2zh" else "")}
    return _result(con, wid, ev_id, grade, effect)

