"""匯出 CSV（Excel 可以直接開，中文不會亂碼）。"""
import csv
import io

from . import srs, words

LIGHT_NAMES = {"red": "紅燈", "yellow": "黃燈", "green": "綠燈"}

HEADER = [
    "英文", "KK 音標", "中文意思", "主分類", "其他分類", "字根字首", "記憶法", "例句", "補充",
    "相關字", "我的筆記", "出處", "燈號", "不同天答對", "答錯次數", "遺忘次數", "加入日期", "下次複習",
]


def to_csv(con, ids: list[int] | None) -> str:
    if ids is None:
        ids = [r["id"] for r in con.execute("SELECT id FROM words WHERE status='active' ORDER BY id")]
    buf = io.StringIO()
    buf.write("﻿")  # BOM：讓 Excel 用 UTF-8 開啟
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(HEADER)
    for wid in ids:
        x = words.load(con, wid)
        if not x or x["status"] != "active":
            continue
        s = x["stats"]
        kk = x["kk_user"] or (f"{x['kk_ai']}（AI）" if x["kk_ai"] else "")
        meanings = " / ".join(
            " ".join(p for p in (m["pos"], m["zh"], f"[{m['domain']}]" if m["domain"] else "", "★" if m["is_primary"] else "") if p)
            for m in x["meanings"]
        )
        examples = "\n".join(e["en"] + (f"（{e['zh']}）" if e["zh"] else "") for e in x["examples"])
        related = "；".join(r["word"] + "".join(f" {v}" for v in (r.get("zh"), r.get("pos"), r.get("rel") and f"（{r['rel']}）", r.get("note")) if v)
                           for r in x["related"])
        sources = "、".join(dict.fromkeys(e["source_title"] for e in x["examples"] if e["source_title"]))
        w.writerow([
            x["word"], kk, meanings, x["categories"]["primary"] or "", "、".join(x["categories"]["others"]),
            x["roots"], x["mnemonic"], examples, x["supplement"], related, x["my_note"], sources,
            LIGHT_NAMES[s["light"]], f"{min(s['correct_count'], srs.GRADUATE_AT)}/{srs.GRADUATE_AT}",
            s["wrong_count"], s["forget_count"], s["added_day"] or "",
            "已畢業" if s["graduated"] else (s["due_day"] or ""),
        ])
    return buf.getvalue()
