"""SQLite 資料庫：結構、初始化、預設分類。"""
import sqlite3
from contextlib import contextmanager

from . import config

SCHEMA_VERSION = 9  # 2：saved_filters（常用篩選組合）；3：系統內建「未分類」；4：分類說明；5：記憶法候選、文章；6：文章的片語與文法、閱讀位置；7：片語的中文欄；8：文章專用的灰色單字；9：相關字拆成中文、詞性、關係、說明
UNCATEGORIZED = "未分類"

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS categories(
    id INTEGER PRIMARY KEY,
    parent_id INTEGER REFERENCES categories(id),
    name TEXT NOT NULL,
    sort INTEGER NOT NULL DEFAULT 0,
    system INTEGER NOT NULL DEFAULT 0,             -- 1＝系統內建（未分類），不能刪除、改名
    description TEXT NOT NULL DEFAULT ''           -- 分類說明，AI 分類時參考（可留空）
);

CREATE TABLE IF NOT EXISTS words(
    id INTEGER PRIMARY KEY,
    word TEXT NOT NULL UNIQUE COLLATE NOCASE,
    status TEXT NOT NULL DEFAULT 'generating',   -- generating / draft / error / active
    error TEXT,
    user_zh TEXT NOT NULL DEFAULT '',            -- 輸入時使用者填的中文
    kk_user TEXT NOT NULL DEFAULT '',
    kk_ai TEXT NOT NULL DEFAULT '',
    roots TEXT NOT NULL DEFAULT '',
    mnemonic TEXT NOT NULL DEFAULT '',
    supplement TEXT NOT NULL DEFAULT '',
    my_note TEXT NOT NULL DEFAULT '',
    ai_suggest_category TEXT NOT NULL DEFAULT '',
    ai_raw TEXT,
    mnemonic_alts TEXT NOT NULL DEFAULT '',       -- AI 記憶法候選（JSON：roots/family/story/link）
    mem_state TEXT NOT NULL DEFAULT '',           -- 記憶法：pending / done / error / ''
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    -- 複習紀錄
    added_day TEXT,
    correct_count INTEGER NOT NULL DEFAULT 0,     -- 不同天累計答對
    wrong_count INTEGER NOT NULL DEFAULT 0,
    forget_count INTEGER NOT NULL DEFAULT 0,      -- 重複輸入次數
    is_red INTEGER NOT NULL DEFAULT 0,
    due_day TEXT,
    last_answer_day TEXT,
    relearn_day TEXT,                             -- 重複輸入那天，排進當天新字練習
    graduated_day TEXT
);

CREATE TABLE IF NOT EXISTS meanings(
    id INTEGER PRIMARY KEY,
    word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    pos TEXT NOT NULL DEFAULT '',
    zh TEXT NOT NULL,
    domain TEXT NOT NULL DEFAULT '',
    is_primary INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'ai',            -- ai / user / dict
    sort INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS examples(
    id INTEGER PRIMARY KEY,
    word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    en TEXT NOT NULL,
    zh TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'ai',            -- ai / context（原文句子）
    source_title TEXT NOT NULL DEFAULT '',
    sort INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS word_categories(
    word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    is_primary INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(word_id, category_id)
);

CREATE TABLE IF NOT EXISTS related(
    id INTEGER PRIMARY KEY,
    word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    other TEXT NOT NULL COLLATE NOCASE,
    zh TEXT NOT NULL DEFAULT '',                  -- 中文
    pos TEXT NOT NULL DEFAULT '',                 -- 詞性 n. v. adj. adv. phr.
    rel TEXT NOT NULL DEFAULT '',                 -- 關係：同家族／近義／反義／易混淆／相關
    note TEXT NOT NULL DEFAULT '',                -- 說明（選填）
    sort INTEGER NOT NULL DEFAULT 0
);

-- 判分用：AI 或你判定過的中文說法（第二版使用）
CREATE TABLE IF NOT EXISTS accepted_answers(
    word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    answer TEXT NOT NULL,
    correct INTEGER NOT NULL,
    source TEXT NOT NULL,                         -- ai / user
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    PRIMARY KEY(word_id, answer)
);

CREATE TABLE IF NOT EXISTS events(
    id INTEGER PRIMARY KEY,
    word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    day TEXT NOT NULL,
    kind TEXT NOT NULL,                           -- added / reinput / answer ...
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 自由複習的常用篩選組合
CREATE TABLE IF NOT EXISTS saved_filters(
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 文章閱讀
CREATE TABLE IF NOT EXISTS articles(
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    raw_text TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '[]',              -- 排版後：JSON [{"t":"h"|"p","text":...}]
    body_ai TEXT NOT NULL DEFAULT '',             -- AI 排版結果（按「套用」才換到 body）
    layout_state TEXT NOT NULL DEFAULT 'pending', -- pending（AI 排版中）/ ready（好了待套用）/ ai（已套用）/ rule（只用規則）
    layout_error TEXT,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    opened_at TEXT
);

-- 文章裡的片語與文法（手填筆記，不進複習）
CREATE TABLE IF NOT EXISTS article_phrases(
    id INTEGER PRIMARY KEY,
    article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    text TEXT NOT NULL,                           -- 片語或文法，例如 no longer、It is ... that ...
    zh TEXT NOT NULL DEFAULT '',                  -- 中文意思
    note TEXT NOT NULL DEFAULT '',                -- 說明
    sentence TEXT NOT NULL DEFAULT '',            -- 原句
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_article_phrases ON article_phrases(article_id);

-- 在文章裡查過、加入的字
CREATE TABLE IF NOT EXISTS article_words(
    id INTEGER PRIMARY KEY,
    article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    lemma TEXT NOT NULL COLLATE NOCASE,           -- 原形
    surface TEXT NOT NULL DEFAULT '',             -- 文章裡的樣子（studies）
    sentence TEXT NOT NULL DEFAULT '',
    meaning TEXT NOT NULL DEFAULT '',             -- 這篇文章裡的意思（AI 依上下文判斷）
    note TEXT NOT NULL DEFAULT '',                -- 你在這篇文章的備註
    local INTEGER NOT NULL DEFAULT 0,             -- 1＝只記在這篇（灰色，不進單字庫，例如專有名詞）
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(article_id, lemma)
);

CREATE INDEX IF NOT EXISTS idx_meanings_word ON meanings(word_id);
CREATE INDEX IF NOT EXISTS idx_events_day ON events(day);
CREATE INDEX IF NOT EXISTS idx_examples_word ON examples(word_id);
CREATE INDEX IF NOT EXISTS idx_related_word ON related(word_id);
CREATE INDEX IF NOT EXISTS idx_related_other ON related(other);
CREATE INDEX IF NOT EXISTS idx_words_status ON words(status);
CREATE INDEX IF NOT EXISTS idx_events_word ON events(word_id);
"""

DEFAULT_CATEGORIES = [
    ("科技", ["資料庫", "機器學習", "程式設計", "網路", "資安", "硬體", "雲端"]),
    ("商業", ["經濟", "金融", "管理", "行銷"]),
    ("學術", ["研究方法", "數學統計"]),
    ("生活", ["旅遊", "飲食", "健康", "情緒"]),
    ("通用", ["動作", "描述", "抽象概念"]),
]


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(config.DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


@contextmanager
def tx():
    con = connect()
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init() -> None:
    config.DATA.mkdir(exist_ok=True)
    if config.DB_PATH.exists():
        con = connect()
        try:
            has_meta = con.execute("SELECT 1 FROM sqlite_master WHERE name='meta'").fetchone()
            ver = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone() if has_meta else None
        finally:
            con.close()
        if ver and int(ver["value"]) < SCHEMA_VERSION:
            from . import backup
            backup.pre_upgrade_backup()  # 改資料庫結構前先備份
    with tx() as con:
        con.executescript(SCHEMA)
        row = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if row is not None and int(row["value"]) < SCHEMA_VERSION:
            con.execute("UPDATE meta SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))
        if row is None:
            for i, (top, children) in enumerate(DEFAULT_CATEGORIES):
                tid = con.execute(
                    "INSERT INTO categories(parent_id,name,sort) VALUES (NULL,?,?)", (top, i)
                ).lastrowid
                for j, child in enumerate(children):
                    con.execute(
                        "INSERT INTO categories(parent_id,name,sort) VALUES (?,?,?)", (tid, child, j)
                    )
            con.execute(
                "INSERT INTO meta(key,value) VALUES ('schema_version',?)", (str(SCHEMA_VERSION),)
            )
        _ensure_uncategorized(con)
        _ensure_v5(con)
        _ensure_v6(con)
        # 之後版本若要改資料庫結構：先 backup.pre_upgrade_backup()，再在這裡做轉換


def _ensure_v5(con) -> None:
    """版本 5：記憶法候選（文章的資料表由 SCHEMA 建立）。"""
    cols = {r["name"] for r in con.execute("PRAGMA table_info(words)")}
    if "mnemonic_alts" not in cols:
        con.execute("ALTER TABLE words ADD COLUMN mnemonic_alts TEXT NOT NULL DEFAULT ''")
    if "mem_state" not in cols:
        con.execute("ALTER TABLE words ADD COLUMN mem_state TEXT NOT NULL DEFAULT ''")


def _ensure_v6(con) -> None:
    """版本 6：文章記住讀到哪一段（片語表由 SCHEMA 建立）。"""
    cols = {r["name"] for r in con.execute("PRAGMA table_info(articles)")}
    if "read_pi" not in cols:
        con.execute("ALTER TABLE articles ADD COLUMN read_pi INTEGER NOT NULL DEFAULT 0")
    # 版本 7：片語的中文欄
    if "zh" not in {r["name"] for r in con.execute("PRAGMA table_info(article_phrases)")}:
        con.execute("ALTER TABLE article_phrases ADD COLUMN zh TEXT NOT NULL DEFAULT ''")
    # 版本 8：文章專用的灰色單字
    if "local" not in {r["name"] for r in con.execute("PRAGMA table_info(article_words)")}:
        con.execute("ALTER TABLE article_words ADD COLUMN local INTEGER NOT NULL DEFAULT 0")
    # 版本 9：相關字拆欄位，舊的「中文（標籤）」自動轉換
    cols = {r["name"] for r in con.execute("PRAGMA table_info(related)")}
    if "rel" not in cols:
        for c in ("zh", "pos", "rel"):
            con.execute(f"ALTER TABLE related ADD COLUMN {c} TEXT NOT NULL DEFAULT ''")
        from .relations import dict_brief, parse_note
        for r in con.execute("SELECT id, other, note FROM related").fetchall():
            x = parse_note(r["note"])
            if not x["pos"] or not x["zh"]:
                d = dict_brief(r["other"], x["zh"])
                x["pos"] = x["pos"] or d["pos"]
                x["zh"] = x["zh"] or d["zh"]
            con.execute("UPDATE related SET zh=?, pos=?, rel=?, note=? WHERE id=?",
                        (x["zh"], x["pos"], x["rel"], x["note"], r["id"]))


def _ensure_uncategorized(con) -> None:
    """版本 3：系統內建的「未分類」（不能刪除、不能改名），沒有分類的字都放這裡。"""
    cols = {r["name"] for r in con.execute("PRAGMA table_info(categories)")}
    if "system" not in cols:
        con.execute("ALTER TABLE categories ADD COLUMN system INTEGER NOT NULL DEFAULT 0")
    if "description" not in cols:  # 版本 4
        con.execute("ALTER TABLE categories ADD COLUMN description TEXT NOT NULL DEFAULT ''")
    row = con.execute("SELECT id FROM categories WHERE system=1").fetchone()
    if not row:
        same = con.execute(
            "SELECT id FROM categories WHERE parent_id IS NULL AND name=?", (UNCATEGORIZED,)
        ).fetchone()
        if same:
            con.execute("UPDATE categories SET system=1, sort=9999 WHERE id=?", (same["id"],))
            uid = same["id"]
        else:
            uid = con.execute(
                "INSERT INTO categories(parent_id,name,sort,system) VALUES (NULL,?,9999,1)", (UNCATEGORIZED,)
            ).lastrowid
    else:
        uid = row["id"]
    # 已存入但沒有任何分類的字 → 未分類
    con.execute(
        """INSERT INTO word_categories(word_id,category_id,is_primary)
           SELECT id, ?, 1 FROM words
           WHERE status='active' AND id NOT IN (SELECT word_id FROM word_categories)""",
        (uid,),
    )
