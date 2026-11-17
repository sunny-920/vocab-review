"""統計頁的資料。"""
from collections import defaultdict
from datetime import date

from . import review, srs, words

ANSWER = ("answer_ok", "answer_ng")
PRACTICE = ("answer_ok", "answer_ng", "retry_ok", "retry_ng")


def _streaks(days: set[str], today: str) -> tuple[int, int]:
    """(目前連續天數, 最長連續天數)。今天還沒練習的話，從昨天開始算。"""
    if not days:
        return 0, 0
    cur = 0
    d = today if today in days else srs.add_days(today, -1)
    while d in days:
        cur += 1
        d = srs.add_days(d, -1)
    best, run, prev = 0, 0, None
    for d in sorted(days):
        run = run + 1 if prev and (date.fromisoformat(d) - date.fromisoformat(prev)).days == 1 else 1
        best = max(best, run)
        prev = d
    return cur, best


def build(con) -> dict:
    today = srs.today_str()
    rows = words.summaries(con)

    # 每天的活動（最近一年）
    start = srs.add_days(today, -370)
    daily = defaultdict(lambda: {"answers": 0, "correct": 0, "practiced": set(), "added": 0, "reinput": 0})
    for e in con.execute("SELECT day, kind, word_id FROM events WHERE day>=?", (start,)):
        d = daily[e["day"]]
        if e["kind"] in ANSWER:
            d["answers"] += 1
            d["correct"] += e["kind"] == "answer_ok"
        if e["kind"] in PRACTICE:
            d["practiced"].add(e["word_id"])
        elif e["kind"] == "added":
            d["added"] += 1
        elif e["kind"] == "reinput":
            d["reinput"] += 1
    daily_list = [
        {"day": k, "answers": v["answers"], "correct": v["correct"], "words": len(v["practiced"]),
         "added": v["added"], "reinput": v["reinput"]}
        for k, v in sorted(daily.items())
    ]

    practice_days = {
        r["day"] for r in con.execute(
            f"SELECT DISTINCT day FROM events WHERE kind IN ({','.join('?' * len(PRACTICE))})", PRACTICE)
    }
    streak, best = _streaks(practice_days, today)

    totals = {r["kind"]: r["n"] for r in con.execute(
        "SELECT kind, COUNT(*) n FROM events WHERE kind IN ('answer_ok','answer_ng') GROUP BY kind")}
    answers = totals.get("answer_ok", 0) + totals.get("answer_ng", 0)

    lights = {"red": 0, "yellow": 0, "green": 0}
    for r in rows:
        lights[r["light"]] += 1

    # 各分類的燈號分布（依主分類，照分類順序）
    by_cat = defaultdict(lambda: {"red": 0, "yellow": 0, "green": 0})
    for r in rows:
        by_cat[r["category"] or "未分類"][r["light"]] += 1
    order = [c["path"] for c in words.categories(con)] + ["未分類"]
    categories = [{"path": p, **by_cat[p], "total": sum(by_cat[p].values())} for p in order if p in by_cat]

    # 頑固字：忘記過、常答錯的字
    stubborn = []
    for r in rows:
        score = r["forget_count"] * 3 + r["wrong_answers"]
        if score > 0:
            stubborn.append({
                "id": r["id"], "word": r["word"], "zh": r["zh"], "light": r["light"],
                "forget_count": r["forget_count"], "answers": r["answers"], "wrong_answers": r["wrong_answers"],
                "rate": round(r["wrong_answers"] / r["answers"] * 100) if r["answers"] else None,
                "score": score,
            })
    stubborn.sort(key=lambda x: (-x["score"], -(x["rate"] or 0), x["word"].lower()))

    # 接下來 14 天的複習量
    st = review.daily_state(con)
    due_by_day = defaultdict(int)
    for r in con.execute(
        "SELECT due_day FROM words WHERE status='active' AND correct_count<? AND due_day>?",
        (srs.GRADUATE_AT, today),
    ):
        due_by_day[r["due_day"]] += 1
    upcoming = [{"day": today, "count": len(st["pending"]), "today": True}]
    for i in range(1, 14):
        d = srs.add_days(today, i)
        upcoming.append({"day": d, "count": due_by_day.get(d, 0), "today": False})

    return {
        "today": today,
        "summary": {
            "total": len(rows),
            "lights": lights,
            "answers": answers,
            "correct_rate": round(totals.get("answer_ok", 0) / answers * 100) if answers else None,
            "streak": streak,
            "best_streak": best,
            "practice_days": len(practice_days),
            "today_words": len(daily[today]["practiced"]) if today in daily else 0,
        },
        "daily": daily_list,
        "categories": categories,
        "stubborn": stubborn[:15],
        "upcoming": upcoming,
    }
