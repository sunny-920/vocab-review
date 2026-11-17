"""建立精簡版離線字典 data/ecdict_lite.db

資料來源：ECDICT（https://github.com/skywind3000/ECDICT，MIT 授權）

用法：
  python -I tools/setup_dict.py              下載原始檔到暫存資料夾、建立字典、刪除暫存
  python -I tools/setup_dict.py --from DIR   使用已下載在 DIR 裡的原始檔
"""
import argparse
import csv
import json
import shutil
import sqlite3
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "ecdict_lite.db"
BASE_URL = "https://raw.githubusercontent.com/skywind3000/ECDICT/master/"
FILES = ["ecdict.csv", "wordroot.txt", "resemble.txt"]


def download(dest: Path) -> None:
    for name in FILES:
        print(f"下載 {name} ...", flush=True)
        urllib.request.urlretrieve(BASE_URL + name, dest / name)


def _int(s: str) -> int:
    try:
        return int(s)
    except (TypeError, ValueError):
        return 0


def keep(row: dict) -> bool:
    """單字全收；片語只收有考試標籤或有詞頻的，控制檔案大小。"""
    if not row["translation"].strip():
        return False
    if " " not in row["word"].strip():
        return True
    return bool(row["tag"].strip()) or _int(row["frq"]) > 0 or _int(row["bnc"]) > 0


def build(src: Path, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".building")
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(tmp)
    con.executescript(
        """
        CREATE TABLE entries(
            id INTEGER PRIMARY KEY, word TEXT NOT NULL, key TEXT NOT NULL,
            phonetic TEXT, translation TEXT, tag TEXT, frq INTEGER, exchange TEXT);
        CREATE TABLE roots(id INTEGER PRIMARY KEY, root TEXT, meaning TEXT, class TEXT, origin TEXT);
        CREATE TABLE root_words(word TEXT NOT NULL, root_id INTEGER NOT NULL);
        CREATE TABLE resemble(id INTEGER PRIMARY KEY, words TEXT, body TEXT);
        CREATE TABLE resemble_words(word TEXT NOT NULL, group_id INTEGER NOT NULL);
        """
    )

    # 1. 字典本體
    csv.field_size_limit(10**7)
    count = 0
    batch = []
    sql = "INSERT INTO entries(word,key,phonetic,translation,tag,frq,exchange) VALUES (?,?,?,?,?,?,?)"
    with open(src / "ecdict.csv", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if not keep(r):
                continue
            w = r["word"].strip()
            frq = _int(r["frq"]) or _int(r["bnc"])
            batch.append((
                w, w.lower(), r["phonetic"].strip(),
                r["translation"].strip().replace("\\n", "\n"),
                r["tag"].strip(), frq, r["exchange"].strip(),
            ))
            if len(batch) >= 5000:
                con.executemany(sql, batch)
                count += len(batch)
                batch.clear()
    con.executemany(sql, batch)
    count += len(batch)
    print(f"字典詞條：{count:,}", flush=True)

    # 2. 字根表
    roots = json.loads((src / "wordroot.txt").read_text(encoding="utf-8-sig"))
    n_roots = 0
    for key, v in roots.items():
        if not isinstance(v, dict):
            continue
        cur = con.execute(
            "INSERT INTO roots(root,meaning,class,origin) VALUES (?,?,?,?)",
            (v.get("root") or key, v.get("meaning", ""), v.get("class", ""), v.get("origin", "")),
        )
        rid = cur.lastrowid
        n_roots += 1
        for ex in v.get("example") or []:
            if isinstance(ex, str) and ex.strip():
                con.execute("INSERT INTO root_words(word,root_id) VALUES (?,?)", (ex.strip().lower(), rid))
    print(f"字根：{n_roots:,}", flush=True)

    # 3. 近義字辨析（每組以「% 字1, 字2, ...」開頭）
    groups = []
    header, body = None, []
    for line in (src / "resemble.txt").read_text(encoding="utf-8-sig").splitlines():
        if line.startswith("%"):
            if header:
                groups.append((header, "\n".join(body).strip()))
            header, body = line[1:].strip(), []
        elif header is not None:
            body.append(line)
    if header:
        groups.append((header, "\n".join(body).strip()))
    for header, text in groups:
        gid = con.execute("INSERT INTO resemble(words,body) VALUES (?,?)", (header, text)).lastrowid
        for w in header.split(","):
            if w.strip():
                con.execute("INSERT INTO resemble_words(word,group_id) VALUES (?,?)", (w.strip().lower(), gid))
    print(f"近義字辨析：{len(groups):,} 組", flush=True)

    con.executescript(
        """
        CREATE INDEX idx_entries_key ON entries(key);
        CREATE INDEX idx_root_words ON root_words(word);
        CREATE INDEX idx_resemble_words ON resemble_words(word);
        """
    )
    con.commit()
    con.execute("VACUUM")
    con.close()
    if out.exists():
        out.unlink()
    tmp.rename(out)
    print(f"完成：{out}（{out.stat().st_size / 1e6:.1f} MB）", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", help="已下載原始檔的資料夾")
    args = ap.parse_args()
    if args.src:
        build(Path(args.src), OUT)
        return
    tmpdir = Path(tempfile.mkdtemp(prefix="ecdict_"))
    try:
        download(tmpdir)
        build(tmpdir, OUT)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
