"""單字的讀寫、分類、排序。"""
import json
import re
from collections import defaultdict

from . import dictionary, srs


class WordError(Exception):
    pass


# ---------- 分類 ----------

UNCATEGORIZED = "未分類"


def categories(con) -> list[dict]:
    rows = con.execute("SELECT id,parent_id,name,sort,system,description FROM categories").fetchall()
    by_parent = defaultdict(list)
    for r in rows:
        by_parent[r["parent_id"]].append(r)
    out = []
    for top in sorted(by_parent[None], key=lambda r: (r["system"], r["sort"], r["id"])):  # 未分類排最後
        out.append({"id": top["id"], "parent_id": None, "name": top["name"], "path": top["name"],
                    "depth": 0, "system": bool(top["system"]), "description": top["description"]})
        for ch in sorted(by_parent[top["id"]], key=lambda r: (r["sort"], r["id"])):
            out.append({
                "id": ch["id"], "parent_id": top["id"], "name": ch["name"],
                "path": f'{top["name"]}/{ch["name"]}', "depth": 1, "system": False,
                "description": ch["description"],
            })
    return out


def category_paths(con) -> list[str]:
    """給 AI 挑的分類（不含「未分類」）。"""
    return [c["path"] for c in categories(con) if not c["system"]]


def category_notes(con) -> dict[str, str]:
    """有填說明的分類 {路徑: 說明}，給 AI 參考。"""
    return {c["path"]: c["description"] for c in categories(con) if not c["system"] and c["description"].strip()}


def set_description(con, cid: int, text: str) -> None:
    row = con.execute("SELECT system FROM categories WHERE id=?", (cid,)).fetchone()
    if not row:
        raise WordError("找不到分類")
    if row["system"]:
        raise WordError(f"「{UNCATEGORIZED}」不需要說明")
    con.execute("UPDATE categories SET description=? WHERE id=?", (text.strip()[:500], cid))


def uncategorized_id(con) -> int:
    return con.execute("SELECT id FROM categories WHERE system=1").fetchone()["id"]


def ensure_category(con, path: str) -> int:
    parts = [p.strip() for p in re.split(r"[/／]", path or "") if p.strip()][:2]
    if not parts:
        raise WordError("分類名稱不能是空的")
    parent = None
    for name in parts:
        row = con.execute(
            "SELECT id, system FROM categories WHERE parent_id IS ? AND name=?", (parent, name)
        ).fetchone()
        if row:
            if row["system"] and len(parts) > 1:
                raise WordError(f"「{UNCATEGORIZED}」底下不能建立小類")
            parent = row["id"]
        else:
            sort = con.execute(
                "SELECT COALESCE(MAX(sort),-1)+1 FROM categories WHERE parent_id IS ? AND system=0", (parent,)
            ).fetchone()[0]
            parent = con.execute(
                "INSERT INTO categories(parent_id,name,sort) VALUES (?,?,?)", (parent, name, sort)
            ).lastrowid
    return parent


def rename_category(con, cid: int, name: str) -> None:
    name = name.strip().replace("/", "／")
    if not name:
        raise WordError("分類名稱不能是空的")
    row = con.execute("SELECT parent_id, system FROM categories WHERE id=?", (cid,)).fetchone()
    if not row:
        raise WordError("找不到分類")
    if row["system"]:
        raise WordError(f"「{UNCATEGORIZED}」是系統分類，不能改名")
    dup = con.execute(
        "SELECT 1 FROM categories WHERE parent_id IS ? AND name=? AND id<>?", (row["parent_id"], name, cid)
    ).fetchone()
    if dup:
        raise WordError("已經有同名的分類")
    con.execute("UPDATE categories SET name=? WHERE id=?", (name, cid))


def _write_categories(con, wid: int, ids: list[int]) -> None:
    """ids[0] 是主分類。有真正的分類就拿掉「未分類」；一個都沒有就放「未分類」。"""
    uid = uncategorized_id(con)
    seen = []
    for i in ids:
        if i not in seen:
            seen.append(i)
    real = [i for i in seen if i != uid]
    final = real or [uid]
    con.execute("DELETE FROM word_categories WHERE word_id=?", (wid,))
    for n, cid in enumerate(final):
        con.execute(
            "INSERT INTO word_categories(word_id,category_id,is_primary) VALUES (?,?,?)", (wid, cid, int(n == 0))
        )


def set_categories(con, wid: int, primary: str | None, others: list[str]) -> None:
    ids = [ensure_category(con, primary)] if primary else []
    ids += [ensure_category(con, p) for p in others if p]
    _write_categories(con, wid, ids)


def _word_cat_ids(con, wid: int) -> list[int]:
    return [r["category_id"] for r in con.execute(
        "SELECT category_id FROM word_categories WHERE word_id=? ORDER BY is_primary DESC", (wid,))]


def _subtree(con, cid: int) -> list[int]:
    return [cid] + [r["id"] for r in con.execute("SELECT id FROM categories WHERE parent_id=?", (cid,))]


def delete_preview(con, cid: int) -> dict:
    c = con.execute("SELECT * FROM categories WHERE id=?", (cid,)).fetchone()
    if not c:
        raise WordError("找不到分類")
    if c["system"]:
        raise WordError(f"「{UNCATEGORIZED}」是系統分類，不能刪除")
    ids = _subtree(con, cid)
    paths = {x["id"]: x["path"] for x in categories(con)}
    affected = {r["word_id"] for r in con.execute(
        f"SELECT word_id FROM word_categories WHERE category_id IN ({','.join('?' * len(ids))})", ids)}
    keep = sum(1 for w in affected if any(i not in ids for i in _word_cat_ids(con, w)))
    return {"ids": ids, "paths": [paths[i] for i in ids], "words": len(affected),
            "keep": keep, "orphan": len(affected) - keep}


def delete_category(con, cid: int, move_to: int | None) -> dict:
    """刪除分類（大類連同小類）。還有其他分類的字只拿掉這個分類；只剩這個分類的字移到 move_to（預設「未分類」）。"""
    pre = delete_preview(con, cid)
    ids = pre["ids"]
    target = move_to or uncategorized_id(con)
    if target in ids or not con.execute("SELECT 1 FROM categories WHERE id=?", (target,)).fetchone():
        raise WordError("要移過去的分類不正確")
    affected = {r["word_id"] for r in con.execute(
        f"SELECT word_id FROM word_categories WHERE category_id IN ({','.join('?' * len(ids))})", ids)}
    for wid in affected:
        remaining = [i for i in _word_cat_ids(con, wid) if i not in ids]
        _write_categories(con, wid, remaining or [target])
    for i in reversed(ids):  # 先刪小類
        con.execute("DELETE FROM categories WHERE id=?", (i,))
    # 常用篩選組合裡拿掉被刪的分類
    for f in con.execute("SELECT id, data FROM saved_filters").fetchall():
        d = json.loads(f["data"])
        if any(i in ids for i in d.get("cats", [])):
            d["cats"] = [i for i in d["cats"] if i not in ids]
            con.execute("UPDATE saved_filters SET data=? WHERE id=?", (json.dumps(d, ensure_ascii=False), f["id"]))
    return pre


def apply_classification(con, items: list[dict]) -> int:
    """AI 分類的結果（使用者勾選後）：原本在「未分類」的字設成主分類，其他的字加成其他分類。"""
    uid = uncategorized_id(con)
    n = 0
    for it in items:
        cid = ensure_category(con, it["path"])
        cur = _word_cat_ids(con, it["word_id"])
        if cid in cur:
            continue
        real = [i for i in cur if i != uid]
        _write_categories(con, it["word_id"], [cid] + real if not real else real + [cid])
        n += 1
    return n


# ---------- 讀取 ----------

def norm_word(s: str) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    return s.strip(".,;:!?\"'“”‘’()[]{}")


def find(con, word: str):
    return con.execute("SELECT * FROM words WHERE word=? COLLATE NOCASE", (word,)).fetchone()


def _stats(r) -> dict:
    return {
        "light": srs.light(r),
        "correct_count": r["correct_count"],
        "wrong_count": r["wrong_count"],
        "forget_count": r["forget_count"],
        "added_day": r["added_day"],
        "due_day": r["due_day"],
        "graduated": r["correct_count"] >= srs.GRADUATE_AT,
    }


def load(con, wid: int, with_dict: bool = False):
    r = con.execute("SELECT * FROM words WHERE id=?", (wid,)).fetchone()
    if not r:
        return None
    paths = {c["id"]: c["path"] for c in categories(con)}
    cats = con.execute(
        "SELECT category_id,is_primary FROM word_categories WHERE word_id=? ORDER BY is_primary DESC",
        (wid,),
    ).fetchall()
    related = []
    for x in con.execute("SELECT other,zh,pos,rel,note FROM related WHERE word_id=? ORDER BY sort,id", (wid,)):
        hit = con.execute(
            "SELECT id FROM words WHERE word=? COLLATE NOCASE AND status='active'", (x["other"],)
        ).fetchone()
        related.append({"word": x["other"], "zh": x["zh"], "pos": x["pos"], "rel": x["rel"], "note": x["note"],
                        "exists_id": hit["id"] if hit else None})
    backlinks = [
        {"id": b["id"], "word": b["word"]}
        for b in con.execute(
            """SELECT DISTINCT w.id, w.word FROM related x JOIN words w ON w.id=x.word_id
               WHERE x.other=? COLLATE NOCASE AND w.status='active' AND w.id<>?""",
            (r["word"], wid),
        )
        if all(b["word"].lower() != x["word"].lower() for x in related)
    ]
    out = {
        "id": r["id"],
        "word": r["word"],
        "status": r["status"],
        "error": r["error"],
        "user_zh": r["user_zh"],
        "kk_user": r["kk_user"],
        "kk_ai": r["kk_ai"],
        "roots": r["roots"],
        "mnemonic": r["mnemonic"],
        "mnemonic_alts": json.loads(r["mnemonic_alts"]) if r["mnemonic_alts"] else None,
        "mem_state": r["mem_state"],
        "supplement": r["supplement"],
        "my_note": r["my_note"],
        "ai_suggest_category": r["ai_suggest_category"],
        "meanings": [
            {"pos": m["pos"], "zh": m["zh"], "domain": m["domain"],
             "is_primary": bool(m["is_primary"]), "source": m["source"]}
            for m in con.execute("SELECT * FROM meanings WHERE word_id=? ORDER BY sort,id", (wid,))
        ],
        "examples": [
            {"en": e["en"], "zh": e["zh"], "source": e["source"], "source_title": e["source_title"]}
            for e in con.execute(
                "SELECT * FROM examples WHERE word_id=? ORDER BY source='ai', sort, id", (wid,))
        ],
        "categories": {
            "primary": next((paths.get(c["category_id"]) for c in cats if c["is_primary"]), None),
            "others": [paths[c["category_id"]] for c in cats if not c["is_primary"] and c["category_id"] in paths],
        },
        "related": related,
        "backlinks": backlinks,
        "stats": _stats(r),
    }
    if with_dict:
        out["dict"] = dictionary.lookup(r["word"])
    return out


def summaries(con, status: str = "active") -> list[dict]:
    paths = {c["id"]: c["path"] for c in categories(con)}
    cats = defaultdict(list)
    primary_cat = {}
    for c in con.execute("SELECT word_id,category_id,is_primary FROM word_categories"):
        cats[c["word_id"]].append(c["category_id"])
        if c["is_primary"]:
            primary_cat[c["word_id"]] = c["category_id"]
    first_meaning = {}
    pos_list = defaultdict(list)
    for m in con.execute("SELECT word_id,pos,zh FROM meanings ORDER BY word_id, is_primary DESC, sort, id"):
        first_meaning.setdefault(m["word_id"], m)
        p = m["pos"].strip()
        if p and p not in pos_list[m["word_id"]]:
            pos_list[m["word_id"]].append(p)
    sources = defaultdict(list)
    has_context = set()
    for e in con.execute("SELECT word_id, source_title FROM examples WHERE source='context'"):
        has_context.add(e["word_id"])
        t = e["source_title"].strip()
        if t and t not in sources[e["word_id"]]:
            sources[e["word_id"]].append(t)
    answers = defaultdict(lambda: [0, 0])
    for a in con.execute(
        "SELECT word_id, kind, COUNT(*) n FROM events WHERE kind IN ('answer_ok','answer_ng') GROUP BY word_id, kind"
    ):
        answers[a["word_id"]][0] += a["n"]
        if a["kind"] == "answer_ng":
            answers[a["word_id"]][1] += a["n"]
    out = []
    for r in con.execute("SELECT * FROM words WHERE status=? ORDER BY id", (status,)):
        m = first_meaning.get(r["id"])
        pc = primary_cat.get(r["id"])
        out.append({
            "id": r["id"],
            "word": r["word"],
            "pos": m["pos"] if m else "",
            "zh": m["zh"] if m else "",
            "category": paths.get(pc, ""),
            "category_id": pc,
            "category_ids": cats.get(r["id"], []),
            "pos_list": pos_list.get(r["id"], []),
            "sources": sources.get(r["id"], []),
            "has_context": r["id"] in has_context,
            "answers": answers[r["id"]][0],
            "wrong_answers": answers[r["id"]][1],
            **_stats(r),
        })
    return out


def browse(con) -> list[dict]:
    """依分類排列；同分類裡，相關字排在一起，再照加入順序。"""
    cats = categories(con)
    words = summaries(con)
    by_cat = defaultdict(list)
    for w in words:
        by_cat[w["category_id"]].append(w)

    links = defaultdict(set)
    ids = {w["word"].lower(): w["id"] for w in words}
    for x in con.execute(
        "SELECT r.word_id, r.other FROM related r JOIN words w ON w.id=r.word_id WHERE w.status='active'"
    ):
        other = ids.get(x["other"].lower())
        if other and other != x["word_id"]:
            links[x["word_id"]].add(other)
            links[other].add(x["word_id"])

    def order(group: list[dict]) -> list[dict]:
        in_group = {w["id"]: w for w in group}
        seen, result = set(), []
        for w in group:  # group 已照 id（加入順序）排好
            if w["id"] in seen:
                continue
            queue = [w["id"]]
            seen.add(w["id"])
            while queue:
                cur = queue.pop(0)
                result.append(in_group[cur])
                for nb in sorted(links[cur]):
                    if nb in in_group and nb not in seen:
                        seen.add(nb)
                        queue.append(nb)
        return result

    # 「其他分類」的字也列在那個分類裡（排在主分類的字後面），例如 AI 分類加進「研究」的字
    secondary = defaultdict(list)
    for w in words:
        for cid in w["category_ids"]:
            if cid != w["category_id"]:
                secondary[cid].append({**w, "secondary": True})

    out = []
    for c in cats:
        if by_cat.get(c["id"]) or secondary.get(c["id"]):
            out.append({"category_id": c["id"], "path": c["path"],
                        "words": order(by_cat.get(c["id"], [])) + secondary.get(c["id"], [])})
    if by_cat.get(None):
        out.append({"category_id": None, "path": "未分類", "words": order(by_cat[None])})
    return out


def candidates(con, word: str, exclude_id: int | None = None) -> list[str]:
    """給 AI 參考：資料庫裡可能跟這個字相關的字。"""
    w = word.lower()
    found = []
    prefix = w[: min(len(w), 5)]
    if len(prefix) >= 4:
        for r in con.execute(
            "SELECT id, word FROM words WHERE status='active' AND lower(word) LIKE ? LIMIT 10",
            (prefix + "%",),
        ):
            if r["id"] != exclude_id:
                found.append(r["word"])
    for g in dictionary.resemble_for(word):
        for other in g["words"].split(","):
            other = other.strip()
            if other and other.lower() != w:
                hit = find(con, other)
                if hit and hit["status"] == "active":
                    found.append(hit["word"])
    for r in con.execute(
        """SELECT DISTINCT w.word FROM related x JOIN words w ON w.id=x.word_id
           WHERE x.other=? COLLATE NOCASE AND w.status='active'""",
        (word,),
    ):
        found.append(r["word"])
    uniq = []
    for f in found:
        if f.lower() != w and f.lower() not in (u.lower() for u in uniq):
            uniq.append(f)
    return uniq[:15]


def related_pool(con, word: str, exclude_id: int | None = None) -> list[dict]:
    """相關字只能從這裡挑（有資料依據的字）：
    - Wiktionary 列的同義、反義、相關、衍生字（常見的才留）、ECDICT 同家族字、原形
    - 你學過的字：上面清單裡有的，或字典意思真的相近的（不是只因為開頭字母一樣）
    回傳 [{word, learned}]，你學過的排前面。"""
    from . import etymology
    w = word.lower()
    base: list[tuple[str, str]] = []  # (字, 關係)
    lem = dictionary.lemma_of(word)
    if lem:
        base.append((lem["lemma"], "同家族"))
    rel = etymology.relations(word)
    base += [(x, "近義") for x in rel["synonyms"]] + [(x, "反義") for x in rel["antonyms"]]
    base += [(x, "相關") for x in rel["related"]]  # Wiktionary 的 related 不一定同家族
    base += [(x, "同家族") for x in rel["derived"] if dictionary.is_common(x)]
    base += [(x, "同家族") for x in dictionary.family_of(word)]
    pool, kinds, seen = [], {}, {w}
    for b, kind in base:
        bl = b.lower()
        if bl not in seen and " " not in b and len(b) > 2 and dictionary.lookup(b):
            seen.add(bl)
            pool.append(b)
            kinds[bl] = kind
    learned = []
    for c in candidates(con, word, exclude_id):
        if c.lower() in seen or (" " not in c and len(dictionary.meaning_chars(word) & dictionary.meaning_chars(c)) >= 2):
            learned.append(c)
    learned_l = {c.lower() for c in learned}
    # 你學過、但不在 candidates 裡的同家族字也標成學過
    for p in pool:
        if p.lower() not in learned_l and find(con, p) and find(con, p)["status"] == "active":
            learned.append(p)
            learned_l.add(p.lower())
    return ([{"word": c, "learned": True, "kind": kinds.get(c.lower(), "意思相近")} for c in learned]
            + [{"word": p, "learned": False, "kind": kinds[p.lower()]} for p in pool if p.lower() not in learned_l][:20])


# ---------- 寫入 ----------

def _replace_meanings(con, wid: int, meanings: list[dict]) -> None:
    con.execute("DELETE FROM meanings WHERE word_id=?", (wid,))
    for i, m in enumerate(meanings):
        con.execute(
            "INSERT INTO meanings(word_id,pos,zh,domain,is_primary,source,sort) VALUES (?,?,?,?,?,?,?)",
            (wid, m.get("pos", ""), m["zh"], m.get("domain", ""), int(bool(m.get("is_primary"))),
             m.get("source", "user"), i),
        )


def _replace_related(con, wid: int, related: list[dict]) -> None:
    con.execute("DELETE FROM related WHERE word_id=?", (wid,))
    from .relations import norm_pos, norm_rel, parse_note
    for i, x in enumerate(related):
        if "rel" not in x and "zh" not in x:  # 舊格式：只有一串 note
            x = {"word": x["word"], **parse_note(x.get("note", ""))}
        con.execute(
            "INSERT INTO related(word_id,other,zh,pos,rel,note,sort) VALUES (?,?,?,?,?,?,?)",
            (wid, x["word"].strip(), (x.get("zh") or "").strip(), norm_pos(x.get("pos", "")),
             norm_rel(x.get("rel", "")) or "相關", (x.get("note") or "").strip(), i),
        )


def apply_ai(con, wid: int, result: dict) -> None:
    _replace_meanings(con, wid, result["meanings"])
    contexts = con.execute(
        "SELECT id, zh FROM examples WHERE word_id=? AND source='context' ORDER BY sort,id", (wid,)
    ).fetchall()
    for ex, zh in zip(contexts, result.get("context_zh", [])):
        if zh and not ex["zh"]:
            con.execute("UPDATE examples SET zh=? WHERE id=?", (zh, ex["id"]))
    con.execute("DELETE FROM examples WHERE word_id=? AND source='ai'", (wid,))
    for i, e in enumerate(result["examples"]):
        con.execute(
            "INSERT INTO examples(word_id,en,zh,source,sort) VALUES (?,?,?,'ai',?)", (wid, e["en"], e["zh"], i)
        )
    _replace_related(con, wid, result["related"])
    set_categories(con, wid, result["primary_category"] or None, result["other_categories"])
    con.execute(
        """UPDATE words SET status='draft', error=NULL, kk_ai=?, supplement=?, mem_state='pending',
               ai_suggest_category=?, ai_raw=?, updated_at=datetime('now','localtime')
           WHERE id=?""",
        (result["kk"], result["supplement"],
         result["suggest_category"], json.dumps(result["raw"], ensure_ascii=False), wid),
    )


MEMORY_LABELS = (("family", "家族"), ("link", "聯想"))


def compose_mnemonic(alts: dict) -> str:
    """記憶法候選 → 記憶法欄位的預設內容（每種一行）。"""
    return "\n".join(f"{label}：{alts[k]}" for k, label in MEMORY_LABELS if alts.get(k))


def memory_ctx(con, wid: int) -> dict | None:
    r = con.execute("SELECT word FROM words WHERE id=?", (wid,)).fetchone()
    if not r:
        return None
    zh = "；".join(m["zh"] for m in con.execute(
        "SELECT zh FROM meanings WHERE word_id=? ORDER BY is_primary DESC, sort, id LIMIT 3", (wid,)))
    return memory_ctx_for(r["word"], zh)


def memory_ctx_for(word: str, zh: str) -> dict:
    """記憶法要給 AI 的參考：Wiktionary 字源（有的話）、ECDICT 字根、同家族字。"""
    from . import etymology
    family = dictionary.family_of(word)
    ctx = {"word": word, "meanings": zh, "roots": dictionary.roots_for_family(word), "family": family}
    if etymology.available():
        lem = dictionary.lemma_of(word)
        info = etymology.lookup(word, lem["lemma"] if lem else None)
        ctx["etym"] = etymology.describe(info) if info else ""
        ctx["etym_parts"] = bool(info and (
            info["parts"] or (info["source"] and info["source"].get("parts"))
            or " + " in info["text"]))  # 只寫在文字裡的組成，例如 from re- (“again”) + levō (“lift”)
        if info:  # Wiktionary 的衍生字（常見的才留）
            have = {f.lower() for f in family}
            ctx["family"] = (family + [d for d in info["derived"]
                                       if dictionary.is_common(d) and d.lower() not in have])[:12]
    return ctx


def apply_memory(con, wid: int, alts: dict, fill: bool) -> None:
    """存記憶法候選。fill=True 時，字根、記憶法還是空的才填入預設內容（不蓋掉你寫的）。"""
    r = con.execute("SELECT roots, mnemonic FROM words WHERE id=?", (wid,)).fetchone()
    if not r:
        return
    roots, mnemonic = r["roots"], r["mnemonic"]
    if fill and not roots.strip():
        roots = alts.get("roots", "")
    if fill and not mnemonic.strip():
        mnemonic = compose_mnemonic(alts)
    con.execute("UPDATE words SET mnemonic_alts=?, mem_state='done', roots=?, mnemonic=? WHERE id=?",
                (json.dumps(alts, ensure_ascii=False), roots, mnemonic, wid))


def fill_from_dict(con, wid: int) -> None:
    r = con.execute("SELECT word,user_zh FROM words WHERE id=?", (wid,)).fetchone()
    meanings = dictionary.meanings_from_dict(r["word"])
    if r["user_zh"]:
        for m in meanings:
            m["is_primary"] = False
        meanings.insert(0, {"pos": "", "zh": r["user_zh"], "domain": "", "is_primary": True, "source": "user"})
    if not meanings:
        raise WordError("字典查不到這個字，請手動填寫中文")
    _replace_meanings(con, wid, meanings)
    con.execute(
        "UPDATE words SET status='draft', error=NULL, updated_at=datetime('now','localtime') WHERE id=?", (wid,)
    )


def save(con, wid: int, p: dict) -> None:
    """儲存編輯器送來的完整內容。"""
    r = con.execute("SELECT * FROM words WHERE id=?", (wid,)).fetchone()
    if not r:
        raise WordError("找不到這個單字")
    word = norm_word(p["word"])
    if not word:
        raise WordError("英文不能是空的")
    if word.lower() != r["word"].lower():
        dup = find(con, word)
        if dup and dup["id"] != wid:
            raise WordError(f"「{word}」已經在資料庫裡了")
    meanings = [m for m in p["meanings"] if m["zh"].strip()]
    if not meanings:
        raise WordError("至少要有一個中文意思")
    if not any(m["is_primary"] for m in meanings):
        meanings[0]["is_primary"] = True
    for m in meanings:
        m["zh"] = m["zh"].strip()
        m["pos"] = m.get("pos", "").strip()
        m["domain"] = m.get("domain", "").strip()
    if not p["categories"]["primary"]:
        raise WordError("請選擇主分類")

    con.execute(
        """UPDATE words SET word=?, kk_user=?, roots=?, mnemonic=?, supplement=?, my_note=?,
               updated_at=datetime('now','localtime') WHERE id=?""",
        (word, p["kk_user"].strip(), p["roots"].strip(), p["mnemonic"].strip(),
         p["supplement"].strip(), p["my_note"].strip(), wid),
    )
    _replace_meanings(con, wid, meanings)
    con.execute("DELETE FROM examples WHERE word_id=?", (wid,))
    for i, e in enumerate(x for x in p["examples"] if x["en"].strip()):
        con.execute(
            "INSERT INTO examples(word_id,en,zh,source,source_title,sort) VALUES (?,?,?,?,?,?)",
            (wid, e["en"].strip(), e["zh"].strip(), e["source"], e["source_title"].strip(), i),
        )
    _replace_related(con, wid, [x for x in p["related"] if x["word"].strip()])
    set_categories(con, wid, p["categories"]["primary"], p["categories"]["others"])


def add_batch(con, source_title: str, items: list[dict]) -> list[dict]:
    """新增單字。回傳每個字的處理結果，以及要送去 AI 的 id。"""
    results = []
    seen = set()
    for it in items:
        word = norm_word(it["word"])
        if not word or word.lower() in seen:
            continue
        seen.add(word.lower())
        zh = it.get("zh", "").strip()
        contexts = []
        for c in it.get("contexts") or []:
            c = re.sub(r"\s+", " ", c).strip()
            if c and c not in contexts:
                contexts.append(c)
        existing = find(con, word)

        if existing and existing["status"] == "active":
            wid = existing["id"]
            srs.apply_reinput(con, wid)
            for c in contexts:
                if not con.execute("SELECT 1 FROM examples WHERE word_id=? AND en=?", (wid, c)).fetchone():
                    con.execute(
                        "INSERT INTO examples(word_id,en,source,source_title,sort) VALUES (?,?,'context',?,-1)",
                        (wid, c, source_title),
                    )
            if zh and not any(
                zh in m["zh"] or m["zh"] in zh
                for m in con.execute("SELECT zh FROM meanings WHERE word_id=?", (wid,))
            ):
                n = con.execute("SELECT COUNT(*) FROM meanings WHERE word_id=?", (wid,)).fetchone()[0]
                con.execute(
                    "INSERT INTO meanings(word_id,zh,is_primary,source,sort) VALUES (?,?,0,'user',?)",
                    (wid, zh, n),
                )
            row = con.execute("SELECT forget_count FROM words WHERE id=?", (wid,)).fetchone()
            results.append({"word": existing["word"], "id": wid, "action": "reinput",
                            "forget_count": row["forget_count"]})
        elif existing:
            results.append({"word": existing["word"], "id": existing["id"], "action": "pending"})
        else:
            wid = con.execute(
                "INSERT INTO words(word,status,user_zh,kk_user) VALUES (?,'generating',?,?)",
                (word, zh, it.get("kk", "").strip()),
            ).lastrowid
            for i, c in enumerate(contexts):
                con.execute(
                    "INSERT INTO examples(word_id,en,source,source_title,sort) VALUES (?,?,'context',?,?)",
                    (wid, c, source_title, i),
                )
            results.append({"word": word, "id": wid, "action": "queued"})
    return results
