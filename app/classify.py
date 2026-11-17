"""AI 分類：在背景掃描單字，產生建議清單，讓使用者勾選後才套用。

- 一般分類（例如「研究」）：找出屬於這個分類的字。大類有小類的話，幫每個字挑最適合的小類。
- 「未分類」：把裡面的字放進現有分類；都不適合的，AI 可以建議新分類。
"""
import threading
import traceback
import uuid

from . import ai, db, words

BATCH = 20  # 一次問 AI 幾個字

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def start(cid: int) -> str:
    with db.tx() as con:
        cat = next((c for c in words.categories(con) if c["id"] == cid), None)
        if not cat:
            raise words.WordError("找不到分類")
        allcats = words.categories(con)
        notes = words.category_notes(con)
        uid = words.uncategorized_id(con)
        rows = words.summaries(con)
        if cat["system"]:
            options = words.category_paths(con)
            target_ids = {uid}
            cands = [r for r in rows if set(r["category_ids"]) <= {uid}]  # 只在未分類裡的字
        else:
            kids = [c for c in allcats if c["parent_id"] == cid]
            options = [c["path"] for c in kids] or [cat["path"]]
            target_ids = {cid, *(c["id"] for c in kids)}
            cands = [r for r in rows if not target_ids & set(r["category_ids"])]
    job = {
        "id": uuid.uuid4().hex[:12], "category": cat["path"], "system": cat["system"],
        "status": "running", "done": 0, "total": len(cands), "suggestions": [], "error": None,
    }
    with _lock:
        for old in [k for k, v in _jobs.items() if v["status"] != "running"][:-10]:
            del _jobs[old]  # 只留最近的結果
        _jobs[job["id"]] = job
    threading.Thread(target=_run, args=(job, options, cands, uid, notes), daemon=True).start()
    return job["id"]


def get(job_id: str) -> dict | None:
    with _lock:
        j = _jobs.get(job_id)
        return dict(j, suggestions=list(j["suggestions"])) if j else None


def _run(job: dict, options: list[str], cands: list[dict], uid: int, notes: dict[str, str]) -> None:
    try:
        existing = set(options)
        for i in range(0, len(cands), BATCH):
            batch = cands[i:i + BATCH]
            items = [{
                "word": r["word"], "zh": r["zh"],
                "current": "" if r["category"] == words.UNCATEGORIZED else r["category"],
            } for r in batch]
            result = ai.classify(options, items, allow_new=job["system"], notes=notes)
            found = []
            for r in batch:
                path = result.get(r["word"].lower())
                if not path:
                    continue
                found.append({
                    "word_id": r["id"], "word": r["word"], "zh": r["zh"],
                    "current": r["category"], "path": path,
                    "is_new": path not in existing,
                    "role": "primary" if set(r["category_ids"]) <= {uid} else "secondary",
                })
            with _lock:
                job["suggestions"].extend(found)
                job["done"] = min(len(cands), i + len(batch))
        job["status"] = "done"
    except Exception as e:
        if not isinstance(e, ai.AIError):
            traceback.print_exc()
        job["status"] = "error"
        job["error"] = str(e)
