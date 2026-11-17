"""判分（規格書第 5 節）。

英→中：① 跟所有中文意思比對 → ② 查判定過的說法 → ③ 問 AI（結果存起來）
中→英、例句填空：拼字嚴格比對（不分大小寫）
"""
import re

from . import ai

_PUNCT = re.compile(r"[\s，。、；;,.!?！？「」『』\[\]【】…~～\-—_:：/'\"“”‘’·•]+")
_PAREN = re.compile(r"[（(][^）)]*[）)]")
_SPLIT = re.compile(r"[、,，;；/／\s]+")
_TAIL = re.compile(r"[的地得了]+$")
_HEAD = re.compile(r"^[已被使]")          # 「已排序的」≈「排序的」、「使維持」≈「維持」
_NEGATION = re.compile(r"[不無非未沒別勿莫]")


def norm_zh(s: str) -> str:
    s = _PUNCT.sub("", s or "")
    return _TAIL.sub("", s) or s


def _core(s: str) -> str:
    """比對用：再去掉開頭的「已／被／使」。"""
    return _HEAD.sub("", s) if len(s) > 2 else s


def zh_terms(text: str) -> list[str]:
    out = []
    for variant in (_PAREN.sub("", text or ""), text or ""):
        for t in _SPLIT.split(variant):
            t = norm_zh(_PAREN.sub("", t))
            if t and t not in out:
                out.append(t)
    return out


def match_zh(answer: str, meanings: list[dict]) -> bool:
    """直接比對（不問 AI）。只接受：完全相同，或你的答案「包含」整個意思再多加修飾（不能加否定詞）。
    你的答案只是意思的一部分（例如「資料」對「資料表」）不算，交給 AI 判斷。"""
    users = [_core(u) for u in zh_terms(answer)]
    targets = [_core(t) for m in meanings for t in zh_terms(m["zh"])]
    for u in users:
        for t in targets:
            if u == t:
                return True
            if len(t) >= 2 and t in u:  # 「仔細檢查」含「檢查」
                extra = u.replace(t, "", 1)
                if not _NEGATION.search(extra) and len(extra) <= 3:
                    return True
    return False


def norm_en(s: str) -> str:
    s = (s or "").replace("’", "'").replace("‘", "'").lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s.strip(".,;:!?\"")


def grade_zh(con, word: dict, answer: str) -> dict:
    """回傳 {correct, method, reason}"""
    if not answer.strip():
        return {"correct": False, "method": "blank", "reason": ""}
    if match_zh(answer, word["meanings"]):
        return {"correct": True, "method": "match", "reason": ""}
    key = norm_zh(answer)
    row = con.execute(
        "SELECT correct, source FROM accepted_answers WHERE word_id=? AND answer=?", (word["id"], key)
    ).fetchone()
    if row:
        return {"correct": bool(row["correct"]), "method": "accepted",
                "reason": "你之前判定過這個說法" if row["source"] == "user" else "AI 之前判定過這個說法"}
    try:
        ok, reason = ai.judge(word["word"], word["meanings"], answer)
    except ai.AIError as e:
        return {"correct": False, "method": "ai_unavailable", "reason": str(e)}
    con.execute(
        "INSERT OR REPLACE INTO accepted_answers(word_id,answer,correct,source) VALUES (?,?,?,'ai')",
        (word["id"], key, int(ok)),
    )
    return {"correct": ok, "method": "ai", "reason": reason}


def grade_en(answer: str, expected: str) -> dict:
    if not answer.strip():
        return {"correct": False, "method": "blank", "reason": ""}
    return {"correct": norm_en(answer) == norm_en(expected), "method": "spelling", "reason": ""}


def remember_override(con, word_id: int, answer: str, correct: bool) -> None:
    key = norm_zh(answer)
    if key:
        con.execute(
            "INSERT OR REPLACE INTO accepted_answers(word_id,answer,correct,source) VALUES (?,?,?,'user')",
            (word_id, key, int(correct)),
        )
