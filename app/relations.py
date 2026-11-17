"""相關字的欄位：中文、詞性、關係、說明分開存。

舊資料（和 AI 的原始輸出）是一串「熱衷地（副詞）」：中文加括號，括號裡有時是詞性、有時是關係、有時是一句說明。
這裡負責拆開。學習狀態（還沒學／已學）不存，顯示時即時查單字庫。"""
import re

RELS = ("同家族", "近義", "反義", "易混淆", "相關")
POSES = ("n.", "v.", "adj.", "adv.", "phr.")

_POS_WORDS = {
    "名詞": "n.", "名": "n.", "動詞": "v.", "原形動詞": "v.", "動": "v.", "形容詞": "adj.", "形": "adj.",
    "副詞": "adv.", "副": "adv.", "片語": "phr.", "動詞片語": "phr.",
}
_REL_PATTERNS = [
    (r"^(近義|近義字|近義詞|同義|同義字|同義詞|意思相近|意思接近|類似)$", "近義"),
    (r"^(反義|反義字|反義詞|相反|相反的動作|相反詞|對比)$", "反義"),
    (r"^(同家族|同字根|衍生字|字根相同|家族)$", "同家族"),
    (r"^(相關|相關字|相關詞)$", "相關"),
    (r"(有區別|區別|易混淆|混淆|搞混|容易弄錯|拼法相近|長得像)", "易混淆"),
]


def norm_pos(p: str) -> str:
    p = (p or "").strip().lower().replace("．", ".")
    if not p:
        return ""
    if not p.endswith("."):
        p += "."
    aliases = {"a.": "adj.", "ad.": "adv.", "vt.": "v.", "vi.": "v.", "phrase.": "phr.", "phrasal.": "phr."}
    p = aliases.get(p, p)
    return p if p in POSES else ""


def norm_rel(r: str) -> str:
    r = (r or "").strip()
    if r in RELS:
        return r
    for pat, rel in _REL_PATTERNS:
        if re.search(pat, r):
            return rel
    return ""


def parse_note(note: str, kind: str = "") -> dict:
    """「熱衷地（副詞）」→ {zh: 熱衷地, pos: adv., rel: 同家族, note: ''}。
    kind：資料來源判斷的關係（同家族／近義／反義／相關），比括號裡寫的優先（近義、反義以資料為準）。"""
    note = (note or "").strip()
    m = re.match(r"^(.*?)\s*[（(]([^（）()]*)[）)]\s*$", note)
    zh, label = (m.group(1).strip(), m.group(2).strip()) if m else (note, "")
    pos, rel, extra = "", "", ""
    if label:
        lp = re.match(r"^(名詞|動詞|形容詞|副詞|片語)(形|原形|形式)?$|^(動詞)?原形(動詞)?$", label)
        if lp and label not in _POS_WORDS:
            label = lp.group(1) or "動詞"
        if label in _POS_WORDS:
            pos, rel = _POS_WORDS[label], "同家族"  # 寫詞性的，幾乎都是同家族的不同詞性（retrieve → retrieval）
        elif norm_rel(label):
            rel = norm_rel(label)
            if rel == "易混淆" and label not in ("易混淆", "混淆"):
                extra = label  # 「與 particular 有區別」整句留在說明
        else:
            extra = label  # 一句說明（「長期儲存資料的方式」）
            rel = "易混淆" if re.search(r"區別|混淆|搞混", label) else ""
    if not zh and extra and not rel:
        zh, extra = extra, ""
    if (len(zh) > 24 or re.search(r"[A-Za-z]|，", zh)) and not extra:  # 一句說明（有英文、逗號、很長）放說明欄
        zh, extra = "", zh
    kind = norm_rel(kind)
    if kind in ("近義", "反義") or (kind and not rel):
        rel = kind
    return {"zh": zh, "pos": pos, "rel": rel or "相關", "note": extra}


def dict_brief(word: str, zh_hint: str = "") -> dict:
    """從字典帶入：詞性和前兩個中文意思，例如 avidly → {pos: adv., zh: 熱心地、貪婪地, found: True}。
    有 zh_hint（已經知道的中文）時，詞性挑意思和它最像的那一行（leave「離開」→ v.，不是第一行的 n.）。"""
    from . import dictionary
    info = dictionary.lookup((word or "").strip())
    if not info:
        return {"found": False, "pos": "", "zh": ""}
    pos, zh, best = "", "", 0
    hint = {c for c in zh_hint if "一" <= c <= "鿿"}
    for line in info["translation"]:
        m = re.match(r"^(?:\[[^\]]*\]\s*)?([a-z]+\.)\s*(.*)$", line)
        body = m.group(2) if m else line
        p = norm_pos(m.group(1)) if m else ""
        terms = [t.strip() for t in re.split(r"[,，;；]", re.sub(r"\[[^\]]*\]", "", body)) if t.strip()]
        if not zh and terms:
            zh = "、".join(terms[:2])
        if p and not pos:
            pos = p
        score = len(hint & set(body))
        if p and score > best:
            pos, best = p, score
    return {"found": True, "pos": pos, "zh": zh}
