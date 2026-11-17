"""AI 品質考卷：30 個單字（新增單字＋記憶法）＋ 8 個文章查字，結果存成 JSON 方便前後比較。
一定要在資料庫複本上跑：set VOCAB_DATA=<複本資料夾>，再執行 python tools/eval_ai.py 結果.json（THINK=0 可關掉記憶法的思考）"""
import json, os, sys, time
sys.path.insert(0, r"G:\學英文")
from app import ai, db, dictionary, words  # VOCAB_DATA 指向複本
ai.MEMORY_THINK = os.environ.get("THINK", "1") == "1"

CARD_WORDS = ["identify", "organize", "require", "depend", "expose", "suggest",
              "relevant", "appropriate", "suitable", "particular", "artificial", "reliable", "factual", "external", "uncertain",
              "duplication", "prediction", "judgment", "element", "assignment", "approach", "passage", "lack", "complexity",
              "algorithm", "traversal", "transpose", "whether", "be limited to", "one by one"]
ART = "Robots and Human Safety"
LOOKUPS = [
    ("share space", "They now work in hospitals, stores, and homes, where they may share space with people."),
    ("recognize", "A delivery robot, for example, must recognize obstacles and slow down when someone crosses its path."),
    ("crosses", "A delivery robot, for example, must recognize obstacles and slow down when someone crosses its path."),
    ("path", "A delivery robot, for example, must recognize obstacles and slow down when someone crosses its path."),
    ("sensors", "Engineers use cameras and sensors to help robots understand their surroundings."),
    ("fail", "However, sensors may fail, and people do not always move in predictable ways."),
    ("predictable", "However, sensors may fail, and people do not always move in predictable ways."),
    ("take control", "A reliable robot should be able to stop when it is uncertain and allow a human operator to take control."),
]

out = {"cards": [], "lookups": []}
with db.tx() as con:
    paths = words.category_paths(con)
    notes = words.category_notes(con)
    refs = {}
    for w in CARD_WORDS:
        r = words.find(con, w)
        refs[w] = {
            "my_meanings": [m["zh"] for m in con.execute("SELECT zh FROM meanings WHERE word_id=? ORDER BY is_primary DESC, sort", (r["id"],))],
            "contexts": [e["en"] for e in con.execute("SELECT en FROM examples WHERE word_id=? AND source='context'", (r["id"],))],
        }
for w in CARD_WORDS:
    info = dictionary.lookup(w)
    ctx = {"word": w, "user_zh": "", "contexts": refs[w]["contexts"],
           "dict_lines": info["translation"] if info else [],
           "resemble": dictionary.resemble_for(w), "lookalikes": dictionary.lookalikes(w),
           "candidates": [], "category_paths": paths, "category_notes": notes}
    t = time.time(); g = ai.generate(ctx); t1 = time.time() - t
    mctx = words.memory_ctx_for(w, "；".join(m["zh"] for m in g["meanings"][:3]))
    t = time.time(); m = ai.memory(mctx); t2 = time.time() - t
    out["cards"].append({"word": w, **refs[w], "t_main": round(t1, 1), "t_memory": round(t2, 1),
                         "meanings": [f"{x['pos']} {x['zh']}" for x in g["meanings"]],
                         "examples": [e["en"] for e in g["examples"]], "supplement": g["supplement"],
                         "category": g["primary_category"], "memory": m, "etym": mctx.get("etym", "")})
    print(f"{w:15} main {t1:4.1f}s mem {t2:4.1f}s", flush=True)
for w, s in LOOKUPS:
    q = {"lemma": (dictionary.lemma_of(w) or {"lemma": w})["lemma"]}
    info = dictionary.lookup(q["lemma"])
    t = time.time()
    r = ai.explain_in_context(w, q["lemma"], s, s, info["translation"] if info else [])
    from app import articles
    mean = articles._short_meaning(r["meaning"]) or articles._dict_first(info)
    out["lookups"].append({"word": w, "sentence": s, "t": round(time.time() - t, 1), "meaning": mean,
                           "raw_meaning": r["meaning"], "note": r["note"], "phrase": r["phrase"], "form": r["form"]})
    print(f"lookup {w:12} {time.time()-t:4.1f}s {mean}", flush=True)
json.dump(out, open(sys.argv[1], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("done")
