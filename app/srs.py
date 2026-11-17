"""複習規則（規格書第 6 節）。

- 一天：凌晨 day_start_hour 點換日
- 在 3 個不同的日子答對就畢業（不用連續）
- 答對後間隔：累計 1 → 3 天後；累計 2 → 7 天後；累計 3 → 畢業
- 答錯：累計 -1（最少 0）、紅燈、明天再考
- 重複輸入：累計歸零、紅燈、遺忘次數 +1
"""
from datetime import date, datetime, timedelta

from . import config

GRADUATE_AT = 3
INTERVAL_AFTER = {1: 3, 2: 7}  # 答對後累計變成 n → 幾天後再考


def logical_today(now: datetime | None = None) -> date:
    now = now or datetime.now()
    hour = int(config.load_settings()["day_start_hour"])
    return (now - timedelta(hours=hour)).date()


def today_str() -> str:
    return logical_today().isoformat()


def add_days(day: str, n: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=n)).isoformat()


def light(row) -> str:
    if row["correct_count"] >= GRADUATE_AT:
        return "green"
    if row["is_red"]:
        return "red"
    return "yellow"


def log(con, word_id: int, day: str, kind: str, detail: str = "") -> None:
    con.execute(
        "INSERT INTO events(word_id,day,kind,detail) VALUES (?,?,?,?)", (word_id, day, kind, detail)
    )


def activate_new(con, word_id: int) -> None:
    """確認存入的新字：黃燈、累計 0、明天第一次考。"""
    today = today_str()
    con.execute(
        """UPDATE words SET status='active', error=NULL, added_day=?, due_day=?,
               correct_count=0, is_red=0, graduated_day=NULL,
               updated_at=datetime('now','localtime')
           WHERE id=?""",
        (today, add_days(today, 1), word_id),
    )
    log(con, word_id, today, "added")


SNAP_FIELDS = ("correct_count", "wrong_count", "is_red", "due_day", "last_answer_day", "graduated_day")


def snapshot(con, word_id: int) -> dict:
    r = con.execute(f"SELECT {','.join(SNAP_FIELDS)} FROM words WHERE id=?", (word_id,)).fetchone()
    return dict(r)


def restore(con, word_id: int, snap: dict) -> None:
    sets = ",".join(f"{f}=?" for f in SNAP_FIELDS)
    con.execute(f"UPDATE words SET {sets} WHERE id=?", (*[snap[f] for f in SNAP_FIELDS], word_id))


def is_learning(row, today: str) -> bool:
    """今天新增或今天重複輸入的字：今天的練習不計分。"""
    return row["added_day"] == today or row["relearn_day"] == today


def apply_answer(con, word_id: int, correct: bool, session: str, retry: bool) -> dict:
    """依規格書 6.2／6.6 更新累計、燈號、下次複習日。回傳 {counted, effect}。

    session: 'daily'（每日複習）或 'free'（自由複習）
    retry:   同一輪答錯後再練一次
    """
    today = today_str()
    r = con.execute("SELECT * FROM words WHERE id=?", (word_id,)).fetchone()
    if retry:
        return {"counted": False, "effect": "再練一次，不計分"}
    if not correct:
        con.execute("UPDATE words SET wrong_count=wrong_count+1 WHERE id=?", (word_id,))
    if is_learning(r, today):
        return {"counted": False, "effect": "今天的新字，練習不計分；明天開始正式複習"}
    if r["last_answer_day"] == today:
        return {"counted": False, "effect": "今天已經作答過這個字，一天只算一次"}
    if session == "free" and correct:
        return {"counted": False, "effect": "自由複習答對不計入累計"}

    old = r["correct_count"]
    if correct:
        n = old + 1
        if n >= GRADUATE_AT:
            con.execute(
                """UPDATE words SET correct_count=?, is_red=0, due_day=NULL, graduated_day=?,
                       last_answer_day=? WHERE id=?""",
                (n, today, today, word_id),
            )
            return {"counted": True, "effect": f"🎉 在 {GRADUATE_AT} 個不同的日子答對，畢業了！"}
        days = INTERVAL_AFTER[n]
        due = add_days(today, days)
        con.execute(
            "UPDATE words SET correct_count=?, is_red=0, due_day=?, last_answer_day=? WHERE id=?",
            (n, due, today, word_id),
        )
        return {"counted": True, "effect": f"累計 {n}/{GRADUATE_AT}，{days} 天後（{due}）再考"}

    n = max(0, old - 1)
    due = add_days(today, 1)
    con.execute(
        """UPDATE words SET correct_count=?, is_red=1, due_day=?, graduated_day=NULL,
               last_answer_day=? WHERE id=?""",
        (n, due, today, word_id),
    )
    return {"counted": True, "effect": f"累計 {old} → {n}，變紅燈，明天再考"}


def set_progress(con, word_id: int, n: int) -> None:
    """手動設定「不同天答對」次數。3＝我本來就會（畢業）；0＝重新開始。
    下次複習日照間隔表：0 → 明天、1 → 3 天後、2 → 7 天後。"""
    n = max(0, min(GRADUATE_AT, int(n)))
    today = today_str()
    old = con.execute("SELECT correct_count FROM words WHERE id=?", (word_id,)).fetchone()["correct_count"]
    if n >= GRADUATE_AT:
        con.execute(
            """UPDATE words SET correct_count=?, is_red=0, due_day=NULL, graduated_day=?,
                   updated_at=datetime('now','localtime') WHERE id=?""",
            (n, today, word_id),
        )
    else:
        due = add_days(today, INTERVAL_AFTER.get(n, 1))
        con.execute(
            """UPDATE words SET correct_count=?, is_red=0, due_day=?, graduated_day=NULL,
                   updated_at=datetime('now','localtime') WHERE id=?""",
            (n, due, word_id),
        )
    log(con, word_id, today, "manual", f"{min(old, GRADUATE_AT)}→{n}")


def set_light(con, word_id: int, light: str) -> None:
    """手動改燈號。
    綠：畢業（累計 3）。黃：取消紅燈；原本是綠燈的話變回累計 2、7 天後再考。
    紅：標成不熟、明天就考；原本是綠燈的話累計變 2。"""
    r = con.execute("SELECT correct_count, due_day FROM words WHERE id=?", (word_id,)).fetchone()
    today = today_str()
    graduated = r["correct_count"] >= GRADUATE_AT
    if light == "green":
        set_progress(con, word_id, GRADUATE_AT)
        return
    if light == "yellow":
        if graduated:
            set_progress(con, word_id, GRADUATE_AT - 1)
        else:
            con.execute("UPDATE words SET is_red=0, updated_at=datetime('now','localtime') WHERE id=?", (word_id,))
            log(con, word_id, today, "manual", "黃燈")
        return
    if light == "red":
        n = min(r["correct_count"], GRADUATE_AT - 1)
        tomorrow = add_days(today, 1)
        due = tomorrow if not r["due_day"] or r["due_day"] > tomorrow else r["due_day"]
        con.execute(
            """UPDATE words SET correct_count=?, is_red=1, graduated_day=NULL, due_day=?,
                   updated_at=datetime('now','localtime') WHERE id=?""",
            (n, due, word_id),
        )
        log(con, word_id, today, "manual", "紅燈")
        return
    raise ValueError(light)


def apply_reinput(con, word_id: int) -> None:
    """又輸入了學過的字：代表忘了。"""
    today = today_str()
    con.execute(
        """UPDATE words SET correct_count=0, is_red=1, forget_count=forget_count+1,
               relearn_day=?, due_day=?, graduated_day=NULL,
               updated_at=datetime('now','localtime')
           WHERE id=?""",
        (today, add_days(today, 1), word_id),
    )
    log(con, word_id, today, "reinput")
