"""背景工作：一個一個把單字送給 AI 整理。"""
import queue
import threading
import traceback

from . import ai, db, dictionary, words

# 先做完所有「整理單字」，有空時才做「記憶法」（要思考，比較慢）
_queue: "queue.PriorityQueue[tuple[int, int, str, int]]" = queue.PriorityQueue()
_seq = 0
_pending: list[int] = []
_mem_pending: list[int] = []
_current: int | None = None
_lock = threading.Lock()
_started = False


def start() -> None:
    global _started
    if _started:
        return
    _started = True
    with db.tx() as con:
        for r in con.execute("SELECT id FROM words WHERE status='generating' ORDER BY id"):
            enqueue(r["id"])
        for r in con.execute("SELECT id FROM words WHERE mem_state='pending' AND status<>'generating' ORDER BY id"):
            enqueue_memory(r["id"])
    threading.Thread(target=_run, name="ai-worker", daemon=True).start()


def _put(priority: int, kind: str, wid: int) -> None:
    global _seq
    _seq += 1
    _queue.put((priority, _seq, kind, wid))


def enqueue(wid: int) -> None:
    with _lock:
        if wid in _pending or wid == _current:
            return
        _pending.append(wid)
        _put(0, "word", wid)


def enqueue_memory(wid: int) -> None:
    with _lock:
        if wid in _mem_pending:
            return
        _mem_pending.append(wid)
        _put(1, "memory", wid)


def position(wid: int) -> int | None:
    """0 = 正在處理，1 = 下一個 ..."""
    with _lock:
        if wid == _current:
            return 0
        if wid in _pending:
            return _pending.index(wid) + 1
    return None


def _run() -> None:
    global _current
    while True:
        _, _, kind, wid = _queue.get()
        if kind == "memory":
            with _lock:
                if wid in _mem_pending:
                    _mem_pending.remove(wid)
            _process_memory(wid)
            continue
        with _lock:
            if wid in _pending:
                _pending.remove(wid)
            _current = wid
        try:
            _process(wid)
        except Exception as e:  # 任何錯誤都記在單字上，不讓背景工作停掉
            msg = str(e) if isinstance(e, ai.AIError) else f"{type(e).__name__}: {e}"
            if not isinstance(e, ai.AIError):
                traceback.print_exc()
            with db.tx() as con:
                con.execute(
                    "UPDATE words SET status='error', error=? WHERE id=? AND status='generating'", (msg, wid)
                )
        finally:
            with _lock:
                _current = None


def _process(wid: int) -> None:
    with db.tx() as con:
        r = con.execute("SELECT * FROM words WHERE id=?", (wid,)).fetchone()
        if not r or r["status"] != "generating":
            return
        info = dictionary.lookup(r["word"])
        ctx = {
            "word": r["word"],
            "user_zh": r["user_zh"],
            "contexts": [
                e["en"] for e in con.execute(
                    "SELECT en FROM examples WHERE word_id=? AND source='context' ORDER BY sort,id", (wid,))
            ],
            "dict_lines": info["translation"] if info else [],
            "resemble": dictionary.resemble_for(r["word"]),
            "lookalikes": dictionary.lookalikes(r["word"]),
            "candidates": words.candidates(con, r["word"], exclude_id=wid),
            "related_pool": words.related_pool(con, r["word"], exclude_id=wid),
            "category_paths": words.category_paths(con),
            "category_notes": words.category_notes(con),
        }
    result = ai.generate(ctx)  # 不在資料庫交易裡等 AI
    with db.tx() as con:
        r = con.execute("SELECT status FROM words WHERE id=?", (wid,)).fetchone()
        if r and r["status"] == "generating":  # 等待期間沒被刪掉
            words.apply_ai(con, wid, result)
            enqueue_memory(wid)


def _process_memory(wid: int) -> None:
    with db.tx() as con:
        r = con.execute("SELECT status, mem_state FROM words WHERE id=?", (wid,)).fetchone()
        if not r or r["mem_state"] != "pending" or r["status"] == "generating":
            return
        ctx = words.memory_ctx(con, wid)
    _review_examples(wid)
    try:
        alts = ai.memory(ctx)
    except Exception as e:
        if not isinstance(e, ai.AIError):
            traceback.print_exc()
        with db.tx() as con:
            con.execute("UPDATE words SET mem_state='error' WHERE id=? AND mem_state='pending'", (wid,))
        return
    with db.tx() as con:
        r = con.execute("SELECT mem_state FROM words WHERE id=?", (wid,)).fetchone()
        if r and r["mem_state"] == "pending":
            words.apply_memory(con, wid, alts, fill=True)


def _review_examples(wid: int) -> None:
    """AI 例句再檢查一次（文法、用法，開思考），有問題就改寫或拿掉。失敗就保留原本的。"""
    with db.tx() as con:
        r = con.execute("SELECT word, status FROM words WHERE id=?", (wid,)).fetchone()
        if not r or r["status"] != "draft":
            return  # 已經確認存入（你可能改過例句）就不動
        exs = [dict(e) for e in con.execute(
            "SELECT id, en, zh FROM examples WHERE word_id=? AND source='ai' ORDER BY sort, id", (wid,))]
        meanings = [dict(m) for m in con.execute(
            "SELECT pos, zh FROM meanings WHERE word_id=? ORDER BY is_primary DESC, sort, id", (wid,))]
    if not exs:
        return
    try:
        fixed = ai.review_examples(r["word"], meanings, [{"en": e["en"], "zh": e["zh"]} for e in exs])
    except Exception:
        traceback.print_exc()
        return
    with db.tx() as con:
        st = con.execute("SELECT status FROM words WHERE id=?", (wid,)).fetchone()
        if not st or st["status"] != "draft":
            return
        con.execute("DELETE FROM examples WHERE word_id=? AND source='ai'", (wid,))
        for i, e in enumerate(fixed):
            con.execute("INSERT INTO examples(word_id,en,zh,source,sort) VALUES (?,?,?,'ai',?)",
                        (wid, e["en"], e["zh"], i))
