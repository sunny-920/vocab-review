"""呼叫本機 Ollama 產生單字卡內容。"""
import json
import re
import threading
import urllib.error
import urllib.request

from . import config
from .dictionary import to_tw

SCHEMA = {
    "type": "object",
    "properties": {
        "kk": {"type": "string"},
        "meanings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "pos": {"type": "string"},
                    "zh": {"type": "string"},
                    "domain": {"type": "string"},
                    "primary": {"type": "boolean"},
                },
                "required": ["pos", "zh", "domain", "primary"],
            },
        },
        "primary_category": {"type": "string"},
        "other_categories": {"type": "array", "items": {"type": "string"}},
        "examples": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"en": {"type": "string"}, "zh": {"type": "string"}},
                "required": ["en", "zh"],
            },
        },
        "supplement": {"type": "string"},
        "context_zh": {"type": "array", "items": {"type": "string"}},
        "related": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"word": {"type": "string"}, "note": {"type": "string"}},
                "required": ["word", "note"],
            },
        },
    },
    "required": [
        "kk", "meanings", "primary_category", "other_categories", "examples", "supplement", "context_zh", "related",
    ],
}

SYSTEM_PROMPT = """你是幫台灣使用者整理英文單字卡的助手。使用者正在讀英文文章（常見主題：資料庫、機器學習等技術文章，也有一般文章），想把遇到的生字背起來。

請用 JSON 輸出，規則：
1. 所有中文一律使用繁體中文、台灣用語（資料庫、程式、軟體、網路、檔案、預設），不可出現簡體字。
2. meanings：列出這個字「常用」的意思，每個意思一筆，最多 5 筆，不要列罕見意思。
   - zh：只寫 1～3 個簡短說法，用「、」分隔，例如「檢查、審查」。不要寫成解釋句。
   - pos：詞性縮寫，例如 n. / v. / adj. / adv. / prep. / conj.
   - domain：只有「這個意思是某領域的專門用法、一般人平常不會這樣用」時才填領域名稱，例如 table 的「資料表」填「資料庫」、operator 的「運算子」填「程式設計」。
     意思本身就是一般用法時（algorithm 的「演算法」、service 的「服務」、approach 的「方法」）填空字串。不要因為原文句子在講某個領域，就把每個意思都標上那個領域。
   - primary：最常用、最需要記住的 1～2 個意思設為 true。有提供原文句子時，句子裡用到的那個意思一定要 primary=true 並排在第一個。
   - 有「使用者提供的中文」時，必須包含這個意思並設為 primary=true。
3. primary_category：從「可用分類」清單挑一個最適合的，原樣照抄（格式「大類/小類」）。有原文句子時以句子的領域為準。只有清單裡完全沒有合適的，才自己寫一個新的「大類/小類」。
   other_categories：其他也適合的分類，最多 2 個，沒有就給空陣列。
   有些分類後面附了「說明」，請照說明判斷：符合說明的字才放進去，說明寫「不包含」的就不要放。
4. examples：1～2 個自然、簡單的例句，必須用到這個單字（可以是變化形），附繁體中文翻譯。專業領域的字請用該領域的情境造句。不要重複使用者的原文句子。
5. supplement（補充）：只寫「容易混淆的字」，幫學生分清楚。有兩種：
   - 拼字很像、常被看錯或寫錯的：adapt（適應） vs adopt（採用）、principal（主要的） vs principle（原則）、lose（失去） vs loose（鬆的）
   - 意思很像、常用錯的：consistent（一致的） vs constant（持續不變的）、affect（影響，動詞） vs effect（影響，名詞）
   格式：「這個字（意思） vs 混淆字（意思）：一句話說差別（20 字以內）」，最多 2 組（用 vs，不要用 ↔；↔ 只用在相反詞），用「；」分隔（程式會分成一組一行）。一定要包含這個字本身。
   「拼字很像的字」裡如果有真的常被搞混的（例如 principal/principle、complement/compliment、adapt/adopt），一定要放第一組。
   只挑「真的會搞混」的：拼字很像，或意思很接近、常常用錯的。「拼字很像的字」「近義字辨析」可以參考，但裡面很多字其實不會搞混（例如 reliable 和 suitable 只是都用 -able 結尾），不要硬放。沒有就給空字串，不要寫成一般的同義字清單。
6. related：只能從「可用的相關字」清單裡挑（同家族、近義、反義），最多 4 個，優先挑「你學過的」。
   note 格式：「中文意思（關係）」，例如「可靠性（名詞）」「不可靠的（反義）」「依賴（近義）」。清單是空的或沒有合適的就給空陣列，不要自己想。
7. kk：美式 KK 音標，不加斜線或括號，重音符號 ˋ 放在重音節前面。不確定就給空字串。
8. context_zh：把每一句「原文句子」翻成自然的繁體中文，順序相同。沒有原文句子就給空陣列。

範例一（單字 increasingly，沒有原文句子）：
{"kk":"ɪnˋkrisɪŋlɪ","meanings":[{"pos":"adv.","zh":"越來越、日益","domain":"","primary":true}],"primary_category":"通用/描述","other_categories":[],"examples":[{"en":"Machine learning is increasingly used in healthcare.","zh":"機器學習越來越常被用在醫療領域。"}],"supplement":"","context_zh":[],"related":[{"word":"increase","note":"增加（原形動詞）"}]}

範例二（單字 retrieve，原文句子：The API retrieves user records from the database.）：
{"kk":"rɪˋtriv","meanings":[{"pos":"v.","zh":"檢索、讀取","domain":"資料庫","primary":true},{"pos":"v.","zh":"取回、找回","domain":"","primary":true},{"pos":"v.","zh":"挽回、恢復","domain":"","primary":false}],"primary_category":"科技/資料庫","other_categories":["通用/動作"],"examples":[{"en":"You can retrieve deleted files from the backup.","zh":"你可以從備份中找回被刪除的檔案。"}],"supplement":"retrieve（取回） vs receive（收到）：retrieve 是主動拿回來，receive 是別人給你","context_zh":["這個 API 會從資料庫讀取使用者紀錄。"],"related":[{"word":"retrieval","note":"檢索（名詞）"},{"word":"store","note":"儲存（相反的動作）"}]}

範例三（單字 examine，沒有原文句子）：
{"kk":"ɪgˋzæmɪn","meanings":[{"pos":"v.","zh":"檢查、審查","domain":"","primary":true},{"pos":"v.","zh":"測驗、考問","domain":"","primary":false}],"primary_category":"通用/動作","other_categories":[],"examples":[{"en":"The doctor will examine your eyes.","zh":"醫生會檢查你的眼睛。"}],"supplement":"","context_zh":[],"related":[{"word":"exam","note":"考試（相關字）"},{"word":"examination","note":"檢查、考試（名詞）"}]}
"""

# 一般生成約 1,700 token；記憶法開「思考」最多再多 3,000。預熱和生成必須一致，否則會重新載入模型
NUM_CTX = 6144

_EMPTY_MARKERS ={"無", "无", "（無）", "(無)", "沒有", "none", "n/a", "na", "-", "—", "null"}


class AIError(Exception):
    pass


def _post(path: str, payload: dict, timeout: float) -> dict:
    s = config.load_settings()
    req = urllib.request.Request(
        s["ollama_url"].rstrip("/") + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise AIError(f"Ollama 回傳錯誤 {e.code}：{body[:300]}") from e
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise AIError("連不到 Ollama，請確認 Ollama 有在執行") from e


def list_models() -> list[str]:
    s = config.load_settings()
    try:
        with urllib.request.urlopen(s["ollama_url"].rstrip("/") + "/api/tags", timeout=3) as res:
            data = json.loads(res.read().decode("utf-8"))
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def status() -> dict:
    s = config.load_settings()
    models = list_models()
    if not models:
        return {"ok": False, "model": s["model"], "error": "連不到 Ollama"}
    present = s["model"] in models or f'{s["model"]}:latest' in models
    return {
        "ok": present,
        "model": s["model"],
        "error": None if present else f"Ollama 裡沒有模型 {s['model']}",
    }


def warmup() -> None:
    """先把模型載入顯示卡（約 5 秒），之後每個字只要約 3 秒。在背景執行，不等它。"""
    def run():
        try:
            _post("/api/generate", {"model": config.load_settings()["model"], "keep_alive": "10m",
                                    "options": {"num_ctx": NUM_CTX}}, timeout=120)
        except AIError:
            pass
    threading.Thread(target=run, daemon=True).start()


def build_user_message(ctx: dict) -> str:
    parts = [f"單字：{ctx['word']}"]
    parts.append(f"使用者提供的中文：{ctx['user_zh'] or '（無）'}")
    if ctx["contexts"]:
        parts.append("原文句子：\n" + "\n".join(f"- {c}" for c in ctx["contexts"]))
    else:
        parts.append("原文句子：（無）")
    if ctx["dict_lines"]:
        parts.append("字典參考（可能含罕見或過時的意思，請自行判斷，只取常用的）：\n" + "\n".join(ctx["dict_lines"]))
    if ctx.get("lookalikes"):
        parts.append("拼字很像的字（給 supplement 參考，大多不會搞混）：" + ", ".join(ctx["lookalikes"]))
    if ctx["resemble"]:
        parts.append("近義字辨析參考（給 supplement 參考，請改寫得簡短）：\n" + "\n\n".join(
            f"[{g['words']}]\n{g['body'][:600]}" for g in ctx["resemble"]))
    pool = ctx.get("related_pool")
    if pool is None:  # 舊的呼叫方式
        parts.append("資料庫中已有、可能相關的字：" + (", ".join(ctx.get("candidates") or []) or "（無）"))
    else:
        def group(items):
            by = {}
            for p in items:
                by.setdefault(p.get("kind", "相關"), []).append(p["word"])
            return "；".join(f"{k}：{', '.join(v)}" for k, v in by.items()) or "（無）"
        parts.append("可用的相關字（related 只能從這裡挑，note 要照這裡寫的關係，例如「（反義）」「（名詞）」）：\n"
                     f"- 你學過的：{group([p for p in pool if p['learned']])}\n"
                     f"- 其他：{group([p for p in pool if not p['learned']])}")
    parts.append("可用分類：\n" + _option_lines(ctx["category_paths"], ctx.get("category_notes") or {}))
    return "\n\n".join(parts)


def _option_lines(options: list[str], notes: dict[str, str]) -> str:
    return "\n".join(f"- {o}" + (f"（說明：{notes[o]}）" if notes.get(o) else "") for o in options)


def generate(ctx: dict) -> dict:
    s = config.load_settings()
    payload = {
        "model": s["model"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_message(ctx)},
        ],
        "format": SCHEMA,
        "stream": False,
        "think": False,
        "keep_alive": "10m",  # 閒置 10 分鐘後卸載，釋放顯示卡記憶體
        "options": {"temperature": 0.3, "num_ctx": NUM_CTX},
    }
    try:
        data = _post("/api/chat", payload, timeout=300)
    except AIError as e:
        if "think" not in str(e).lower():
            raise
        payload.pop("think")  # 不支援「思考」參數的模型
        data = _post("/api/chat", payload, timeout=300)
    content = (data.get("message") or {}).get("content", "")
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
    try:
        raw = json.loads(content)
    except ValueError as e:
        raise AIError(f"AI 回傳的格式無法解析：{content[:200]}") from e
    return normalize(raw, ctx)  # 例句之後在背景用 review_examples 檢查（和記憶法一起）


# ================= 例句檢查 =================
EXAMPLE_CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"problem": {"type": "string"}, "ok": {"type": "boolean"},
                               "en": {"type": "string"}, "zh": {"type": "string"}},
                "required": ["problem", "ok", "en", "zh"],
            },
        },
    },
    "required": ["items"],
}

EXAMPLE_CHECK_PROMPT = """你是嚴格的英文老師，檢查單字卡上的例句。每一句都要回傳一筆，順序相同。
先在 problem 寫出這句的問題（用一句話；真的完全沒問題才寫「無」），再決定 ok：
- problem 是「無」：句子自然、文法正確，而且正確用到這個單字（用法、詞性、搭配、位置都對）→ ok=true，en 和 zh 原樣照抄。
- 有任何問題（文法錯、動詞沒變化、用法不自然、意思不對、句子沒寫完）→ ok=false，en 改寫成正確自然的句子（一定要用到這個單字），zh 寫新的繁體中文翻譯。
常見錯誤例子：「The company appropriate funds」→ 動詞要用 appropriated；「The system is designed to intend the user's actions」→ intend 不能這樣用；
「The system failed, for this reason.」→ for this reason 要放在說明原因之後的句首。"""


def _uses_word(sentence: str, word: str) -> bool:
    """例句裡有沒有用到這個字（含變化形）。片語只檢查主要的字。"""
    from .dictionary import forms_of
    s = sentence.lower()
    words = [t for t in re.findall(r"[a-z]+", word.lower()) if t not in ("a", "an", "the", "of", "to", "be", "b", "sb", "sth")]
    if not words:
        return True
    main = max(words, key=len)
    forms = {main, *(f.lower() for f in forms_of(main))}
    stem = re.sub(r"(e|y)$", "", main)
    return any(re.search(rf"\b{re.escape(f)}\b", s) for f in forms) or bool(re.search(rf"\b{re.escape(stem)}[a-z]*\b", s))


def review_examples(word: str, meanings: list[dict], examples: list[dict]) -> list[dict]:
    """請 AI 再檢查一次例句（文法、用法），有問題就改寫；最後確認例句真的有用到這個字。"""
    if not examples:
        return examples
    mean = "；".join(f"{m.get('pos', '')} {m['zh']}" for m in meanings[:3])
    lines = "\n".join(f"{i + 1}. {e['en']}（{e['zh']}）" for i, e in enumerate(examples))
    # 要開「思考」才抓得到問題（不思考時 for this reason 放錯位置、intend 用錯都會說沒問題）
    raw = _chat_json(EXAMPLE_CHECK_PROMPT, f"單字：{word}\n意思：{mean}\n例句：\n{lines}", EXAMPLE_CHECK_SCHEMA,
                     timeout=300, think=True)
    items = raw.get("items") or []
    out = []
    for i, e in enumerate(examples):
        it = items[i] if i < len(items) else None
        if it and not it.get("ok") and str(it.get("en") or "").strip():
            e = {"en": str(it["en"]).strip(), "zh": _text(it.get("zh")) or e["zh"]}
        if _uses_word(e["en"], word):
            out.append(e)
    return out or examples


JUDGE_SCHEMA = {
    "type": "object",
    "properties": {"correct": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["correct", "reason"],
}

JUDGE_PROMPT = """你是嚴格的英文單字測驗閱卷老師。判斷學生寫的中文，是否就是這個英文單字的其中一個意思。
算對：學生的說法和其中一個意思「可以互相替換、意思相同」，只是換個說法（同義詞、口語／正式說法、多加修飾語）。
算錯（以下都算錯，即使有關聯）：
- 只是相關、同一個情境裡的另一個概念：prevent（防止）寫「保護」、service（服務）寫「提供」、sorted（已排序的）寫「分類」。
- 範圍不同：上位或下位概念、只對一部分、太籠統（例如只寫「東西」「做」）。
- 修飾的意思不同：relational database（關聯式資料庫）寫「相關性資料庫」。
- 詞性造成意思改變、意思相反、或其實是另一個英文單字的意思。
不確定時判錯。
reason：用一句繁體中文簡短說明理由。"""


def judge(word: str, meanings: list[dict], answer: str) -> tuple[bool, str]:
    """英→中答案比對不到時，請 AI 判斷。"""
    lines = "\n".join(
        f"- {m.get('pos', '')} {m['zh']}" + (f"（{m['domain']}）" if m.get("domain") else "") for m in meanings
    )
    payload = {
        "model": config.load_settings()["model"],
        "messages": [
            {"role": "system", "content": JUDGE_PROMPT},
            {"role": "user", "content": f"單字：{word}\n意思：\n{lines}\n\n學生的答案：{answer}"},
        ],
        "format": JUDGE_SCHEMA,
        "stream": False,
        "think": False,
        "keep_alive": "10m",
        "options": {"temperature": 0, "num_ctx": NUM_CTX},
    }
    data = _post("/api/chat", payload, timeout=120)
    content = re.sub(r"<think>.*?</think>", "", (data.get("message") or {}).get("content", ""), flags=re.S)
    try:
        raw = json.loads(content)
    except ValueError as e:
        raise AIError("AI 判斷的回傳格式無法解析") from e
    return bool(raw.get("correct")), _text(raw.get("reason"))


CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"word": {"type": "string"}, "category": {"type": "string"}},
                "required": ["word", "category"],
            },
        },
    },
    "required": ["items"],
}

CLASSIFY_STRICT = """你是英文單字分類助手。使用者想把單字依主題整理。判斷每個單字是否適合放進「可用分類」中的某一個主題。
- 適合的條件：這個字是該主題的文章裡常見的字，或意思和該主題直接相關（例如主題「醫療」：diagnosis、symptom、patient、treatment）。
- 只是一般生活用語、和該主題沒有明顯關係的字，category 給空字串。
- 分類後面附了「說明」時，以說明為準：符合說明的才放，說明寫「不包含」的一律不要放。
- category 必須原樣照抄清單裡的分類名稱。每個單字都要回傳一筆。"""

# 「未分類」重新分類：先讓 AI 自由寫出最適合的主題，再對照現有分類（直接給清單叫它挑，它會勉強塞進不相符的類）
CLASSIFY_OPEN = """你是英文單字分類助手。為每個單字寫出最適合的主題分類，格式「大類/小類」，用繁體中文、台灣用語。
- 大類從這些選：{tops}（真的都不適合才自己寫）。
- 小類寫最精確、最常見的主題名稱，2～4 個字，例如：資料庫、機器學習、醫療、預算、植物。
- 參考「可用分類」裡已有的名稱：主題相同就用一樣的名稱；主題不同就寫新的，不要勉強套用。
- 分類後面附了「說明」時，符合說明的字就用那個分類。
- 每個單字都要回傳一筆。"""


def classify(options: list[str], items: list[dict], allow_new: bool, notes: dict[str, str] | None = None) -> dict[str, str]:
    """回傳 {單字(小寫): 分類路徑}；沒有適合的不會出現在結果裡。notes：分類說明。"""
    lines = []
    for it in items:
        cur = f"（目前分類：{it['current']}）" if it.get("current") else ""
        lines.append(f"- {it['word']}：{it['zh']}{cur}")
    user = "可用分類：\n" + _option_lines(options, notes or {}) + "\n\n單字：\n" + "\n".join(lines)
    payload = {
        "model": config.load_settings()["model"],
        "messages": [
            {"role": "system", "content": CLASSIFY_OPEN.format(
                tops="、".join(dict.fromkeys(o.split("/")[0] for o in options))) if allow_new else CLASSIFY_STRICT},
            {"role": "user", "content": user},
        ],
        "format": CLASSIFY_SCHEMA,
        "stream": False,
        "think": False,
        "keep_alive": "10m",
        "options": {"temperature": 0, "num_ctx": NUM_CTX},
    }
    data = _post("/api/chat", payload, timeout=300)
    content = re.sub(r"<think>.*?</think>", "", (data.get("message") or {}).get("content", ""), flags=re.S)
    try:
        raw = json.loads(content)
    except ValueError as e:
        raise AIError("AI 分類的回傳格式無法解析") from e
    valid = set(options)
    out = {}
    for r in raw.get("items") or []:
        w = str(r.get("word") or "").strip().lower()
        path = _norm_path(r.get("category"))
        if not w or not path:
            continue
        if path in valid:
            out[w] = path
            continue
        # 小類名稱和現有的一樣（例如寫成「生活/資料庫」但已經有「科技/資料庫」）→ 用現有的
        hit = [o for o in options if o.split("/")[-1] == path.split("/")[-1]]
        if len(hit) == 1:
            out[w] = hit[0]
        elif allow_new and "/" in path:
            out[w] = path
    return out


def _text(v) -> str:
    s = to_tw(str(v or "").strip())
    return "" if s.lower() in _EMPTY_MARKERS else s


def _norm_path(p: str) -> str:
    p = to_tw(str(p or "").strip())
    p = re.sub(r"\s*[›>／\\|]\s*", "/", p)
    return "/".join(x.strip() for x in p.split("/") if x.strip())


def _terms(s: str) -> list[str]:
    return [t for t in re.split(r"[、,，;；/\s]+", s or "") if t]


def _en_tokens(s: str) -> set[str]:
    return {t.strip("-").lower() for t in re.findall(r"[A-Za-z][A-Za-z-]*", s) if len(t.strip("-")) >= 2}


def _repeats_roots(mnemonic: str, roots: str) -> bool:
    """記憶法裡的英文全都是字根拆出來的部分 → 只是把字根再講一次。"""
    m = _en_tokens(mnemonic)
    return bool(m) and m <= _en_tokens(roots)


def _confusables(text: str, word: str, ctx: dict) -> str:
    """補充（容易混淆的字）：最多 2 組，一組一行。
    混淆字要真的容易搞混：拼字很像、開頭一樣，或字典意思相近（dictionary.close_words）。
    reliable vs suitable 這種只是字典把 -able 結尾的字放一組的，不算。"""
    from .dictionary import close_words, lookup
    w = word.lower()
    mine = lookup(word)
    out = []
    for g in re.split(r"[；;\n]\s*(?=[A-Za-z])", text or ""):
        g = g.strip()
        if not g or w[:max(3, len(w) - 2)] not in g.lower():
            continue
        others = [x for x in re.findall(r"[A-Za-z][A-Za-z-]+", g)
                  if x.lower() != w and x.lower() not in ("vs", "or") and not x.lower().startswith(w[:max(3, len(w) - 2)])]
        if not others or not lookup(others[0]) or not close_words(word, others[0]):
            continue
        o = lookup(others[0])
        if mine and o and mine["translation"][:1] == o["translation"][:1]:
            continue  # 拼法變體（judgment / judgement）
        out.append(re.sub(r"\s*(↔|<->|⇔)\s*", " vs ", g))  # 易混淆字用 vs；↔ 留給相反詞
    return "\n".join(out[:2])


def normalize(raw: dict, ctx: dict) -> dict:
    word = ctx["word"]
    paths = set(ctx["category_paths"])

    meanings = []
    for m in raw.get("meanings") or []:
        zh = _text(m.get("zh"))
        if not zh:
            continue
        meanings.append({
            "pos": str(m.get("pos") or "").strip(),
            "zh": zh,
            "domain": _norm_path(m.get("domain")).split("/")[-1],  # 「科技/資料庫」→「資料庫」
            "is_primary": bool(m.get("primary")),
            "source": "ai",
        })
    meanings = meanings[:5]
    from .dictionary import domain_ok
    for m in meanings:  # 「科技」「通用」這種太籠統，等於沒標；一般意思不標領域
        if m["domain"] in ("科技", "通用", "學術", "抽象概念", "一般", "其他", "日常") or not domain_ok(word, m["zh"], m["domain"]):
            m["domain"] = ""
    if len(meanings) == 1:
        meanings[0]["domain"] = ""  # 只有一個意思，不需要用領域區分

    # 使用者自己填的中文一定要在，而且是主要意思
    user_zh = (ctx["user_zh"] or "").strip()
    if user_zh:
        want = _terms(user_zh)
        hit = next((m for m in meanings if any(t in m["zh"] or m["zh"] in t for t in want)), None)
        if hit:
            hit["is_primary"] = True
            # 你寫的說法一個都不能少：AI 沒列到的補在最前面（例如「擷取；取回」的「擷取」）
            missing = [t for t in want if not any(t in m["zh"] for m in meanings)]
            if missing:
                hit["zh"] = "、".join(missing + [hit["zh"]])
            meanings.remove(hit)
            meanings.insert(0, hit)
        else:
            pos = meanings[0]["pos"] if meanings else ""
            meanings.insert(0, {"pos": pos, "zh": user_zh, "domain": "", "is_primary": True, "source": "user"})
    if meanings and not any(m["is_primary"] for m in meanings):
        meanings[0]["is_primary"] = True

    primary = _norm_path(raw.get("primary_category"))
    suggest = ""
    if primary not in paths:
        suggest = primary
        top = primary.split("/")[0] if primary else ""
        primary = top if top in paths else ""
    others = []
    for p in raw.get("other_categories") or []:
        p = _norm_path(p)
        if p in paths and p != primary and p not in others:
            others.append(p)

    examples = []
    for e in raw.get("examples") or []:
        en = str(e.get("en") or "").strip()
        if en:
            examples.append({"en": en, "zh": _text(e.get("zh"))})

    related = []
    for r in raw.get("related") or []:
        w = str(r.get("word") or "").strip()
        if w and w.lower() != word.lower() and all(w.lower() != x["word"].lower() for x in related):
            related.append({"word": w, "note": _text(r.get("note"))})
    pool = ctx.get("related_pool")
    kinds = {}
    if pool is not None:  # 只收有資料依據的相關字（字典、Wiktionary、你學過且意思相關的字）
        kinds = {p["word"].lower(): p.get("kind", "") for p in pool}
        related = [r for r in related if r["word"].lower() in kinds]
    # 拆成中文、詞性、關係、說明；關係以資料來源為準（AI 把同家族的字說成近義、反義就改掉），詞性從字典帶入
    from .relations import dict_brief, parse_note
    for i, r in enumerate(related):
        x = parse_note(r["note"], kinds.get(r["word"].lower(), ""))
        if not x["pos"] or not x["zh"]:
            d = dict_brief(r["word"], x["zh"])
            x["pos"] = x["pos"] or d["pos"]
            x["zh"] = x["zh"] or d["zh"]
        related[i] = {"word": r["word"], **x}

    kk = re.sub(r"[\[\]/]", "", str(raw.get("kk") or "")).strip()
    kk = kk.replace("ˈ", "ˋ").replace("'", "ˋ").replace("ˌ", "ˏ").replace("ɡ", "g")

    return {
        "kk": kk,
        "meanings": meanings,
        "primary_category": primary,
        "other_categories": others[:2],
        "suggest_category": suggest,
        "examples": examples[:2],
        "supplement": _confusables(_text(raw.get("supplement")), word, ctx),
        "context_zh": [_text(z) for z in raw.get("context_zh") or []],
        "related": related[:4],
        "raw": raw,
    }


# ================= 記憶法（單獨一次呼叫，開「思考」） =================
MEMORY_SCHEMA = {
    "type": "object",
    "properties": {
        "roots": {"type": "string"},
        "family": {"type": "string"},
    },
    "required": ["roots", "family"],
}

MEMORY_PROMPT = """你是很會教英文單字的老師，幫台灣學生「看懂單字怎麼組成」，而不是硬背中文翻譯。全部用繁體中文、台灣用語，英文單字保持英文。
有兩種方法，寫得出好的才寫，寫不出來就給空字串。寧可空白，不要硬湊、不要編造。短字（glad、crowd）通常兩種都空白。

1. roots（拆解）：把單字拆成字首＋字根＋字尾，每一塊附中文意思，最後用 → 推出單字的意思。
   格式：「de-（去除）+ tect（遮蓋）→ 把遮蓋的東西拿掉 → 發現、偵測」
   有「Wiktionary 字源」時一定照它的組成來拆（它是真的字源資料），把每一塊的英文意思改成好懂的中文。
   每一塊都要寫成「英文單字裡看得到的拼法」，學生才看得懂：不要寫拉丁文、希臘文原字，不要長音符號（dē、levō 都不行）。
   拉丁文、希臘文來源只用來知道每一塊的意思，例如：
   - detection（來源拉丁文 dētēctiō = dētegō + -tiō）→ 寫「detect（偵測）+ -ion（名詞字尾）；detect = de-（去除）+ tect（遮蓋）→ 把遮蓋拿掉 → 發現」
   - relevant（來源拉丁文 relevō = re- + levō）→ 寫「re-（再）+ lev（舉起）+ -ant（…的）」，不要寫 relevāns、levō
   - prevent（來源拉丁文 prae + veniō）→ 寫「pre-（在前面）+ vent（來）」，不要寫 prae、veniō
   字首被同化時照英文單字的寫法，意思用原本字首的意思：accurate 寫 ac-（向，原本是 ad-），sufficient 寫 suf-（在下面，原本是 sub-）。
   字尾也照英文單字的寫法：decision 是 -ion 不是 -tion，字根照單字寫 cis。
   沒有字源資料、或字源看不出組成（例如只寫 From Middle English fre），就給空字串，不要自己拆。
2. family（家族）：同一家族、學生可能已經會的簡單字，由簡單到難，用 → 連起來，每個字附中文。
   格式：「detect（偵測）→ detective（偵探）→ detection（偵測）」
   只從「同家族字」清單挑學生容易認得的常見字，最多 4 個。不要放 -ly 副詞、英式拼法這種沒幫助的字。

範例（單字 evaluation，評估；字源：evaluate + -ion，evaluate 來自法語 évaluer = é-（出）+ value（價值））：
{"roots":"evaluate（評估）+ -ion（名詞字尾）；evaluate = e-（出來）+ value（價值）→ 把價值找出來 → 評估","family":"value（價值）→ evaluate（評估）→ evaluation（評估）"}

範例（單字 glad，高興的）：
{"roots":"","family":""}
"""

# 記憶法要不要開「思考」（比較準，但每個字多 5～10 秒）
MEMORY_THINK = True


def _common_part(a: str, b: str, n: int = 4) -> bool:
    """兩個字有沒有共同的一段（至少 n 個字母），例如 value 和 evaluation 都有 valu。"""
    a, b = a.lower(), b.lower()
    return any(a[i:i + n] in b for i in range(len(a) - n + 1))


def _check_family(text: str, word: str, ref: list[str] | None = None) -> str:
    """家族字由程式檢查：要查得到字典、而且是字典找到的同家族字（或和原本的字有 5 個字母以上相同），
    不重複、不要英式拼法；剩不到兩個字就不要。"""
    from .dictionary import lookup
    seen, parts = set(), []
    for p in re.split(r"\s*(?:→|->)\s*", text or ""):
        p = p.strip()
        m = re.match(r"[A-Za-z][A-Za-z-]*", p)
        if not m:
            continue
        en = m.group(0).lower()
        if "英式" in p or (en.endswith(("ise", "ised", "ising")) and lookup(en[:-3] + "ize" + en[len(en) - 3 + 3:])):
            continue  # 英式拼法沒幫助
        # 只收參考清單裡的字（字典＋Wiktionary 找到的同家族字），或原本的字的字首（suit → suitable）
        # 不再用「有幾個字母相同」判斷：factual/actual、transpose/transplant 這種會被誤收
        ok = (en == word.lower() or en in {r.lower() for r in ref or []}
              or (len(en) >= 4 and word.lower().startswith(en)))
        if en in seen or not lookup(en) or not ok or en.endswith("re") and lookup(en[:-2] + "er"):
            continue
        seen.add(en)
        parts.append(p)
    return " → ".join(parts) if len(parts) >= 2 else ""


_LATIN_ENDINGS = [  # 拉丁文常見寫法 → 英文拼法（只換字塊結尾）
    (r"-tio\b", "-tion"), (r"-sio\b", "-sion"), (r"-tas\b", "-ty"), (r"-io\b", "-ion"),
]


def _english_roots(text: str) -> str:
    """字根拆解只留英文拼法：拿掉長音符號（dē → de），把 -tio 這種拉丁字尾換成英文的 -tion。"""
    import unicodedata
    text = "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c))
    text = unicodedata.normalize("NFC", text)
    for pat, rep in _LATIN_ENDINGS:
        text = re.sub(pat, rep, text)
    return text


def _unseen_pieces(roots: str, word: str) -> list[str]:
    """拆解裡哪幾塊在單字裡看不到（例如 suppose 拆成 sub- + pon）。"""
    w, bad = word.lower(), []
    for seg in re.split(r"[；;]", roots):
        seg = seg.split("→")[0]
        m = re.match(r"\s*([A-Za-z]+)\s*=", seg)  # 「detect = de- + tect」這種，檢查 detect 的組成
        target = m.group(1).lower() if m else w
        for p in re.findall(r"(-?[A-Za-z]+-?)\s*[（(]", seg):
            core = p.strip("-").lower()
            # rely → reli-able、pose → pos-ition 這種字尾 e/y 的變化算看得到
            ok = core in target or core in w or (len(core) >= 4 and core[-1] in "ey" and core[:-1] in target)
            if not ok:
                bad.append(p)
    return bad


def memory(ctx: dict) -> dict:
    """ctx: word, meanings(中文字串), roots(字根參考), family(同家族字)。回傳 {roots, family}。"""
    parts = [f"單字：{ctx['word']}", f"意思：{ctx['meanings'] or '（不確定）'}"]
    if ctx.get("etym"):
        parts.append("Wiktionary 字源：\n" + ctx["etym"])
    if ctx.get("roots"):
        parts.append("ECDICT 字根參考（英文解釋，可能是同家族字的）：\n" + "\n".join(
            f"- {r['root']}：{r['meaning']}" + (f"（來自 {r['via']}）" if r.get("via") else "") for r in ctx["roots"]))
    if ctx.get("family"):
        parts.append("同家族字（可能混了不相關的字）：" + ", ".join(ctx["family"]))
    payload = {
        "model": config.load_settings()["model"],
        "messages": [
            {"role": "system", "content": MEMORY_PROMPT},
            {"role": "user", "content": "\n\n".join(parts)},
        ],
        "format": MEMORY_SCHEMA,
        "stream": False,
        "think": MEMORY_THINK,
        "keep_alive": "10m",
        "options": {"temperature": 0.4, "num_ctx": NUM_CTX, "num_predict": 3000 if MEMORY_THINK else 600},
    }
    try:
        data = _post("/api/chat", payload, timeout=300)
        content = (data.get("message") or {}).get("content", "")
        raw = json.loads(re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip())
    except (AIError, ValueError):
        # 想太久（超過長度）或模型不支援思考 → 不思考再試一次
        payload["think"] = False
        payload["options"]["num_predict"] = 600
        data = _post("/api/chat", payload, timeout=300)
        content = (data.get("message") or {}).get("content", "")
        try:
            raw = json.loads(re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip())
        except ValueError as e:
            raise AIError("AI 記憶法的回傳格式無法解析") from e
    out = {k: _text(raw.get(k)) for k in ("roots", "family")}
    out["roots"] = _english_roots(re.sub(r"(?<=[A-Za-z-])\d+", "", out["roots"]))
    bad = _unseen_pieces(out["roots"], ctx["word"])
    if bad:  # 有幾塊用了拉丁文寫法、英文單字裡看不到 → 指出來讓 AI 重寫一次
        payload["think"] = False
        payload["options"]["num_predict"] = 600
        payload["messages"] += [
            {"role": "assistant", "content": json.dumps(out, ensure_ascii=False)},
            {"role": "user", "content": f"roots 裡的 {', '.join(bad)} 在 {ctx['word']} 這個英文單字裡看不到。"
                                        f"請改成單字裡實際看得到的拼法（例如 suppose 要寫 sup- + pose，不是 sub- + pon），"
                                        f"意思不變，family 照舊。"},
        ]
        try:
            data = _post("/api/chat", payload, timeout=300)
            raw2 = json.loads(re.sub(r"<think>.*?</think>", "", (data.get("message") or {}).get("content", ""),
                                     flags=re.S).strip())
            fixed = _english_roots(re.sub(r"(?<=[A-Za-z-])\d+", "", _text(raw2.get("roots"))))
            if fixed and len(_unseen_pieces(fixed, ctx["word"])) < len(bad):
                out["roots"] = fixed
        except (AIError, ValueError):
            pass
    if "etym" in ctx and not ctx.get("etym_parts") and not ctx.get("roots"):
        out["roots"] = ""  # Wiktionary 看不出組成、ECDICT 也沒有字根 → 不讓 AI 自己拆
    out["family"] = _check_family(out["family"], ctx["word"], ctx.get("family"))
    out["story"] = out["link"] = ""  # 字源、聯想已拿掉（容易亂編）；舊資料相容
    return out


def _chat_json(system: str, user: str, schema: dict, temperature: float = 0, timeout: float = 180,
               think: bool = False) -> dict:
    payload = {
        "model": config.load_settings()["model"],
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "format": schema,
        "stream": False,
        "think": think,
        "keep_alive": "10m",
        "options": {"temperature": temperature, "num_ctx": NUM_CTX, **({"num_predict": 3000} if think else {})},
    }
    data = _post("/api/chat", payload, timeout=timeout)
    content = re.sub(r"<think>.*?</think>", "", (data.get("message") or {}).get("content", ""), flags=re.S).strip()
    try:
        return json.loads(content)
    except ValueError as e:
        raise AIError("AI 的回傳格式無法解析") from e


# ================= 文章排版 =================
LAYOUT_SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"n": {"type": "integer"}, "t": {"type": "string", "enum": ["h", "p", "c", "x"]}},
                "required": ["n", "t"],
            },
        },
    },
    "required": ["lines"],
}

LAYOUT_PROMPT = """你在整理從網頁或 PDF 複製下來的英文文章。文字被切成一行一行，有些段落被斷成好幾行，也混了頁碼、頁首頁尾等雜訊。
請判斷每一行的角色，每一行都要回傳一筆 {"n": 行號, "t": 角色}：
- h：標題或小標題（短、通常沒有句號）
- p：新段落的第一行
- c：接續上一行（同一段落被斷行，或標題被斷成兩行的後半）
- x：雜訊（頁碼、頁首頁尾、「Advertisement」、分享按鈕文字、圖片來源等不屬於文章內容的字）

判斷依據：上一行沒有句號結尾、這一行小寫開頭 → 通常是 c。上一行句子結束、這一行開始新的主題 → p。
「[空行]」表示原文這一行前面有空白行，通常是新段落。
每行只給你開頭和結尾，中間用 … 省略。"""


def layout_labels(lines: list[dict]) -> dict[int, str]:
    """lines: [{n, text, blank_before, prev_end}] → {行號: 角色}"""
    rows = []
    for l in lines:
        t = l["text"]
        if len(t) > 140:
            t = t[:90] + " … " + t[-40:]
        rows.append(f"{l['n']}| {'[空行] ' if l['blank_before'] else ''}{t}")
    raw = _chat_json(LAYOUT_PROMPT, "\n".join(rows), LAYOUT_SCHEMA, timeout=300)
    out = {}
    for r in raw.get("lines") or []:
        try:
            n = int(r.get("n"))
        except (TypeError, ValueError):
            continue
        if r.get("t") in ("h", "p", "c", "x"):
            out[n] = r["t"]
    return out


SPLIT_SCHEMA = {
    "type": "object",
    "properties": {"blocks": {"type": "array", "items": {
        "type": "object",
        "properties": {"type": {"type": "string", "enum": ["p", "h"]}, "first_words": {"type": "string"}},
        "required": ["type", "first_words"]}}},
    "required": ["blocks"],
}
SPLIT_PROMPT = """這段英文是從網頁複製的，換行不見了，好幾個段落和小標題黏成了一大段。請找出原本的分段。
- 依照內容的轉換分段（換了時間、地點、主題、說話的人），一般每段 3～8 句。不要每句都分段。
- 小標題：一小段短語（通常 2～8 個字，沒有句號），夾在一句話的句號後面、下一句話的前面，例如
  「...in the forest. Personalities, minds and emotions Jane worked hard...」裡的「Personalities, minds and emotions」。
  小標題很少，一篇文章通常只有 0～5 個。句子的開頭不是小標題：
  「When Jane was 22 and working...」「In 1957, she set sail.」都是一般句子，不要標成標題。
- 依照順序列出每一塊：
  - 段落（type "p"）：給這段開頭的前 6～8 個英文字，和原文一字不差（照抄，包含標點和大小寫）。第一段也要列。
  - 小標題（type "h"）：給完整的標題文字，照抄，不要多抄到後面的句子。
- 不要改寫、不要翻譯、不要漏掉任何一段。
只回傳 JSON：{"blocks": [{"type": "p", "first_words": "..."}, {"type": "h", "first_words": "..."}, ...]}"""


def split_points(text: str) -> list[dict]:
    """一大段英文 → [{type: p|h, first_words}]（只回答位置，不改字）。"""
    raw = _chat_json(SPLIT_PROMPT, text, SPLIT_SCHEMA, timeout=300)
    out = []
    for b in raw.get("blocks") or []:
        t, w = b.get("type"), str(b.get("first_words") or "").strip()
        if t in ("p", "h") and w:
            out.append({"type": t, "first_words": w})
    return out


# ================= 文章查字：依上下文判斷意思 =================
EXPLAIN_SCHEMA = {
    "type": "object",
    "properties": {
        "lemma": {"type": "string"},
        "pos": {"type": "string"},
        "form": {"type": "string"},
        "meaning": {"type": "string"},
        "phrase": {"type": "string"},
        "phrase_meaning": {"type": "string"},
        "note": {"type": "string"},
    },
    "required": ["lemma", "pos", "form", "meaning", "phrase", "phrase_meaning", "note"],
}

EXPLAIN_PROMPT = """你幫台灣學生讀英文文章。學生在句子裡選了一個字（或片語），請判斷它「在這篇文章裡」是哪一個意思，寫成單字卡上的樣子。全部用繁體中文、台灣用語。
- lemma：字典原形（studies→study、ran→run、analyses→analysis、better→good）。是片語就寫片語原形。專有名詞保留原樣。
- pos：在這個句子裡的詞性（n. / v. / adj. / adv. / prep. / conj.）
- form：在句子裡的型態，例如「過去分詞（被動）」「現在分詞」「複數」「比較級」「第三人稱單數」「原形」
- meaning：像單字卡、字典那樣的「詞」，1～2 個說法，每個最多 6 個字，用「、」分隔。
  不要寫成句子、不要翻譯整句、不要加解釋。優先從字典意思裡挑最符合上下文的那個。
  例如 table：文章在講家具 →「桌子」；文章在講資料庫 →「表、資料表」。
  例如 accurate（accurate object detection）→「準確的、精確的」。
- phrase：如果這個字在這句裡屬於一個片語、片語動詞或固定搭配，而且意思因此改變（例如 carried out＝執行、take into account＝考慮），寫出片語原形（carry out）；否則給空字串。
- phrase_meaning：片語的意思，一樣寫成單字卡的樣子（1～2 個詞），沒有就給空字串。
- note：只在「這裡的意思」和這個字最常見的意思不同時才寫一句短提醒，20 字以內，例如「這裡是資料庫的表，不是桌子」。意思就是最常見的那個時給空字串。"""


MATCH_SCHEMA = {"type": "object", "properties": {"match": {"type": "integer"}}, "required": ["match"]}
MATCH_PROMPT = """學生的單字庫裡，這個字已經有幾個中文意思（有編號）。現在它出現在一個新句子裡，「在這句的意思」也給你了。
請判斷：「在這句的意思」和單字庫裡的哪一個意思是同一個意思（說法不同但意思一樣也算，例如「最後」和「終於」）。
- 是同一個 → 回那個編號。
- 都不是（這是一個新的、不同的意思，例如 dock 學的是「碼頭」，這句是「停泊、靠港」）→ 回 -1。
只回傳 JSON：{"match": 編號或 -1}"""


def match_meaning(word: str, sentence: str, ctx_meaning: str, meanings: list[dict]) -> int:
    """在這句的意思是單字庫裡的第幾個意思（從 0 開始）；都不是回 -1。"""
    lines = [f"{i}. {m.get('pos', '')} {m['zh']}" for i, m in enumerate(meanings)]
    user = f"單字：{word}\n句子：{sentence}\n在這句的意思：{ctx_meaning}\n\n單字庫裡的意思：\n" + "\n".join(lines)
    raw = _chat_json(MATCH_PROMPT, user, MATCH_SCHEMA, timeout=60)
    try:
        i = int(raw.get("match"))
    except (TypeError, ValueError):
        return -1
    return i if 0 <= i < len(meanings) else -1


TRANSLATE_SCHEMA = {"type": "object", "properties": {"zh": {"type": "string"}}, "required": ["zh"]}
TRANSLATE_PROMPT = """你是英文老師，幫台灣學生看懂英文句子。把使用者給的英文翻成自然、通順的繁體中文（台灣用語）。
- 意思要準確，不要漏掉任何部分，也不要加原文沒有的內容。
- 專有名詞、程式或技術用語可以保留英文。
- 有前後文時，用前後文判斷代名詞和多義字的意思，但只翻譯指定的那段。
只回傳 JSON：{"zh": "翻譯"}"""


def translate(text: str, context: str = "") -> str:
    """整句翻譯（文章裡選一整句時，按了才翻）。"""
    parts = [f"要翻譯的英文：{text}"]
    if context and context.strip() != text.strip():
        parts.append(f"前後文（只供參考，不用翻）：{context[:900]}")
    raw = _chat_json(TRANSLATE_PROMPT, "\n\n".join(parts), TRANSLATE_SCHEMA, timeout=120)
    zh = _text(raw.get("zh"))
    if not zh:
        raise AIError("AI 沒有給出翻譯")
    return zh


def explain_in_context(selected: str, lemma_hint: str, sentence: str, paragraph: str, dict_lines: list[str]) -> dict:
    parts = [f"選取的字：{selected}", f"所在的句子：{sentence}"]
    if paragraph and paragraph != sentence:
        parts.append(f"前後文：{paragraph[:900]}")
    if lemma_hint and lemma_hint.lower() != selected.lower():
        parts.append(f"字典判斷的原形：{lemma_hint}")
    if dict_lines:
        parts.append("字典參考：\n" + "\n".join(dict_lines[:8]))
    raw = _chat_json(EXPLAIN_PROMPT, "\n\n".join(parts), EXPLAIN_SCHEMA, timeout=120)
    out = {k: _text(raw.get(k)) for k in EXPLAIN_SCHEMA["properties"]}
    out["lemma"] = str(raw.get("lemma") or "").strip() or lemma_hint
    out["phrase"] = _text(raw.get("phrase"))
    if not out["phrase"] or out["phrase"].lower() == out["lemma"].lower():
        out["phrase"], out["phrase_meaning"] = "", ""
    return out
