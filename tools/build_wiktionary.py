"""把 Wiktionary（kaikki.org 的 raw-wiktextract-data.jsonl.gz）整理成本機資料庫 data/wiktionary.db。

只要做一次（約 30～60 分鐘）。一行一行讀壓縮檔，不用先解壓縮，也不會把整個檔案載入記憶體。
保留：
  - 英文詞條：完整保留（字源、衍生字、相關字、意思、例句…原始 JSON 都留著）
  - 拉丁文、希臘文、古法語、古英語等：拆字根時查字根的意思用，同樣保留完整 JSON

用法：.venv\\Scripts\\python.exe tools\\build_wiktionary.py [壓縮檔路徑]
資料來源：Wiktionary（CC BY-SA），經 kaikki.org / wiktextract（Tatu Ylonen, LREC 2022）整理。
"""
import gzip
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "wiktionary" / "raw-wiktextract-data.jsonl.gz"
OUT = ROOT / "data" / "wiktionary.db"
TMP = OUT.with_suffix(".db.building")

# 英文 + 英文字源常見的來源語言
LANGS = {
    "en",                      # 英文
    "la", "la-lat", "la-med", "la-new", "VL.",  # 拉丁文（含後期、中世紀、新拉丁、通俗拉丁）
    "grc",                     # 古希臘文
    "fro", "frm", "xno", "fr",  # 古法語、中古法語、盎格魯諾曼語、法語
    "enm", "ang",              # 中古英語、古英語
    "non", "gem-pro", "ine-pro",  # 古諾斯語、原始日耳曼語、原始印歐語
    "it", "es", "de", "nl",    # 常見的借詞來源
}

_PATTERNS = [f'"lang_code": "{c}"' for c in LANGS] + [f'"lang_code":"{c}"' for c in LANGS]

SCHEMA = """
CREATE TABLE entries(
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL,          -- 小寫、去掉長音符號，查詢用
    word TEXT NOT NULL,
    lang_code TEXT NOT NULL,
    pos TEXT,
    etymology_text TEXT,
    etymology_templates TEXT,   -- JSON
    derived TEXT,               -- JSON：衍生字
    glosses TEXT,               -- JSON：前幾個意思（英文）
    raw TEXT NOT NULL           -- 完整原始 JSON
);
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
"""


def norm_key(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower().strip()


def glosses_of(e: dict) -> list[str]:
    out = []
    for s in e.get("senses") or []:
        for g in s.get("glosses") or []:
            if g and g not in out:
                out.append(g)
        if len(out) >= 6:
            break
    return out


def main():
    if not SRC.exists():
        sys.exit(f"找不到 {SRC}")
    if TMP.exists():
        TMP.unlink()
    con = sqlite3.connect(TMP)
    con.executescript(SCHEMA)
    con.execute("PRAGMA journal_mode=OFF")
    con.execute("PRAGMA synchronous=OFF")
    t0 = time.time()
    n_lines = n_kept = 0
    batch = []
    with gzip.open(SRC, "rt", encoding="utf-8") as f:
        for line in f:
            n_lines += 1
            # 先用字串粗篩（一行裡完全沒出現要的語言就跳過），再解析 JSON 看最外層的語言
            # 注意：翻譯、後代字裡面也有 lang_code，所以不能只看第一個
            if not any(p in line for p in _PATTERNS):
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            w = e.get("word")
            if not w or e.get("lang_code") not in LANGS:
                continue
            batch.append((
                norm_key(w), w, e["lang_code"], e.get("pos"),
                e.get("etymology_text"),
                json.dumps(e.get("etymology_templates") or [], ensure_ascii=False),
                json.dumps([d.get("word") for d in e.get("derived") or [] if d.get("word")], ensure_ascii=False),
                json.dumps(glosses_of(e), ensure_ascii=False),
                line.strip(),
            ))
            n_kept += 1
            if len(batch) >= 5000:
                con.executemany("INSERT INTO entries(key,word,lang_code,pos,etymology_text,etymology_templates,"
                                "derived,glosses,raw) VALUES (?,?,?,?,?,?,?,?,?)", batch)
                batch.clear()
            if n_lines % 200000 == 0:
                print(f"{n_lines:,} 行，保留 {n_kept:,} 筆，{time.time() - t0:.0f} 秒", flush=True)
    if batch:
        con.executemany("INSERT INTO entries(key,word,lang_code,pos,etymology_text,etymology_templates,"
                        "derived,glosses,raw) VALUES (?,?,?,?,?,?,?,?,?)", batch)
    print("建立索引…", flush=True)
    con.execute("CREATE INDEX idx_key ON entries(key, lang_code)")
    con.execute("INSERT INTO meta VALUES ('source', ?)", (SRC.name,))
    con.execute("INSERT INTO meta VALUES ('built', datetime('now','localtime'))")
    con.execute("INSERT INTO meta VALUES ('entries', ?)", (str(n_kept),))
    con.commit()
    con.close()
    if OUT.exists():
        OUT.unlink()
    TMP.rename(OUT)
    print(f"完成：{n_lines:,} 行，保留 {n_kept:,} 筆，{time.time() - t0:.0f} 秒 → {OUT}")


if __name__ == "__main__":
    main()
