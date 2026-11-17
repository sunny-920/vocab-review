"""網頁伺服器與 API。只在本機 127.0.0.1 執行。"""
import json
import mimetypes
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import ai, articles, backup, classify, config, db, dictionary, export, review, srs, stats, tts, words, worker

# Windows 的登錄檔有時把 .js 設成 text/plain，瀏覽器會拒絕載入模組
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/manifest+json", ".webmanifest")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    backup.daily_backup(srs.today_str())
    worker.start()
    articles.resume_jobs()
    tts.clean_old_cache()
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def no_cache(request: Request, call_next):
    res = await call_next(request)
    res.headers["Cache-Control"] = "no-store"  # 程式更新後不會讀到舊的網頁
    return res


@app.exception_handler(words.WordError)
async def word_error(request: Request, exc: words.WordError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(articles.ArticleError)
async def article_error(request: Request, exc: articles.ArticleError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# ---------- 資料格式 ----------

class Meaning(BaseModel):
    pos: str = ""
    zh: str
    domain: str = ""
    is_primary: bool = False
    source: str = "user"


class Example(BaseModel):
    en: str
    zh: str = ""
    source: str = "ai"
    source_title: str = ""


class Related(BaseModel):
    word: str
    zh: str = ""
    pos: str = ""
    rel: str = ""
    note: str = ""


class Cats(BaseModel):
    primary: str | None = None
    others: list[str] = []


class WordSave(BaseModel):
    word: str
    kk_user: str = ""
    meanings: list[Meaning]
    examples: list[Example] = []
    categories: Cats
    roots: str = ""
    mnemonic: str = ""
    supplement: str = ""
    my_note: str = ""
    related: list[Related] = []


class BatchItem(BaseModel):
    word: str
    kk: str = ""
    zh: str = ""
    contexts: list[str] = []


class Batch(BaseModel):
    source_title: str = ""
    items: list[BatchItem]


class Answer(BaseModel):
    word_id: int
    mode: str            # en2zh / zh2en / cloze / listen（聽寫）
    answer: str = ""
    expected: str = ""   # 中→英、填空的正確答案（填空要填句子裡的形態）
    session: str         # daily / free
    retry: bool = False


class Override(BaseModel):
    event_id: int
    correct: bool


class FreeReview(BaseModel):
    ids: list[int]
    shuffle: bool = False


class Progress(BaseModel):
    count: int


class Light(BaseModel):
    light: str  # red / yellow / green


class SavedFilter(BaseModel):
    name: str
    data: dict


class ExportReq(BaseModel):
    ids: list[int] | None = None


class ClassifyItem(BaseModel):
    word_id: int
    path: str


class ClassifyApply(BaseModel):
    items: list[ClassifyItem]


class NewCategory(BaseModel):
    path: str


class RenameCategory(BaseModel):
    name: str


class CategoryDescription(BaseModel):
    description: str = ""


# ---------- 狀態 ----------

@app.get("/api/status")
def status():
    today = srs.today_str()
    backup.daily_backup(today)  # 程式跨日一直開著時也會備份
    with db.tx() as con:
        rows = words.summaries(con)
        drafts = con.execute(
            "SELECT status, COUNT(*) n FROM words WHERE status<>'active' GROUP BY status"
        ).fetchall()
        today_ids = {
            r["id"] for r in con.execute(
                "SELECT id FROM words WHERE status='active' AND (added_day=? OR relearn_day=?)", (today, today))
        }
        daily = review.daily_state(con)
    counts = {"red": 0, "yellow": 0, "green": 0}
    for r in rows:
        counts[r["light"]] += 1
    return {
        "review": {k: v for k, v in daily.items() if k != "pending"},
        "today": today,
        "ai": ai.status(),
        "dictionary": dictionary.available(),
        "total": len(rows),
        "lights": counts,
        "pending": {d["status"]: d["n"] for d in drafts},
        "today_words": [r for r in rows if r["id"] in today_ids],
    }


# ---------- 新增 ----------

@app.get("/api/check")
def check(word: str):
    w = words.norm_word(word)
    if not w:
        return {"word": ""}
    with db.tx() as con:
        ex = words.find(con, w)
        lemma = dictionary.lemma_of(w)
        if lemma:
            hit = words.find(con, lemma["lemma"])
            lemma["existing"] = bool(hit and hit["status"] == "active")
    info = dictionary.lookup(w)
    return {
        "word": w,
        "existing": None if not ex else {
            "id": ex["id"], "status": ex["status"], "forget_count": ex["forget_count"], "light": srs.light(ex),
        },
        "lemma": lemma,
        "dict": info,
    }


@app.post("/api/warmup")
def warmup():
    ai.warmup()
    return {"ok": True}


@app.post("/api/words/batch")
def add_batch(b: Batch):
    with db.tx() as con:
        results = words.add_batch(con, b.source_title.strip(), [i.model_dump() for i in b.items])
    for r in results:
        if r["action"] == "queued":
            worker.enqueue(r["id"])
    return {"results": results}


@app.get("/api/drafts")
def drafts():
    with db.tx() as con:
        ids = [r["id"] for r in con.execute(
            "SELECT id FROM words WHERE status IN ('generating','draft','error') ORDER BY id")]
        out = []
        for wid in ids:
            w = words.load(con, wid, with_dict=True)
            w["queue_position"] = worker.position(wid)
            out.append(w)
    return out


@app.post("/api/words/{wid}/regenerate")
def regenerate(wid: int):
    with db.tx() as con:
        r = con.execute("SELECT status FROM words WHERE id=?", (wid,)).fetchone()
        if not r:
            raise HTTPException(404, "找不到這個單字")
        con.execute("UPDATE words SET status='generating', error=NULL WHERE id=?", (wid,))
    worker.enqueue(wid)
    return {"ok": True}


@app.post("/api/words/{wid}/memory")
def regenerate_memory(wid: int):
    """重新產生記憶法候選（約 10～40 秒）。只存候選，不改你的字根和記憶法欄位。"""
    with db.tx() as con:
        ctx = words.memory_ctx(con, wid)
    if not ctx:
        raise HTTPException(404, "找不到這個單字")
    try:
        alts = ai.memory(ctx)
    except ai.AIError as e:
        raise HTTPException(502, str(e))
    with db.tx() as con:
        words.apply_memory(con, wid, alts, fill=False)
    return alts


@app.post("/api/words/{wid}/dict-fill")
def dict_fill(wid: int):
    with db.tx() as con:
        words.fill_from_dict(con, wid)
        return words.load(con, wid, with_dict=True)


@app.post("/api/words/{wid}/confirm")
def confirm(wid: int, p: WordSave):
    with db.tx() as con:
        words.save(con, wid, p.model_dump())
        srs.activate_new(con, wid)
        return words.load(con, wid)


# ---------- 單字 ----------

@app.get("/api/words")
def list_words():
    with db.tx() as con:
        return words.summaries(con)


@app.get("/api/words/{wid}")
def get_word(wid: int):
    with db.tx() as con:
        w = words.load(con, wid, with_dict=True)
    if not w:
        raise HTTPException(404, "找不到這個單字")
    return w


@app.put("/api/words/{wid}")
def update_word(wid: int, p: WordSave):
    with db.tx() as con:
        words.save(con, wid, p.model_dump())
        return words.load(con, wid, with_dict=True)


@app.post("/api/words/{wid}/progress")
def set_progress(wid: int, p: Progress):
    with db.tx() as con:
        r = con.execute("SELECT status FROM words WHERE id=?", (wid,)).fetchone()
        if not r or r["status"] != "active":
            raise HTTPException(404, "找不到這個單字")
        srs.set_progress(con, wid, p.count)
        return words.load(con, wid, with_dict=True)


@app.post("/api/words/{wid}/light")
def set_light(wid: int, p: Light):
    if p.light not in ("red", "yellow", "green"):
        raise HTTPException(400, "燈號錯誤")
    with db.tx() as con:
        r = con.execute("SELECT status FROM words WHERE id=?", (wid,)).fetchone()
        if not r or r["status"] != "active":
            raise HTTPException(404, "找不到這個單字")
        srs.set_light(con, wid, p.light)
        return words.load(con, wid, with_dict=True)


@app.delete("/api/words/{wid}")
def delete_word(wid: int):
    with db.tx() as con:
        r = con.execute("SELECT word FROM words WHERE id=?", (wid,)).fetchone()
        con.execute("DELETE FROM words WHERE id=?", (wid,))
    if r:
        tts.forget(r["word"])  # 發音快取也一起刪
    return {"ok": True}


@app.get("/api/browse")
def browse():
    with db.tx() as con:
        return words.browse(con)


# ---------- 複習 ----------

@app.get("/api/review/daily")
def review_daily(shuffle: bool = False):
    with db.tx() as con:
        return review.daily_round(con, shuffle)


@app.post("/api/review/free")
def review_free(f: FreeReview):
    with db.tx() as con:
        return review.free_list(con, f.ids, f.shuffle)


@app.post("/api/review/answer")
def review_answer(a: Answer):
    if a.mode not in ("en2zh", "zh2en", "cloze", "listen") or a.session not in ("daily", "free"):
        raise HTTPException(400, "參數錯誤")
    with db.tx() as con:
        return review.answer(con, a.word_id, a.mode, a.answer, a.expected, a.session, a.retry)


@app.post("/api/review/override")
def review_override(o: Override):
    with db.tx() as con:
        return review.override(con, o.event_id, o.correct)


@app.get("/api/filters")
def list_filters():
    with db.tx() as con:
        return [
            {"id": r["id"], "name": r["name"], "data": json.loads(r["data"])}
            for r in con.execute("SELECT * FROM saved_filters ORDER BY id")
        ]


@app.post("/api/filters")
def add_filter(f: SavedFilter):
    name = f.name.strip()
    if not name:
        raise HTTPException(400, "請輸入名稱")
    with db.tx() as con:
        con.execute("DELETE FROM saved_filters WHERE name=?", (name,))  # 同名就覆蓋
        fid = con.execute(
            "INSERT INTO saved_filters(name,data) VALUES (?,?)", (name, json.dumps(f.data, ensure_ascii=False))
        ).lastrowid
    return {"id": fid}


@app.delete("/api/filters/{fid}")
def delete_filter(fid: int):
    with db.tx() as con:
        con.execute("DELETE FROM saved_filters WHERE id=?", (fid,))
    return {"ok": True}


# ---------- 統計、匯出 ----------

@app.get("/api/stats")
def get_stats():
    with db.tx() as con:
        return stats.build(con)


@app.post("/api/export")
def export_csv(req: ExportReq):
    with db.tx() as con:
        text = export.to_csv(con, req.ids)
    name = f"單字庫-{srs.today_str()}.csv"
    return Response(
        content=text.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=\"vocab.csv\"; filename*=UTF-8''{quote(name)}"},
    )


# ---------- 分類 ----------

@app.get("/api/categories")
def list_categories():
    with db.tx() as con:
        cats = words.categories(con)
        counts = {}
        for r in con.execute(
            """SELECT wc.category_id, COUNT(*) n FROM word_categories wc
               JOIN words w ON w.id=wc.word_id WHERE w.status='active' GROUP BY wc.category_id"""
        ):
            counts[r["category_id"]] = r["n"]
    for c in cats:
        c["count"] = counts.get(c["id"], 0)
    return cats


@app.post("/api/categories")
def add_category(c: NewCategory):
    with db.tx() as con:
        cid = words.ensure_category(con, c.path)
    return {"id": cid}


@app.get("/api/categories/{cid}/delete-preview")
def category_delete_preview(cid: int):
    with db.tx() as con:
        return words.delete_preview(con, cid)


@app.delete("/api/categories/{cid}")
def delete_category(cid: int, move_to: int | None = None):
    with db.tx() as con:
        return words.delete_category(con, cid, move_to)


@app.post("/api/categories/{cid}/classify")
def classify_category(cid: int):
    return {"job_id": classify.start(cid)}


@app.get("/api/classify/{job_id}")
def classify_status(job_id: str):
    job = classify.get(job_id)
    if not job:
        raise HTTPException(404, "找不到這次分類（程式可能重新啟動過）")
    return job


@app.post("/api/classify/apply")
def classify_apply(a: ClassifyApply):
    with db.tx() as con:
        n = words.apply_classification(con, [i.model_dump() for i in a.items])
    return {"applied": n}


@app.put("/api/categories/{cid}/description")
def set_category_description(cid: int, d: CategoryDescription):
    with db.tx() as con:
        words.set_description(con, cid, d.description)
    return {"ok": True}


@app.put("/api/categories/{cid}")
def rename_category(cid: int, c: RenameCategory):
    with db.tx() as con:
        words.rename_category(con, cid, c.name)
    return {"ok": True}


# ---------- 設定 ----------

@app.get("/api/settings")
def get_settings():
    return {
        "settings": config.load_settings(),
        "models": ai.list_models(),
        "paths": {"database": str(config.DB_PATH), "backups": str(config.BACKUP_DIR)},
    }


@app.put("/api/settings")
def put_settings(patch: dict):
    return config.save_settings(patch)


# ---------- 網頁 ----------

app.mount("/static", StaticFiles(directory=config.STATIC), name="static")


# ---------- 文章 ----------

class NewArticle(BaseModel):
    title: str = ""
    source: str = ""
    text: str


class ArticleUpdate(BaseModel):
    title: str | None = None
    source: str | None = None
    note: str | None = None


class ReadPos(BaseModel):
    pi: int


class ArticleBody(BaseModel):
    markdown: str


class Phrase(BaseModel):
    text: str
    zh: str = ""
    note: str = ""
    sentence: str = ""


class Translate(BaseModel):
    text: str
    context: str = ""


class Lookup(BaseModel):
    text: str
    sentence: str = ""
    paragraph: str = ""


class ArticleWordAdd(BaseModel):
    lemma: str
    surface: str = ""
    sentence: str = ""
    meaning: str = ""


class ArticleWordNote(BaseModel):
    note: str


@app.get("/api/articles")
def article_list():
    with db.tx() as con:
        return articles.summary_list(con)


@app.post("/api/articles")
def article_create(a: NewArticle):
    with db.tx() as con:
        aid = articles.create(con, a.title, a.source, a.text)
    articles.start_layout(aid)
    return {"id": aid}


@app.get("/api/articles/{aid}")
def article_get(aid: int, touch: bool = False):
    with db.tx() as con:
        return articles.load(con, aid, touch=touch)


@app.put("/api/articles/{aid}")
def article_update(aid: int, a: ArticleUpdate):
    with db.tx() as con:
        articles.update(con, aid, a.title, a.source, a.note)
        return articles.load(con, aid)


@app.delete("/api/articles/{aid}")
def article_delete(aid: int):
    with db.tx() as con:
        articles.delete(con, aid)
    return {"ok": True}


@app.post("/api/articles/{aid}/layout/apply")
def article_apply_layout(aid: int):
    with db.tx() as con:
        articles.apply_ai_layout(con, aid)
        return articles.load(con, aid)


@app.post("/api/articles/{aid}/layout/dismiss")
def article_dismiss_layout(aid: int):
    with db.tx() as con:
        con.execute("UPDATE articles SET layout_state='rule' WHERE id=? AND layout_state='ready'", (aid,))
    return {"ok": True}


@app.post("/api/articles/{aid}/layout/redo")
def article_redo_layout(aid: int):
    with db.tx() as con:
        con.execute("UPDATE articles SET layout_state='pending', layout_error=NULL WHERE id=?", (aid,))
    articles.start_layout(aid)
    return {"ok": True}


@app.get("/api/dict/brief")
def dict_brief(word: str):
    """編輯相關字時：字典查得到嗎（拼字提醒）、帶入詞性和中文、單字庫裡有沒有。"""
    from .relations import dict_brief as brief
    out = brief(word)
    with db.tx() as con:
        hit = con.execute("SELECT id FROM words WHERE word=? COLLATE NOCASE AND status='active'", (word.strip(),)).fetchone()
    out["exists_id"] = hit["id"] if hit else None
    return out


@app.get("/api/tts/status")
def tts_status():
    return tts.status()


@app.get("/api/tts")
def tts_speak(text: str, voice: str = tts.DEFAULT_VOICE, speed: float = 1.0, kind: str = "sentence"):
    """念英文：kind=word 會存起來（下次直接播），sentence（文章）即時產生、不存。"""
    if not tts.available():
        raise HTTPException(503, "還沒有本機語音模型")
    try:
        data = tts.synthesize(text, voice, speed, cache=(kind == "word"))
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    headers ={"Cache-Control": "private, max-age=86400"} if kind == "word" else {"Cache-Control": "no-store"}
    return Response(data, media_type="audio/wav", headers=headers)


@app.post("/api/lookup")
def lookup_quick(q: Lookup):
    with db.tx() as con:
        return articles.quick_lookup(con, q.text)


@app.put("/api/articles/{aid}/body")
def article_set_body(aid: int, b: ArticleBody):
    with db.tx() as con:
        articles.set_body(con, aid, b.markdown)
        return articles.load(con, aid)


@app.put("/api/articles/{aid}/read-pos")
def article_read_pos(aid: int, p: ReadPos):
    with db.tx() as con:
        articles.set_read_pos(con, aid, p.pi)
    return {"ok": True}


@app.get("/api/phrases")
def phrase_list_all():
    with db.tx() as con:
        return articles.all_phrases(con)


@app.post("/api/articles/{aid}/phrases")
def phrase_add(aid: int, p: Phrase):
    with db.tx() as con:
        return articles.add_phrase(con, aid, p.text, p.zh, p.note, p.sentence)


@app.put("/api/phrases/{pid}")
def phrase_update(pid: int, p: Phrase):
    with db.tx() as con:
        return articles.update_phrase(con, pid, p.text, p.zh, p.note, p.sentence)


@app.delete("/api/phrases/{pid}")
def phrase_delete(pid: int):
    with db.tx() as con:
        articles.delete_phrase(con, pid)
    return {"ok": True}


@app.post("/api/translate")
def translate(t: Translate):
    text = " ".join(t.text.split())
    if not text:
        raise HTTPException(400, "沒有要翻譯的文字")
    if len(text) > 1500:
        raise HTTPException(400, "一次最多翻譯 1500 個字元，請選短一點")
    try:
        return {"zh": ai.translate(text, t.context)}
    except ai.AIError as e:
        raise HTTPException(502, str(e))


@app.post("/api/lookup/explain")
def lookup_explain(q: Lookup):
    with db.tx() as con:
        articles.quick_lookup(con, q.text)  # 檢查有選到字
    try:
        with db.tx() as con:
            return articles.explain(con, q.text, q.sentence, q.paragraph)
    except ai.AIError as e:
        raise HTTPException(502, str(e))


class WordMeaning(BaseModel):
    meaning: str


class AddMeaning(BaseModel):
    pos: str = ""
    zh: str
    surface: str = ""
    sentence: str = ""


@app.post("/api/articles/{aid}/words/{wid}/meaning")
def article_add_meaning(aid: int, wid: int, m: AddMeaning):
    """把「在這句的意思」加到單字庫裡的字（不設成主要意思）。"""
    with db.tx() as con:
        return articles.add_meaning(con, aid, wid, m.pos, m.zh, m.surface, m.sentence)


@app.post("/api/articles/{aid}/words/local")
def article_add_local_word(aid: int, w: ArticleWordAdd):
    with db.tx() as con:
        return articles.add_local_word(con, aid, w.lemma, w.surface, w.sentence, w.meaning)


@app.put("/api/articles/{aid}/words/{awid}/meaning")
def article_word_meaning(aid: int, awid: int, m: WordMeaning):
    with db.tx() as con:
        articles.set_word_meaning(con, aid, awid, m.meaning)
    return {"ok": True}


@app.post("/api/articles/{aid}/words")
def article_add_word(aid: int, w: ArticleWordAdd):
    with db.tx() as con:
        res = articles.add_word(con, aid, w.lemma, w.surface, w.sentence, w.meaning)
    if res["action"] == "queued":
        worker.enqueue(res["id"])
    return res


@app.put("/api/articles/{aid}/words/{awid}")
def article_word_note(aid: int, awid: int, n: ArticleWordNote):
    with db.tx() as con:
        articles.set_word_note(con, aid, awid, n.note)
    return {"ok": True}


@app.delete("/api/articles/{aid}/words/{awid}")
def article_word_remove(aid: int, awid: int):
    with db.tx() as con:
        articles.remove_word(con, aid, awid)
    return {"ok": True}


@app.get("/api/scan-targets")
def scan_targets():
    with db.tx() as con:
        return articles.scan_targets(con)


@app.get("/")
def index():
    return FileResponse(config.STATIC / "index.html")
