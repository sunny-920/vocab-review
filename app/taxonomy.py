"""分類表（大類/小類）和分類規則。

原則：依「這個字本身最常見的意思」分類，不看是在哪篇文章讀到的（出處另外記在例句上，自由複習可以用出處篩選）。
科技類只放「有技術意思」的字：至少一個意思標了技術領域（資料庫、程式設計、機器學習…），或字典有 [計] 的意思。
"""
import re

TREE = [
    ("科技", [
        ("資料與資料庫", "資料庫、資料結構、資料處理的專有名詞：table（資料表）、query、backup、relational、retrieve（檢索）。一般字不放，例如 relevant、available。"),
        ("程式與演算法", "寫程式、演算法的專有名詞：algorithm、operator、traversal、transpose、complexity（複雜度）。"),
        ("AI 與機器學習", "AI、機器學習、語音辨識的專有名詞：prediction、accuracy、generalization、overfitting。一般字不放，例如 intend、remain、obstacle。"),
        ("硬體、網路與資安", "電腦硬體、網路、資訊安全：device、server、battery、bandwidth、threat（威脅）、detection。"),
    ]),
    ("學術", [
        ("研究方法", "做研究、實驗、評估的字：evaluate、investigate、methodology、validity、experimental、hypothesis、reliability。"),
        ("學術寫作常用字", "論文、學術文章裡常用、但不屬於特定領域的字：approach、relevant、demonstrate、significantly、particular、consistent、suggest。"),
        ("學科與科學知識", "各學科、科學的知識名詞：evolutionary、atomic、biomedical、cosine、molecule。人物、職業（biologist）不放這裡，放「人物與身分」。"),
    ]),
    ("人與社會", [
        ("人物與身分", "人、職業、角色、群體：archaeologist、biologist、colleague、mentor、tutor、collaborator、descendant、mankind。"),
        ("情緒與個性", "感受、情緒、態度、個性、品格：passion、courage、compassion、gratitude、frustrating、avid、staunch、resilience。"),
        ("社會、工作與經濟", "工作、公司、組織、政府、經濟、金錢：manage、workforce、priority、authority、presidential、crisis、interest（利息）。"),
    ]),
    ("自然與生活", [
        ("自然、地理與生物", "動植物、自然環境、地理：jungle、nest、stem、flesh、continent、extinction、endemic、fissure。"),
        ("日常生活", "家庭、食物、交通、旅遊、健康、學校生活：carpet、shelter、round-trip、dock、vegetarian、disease、campus。"),
    ]),
    ("通用", [
        ("動作與變化", "一般的動作、行為、變化（多半是動詞）：prevent、organize、adjust、expand、restore、flee、insist。"),
        ("性質與狀態", "描述性質、狀態、程度的形容詞：available、critical、permanent、tremendous、reliable、unnecessary。"),
        ("抽象概念", "一般的抽象名詞：decision、concept、element、purpose、heritage、foundation、obstacle。"),
        ("副詞、片語與連接詞", "副詞、介係詞、連接詞、固定片語：increasingly、eventually、whether、instead、no longer、for this reason、ahead of。"),
    ]),
]

PATHS = [f"{top}/{child}" for top, kids in TREE for child, _ in kids]
NOTES = {f"{top}/{child}": note for top, kids in TREE for child, note in kids}

_TECH_DOMAINS = {"資料庫", "程式設計", "機器學習", "網路", "資安", "硬體", "雲端", "電腦", "科技", "軟體", "人工智慧",
                 "演算法", "資料", "AI", "通訊"}


# 意思的「領域」標籤要用簡短的領域名稱；AI 有時照抄分類名稱，在這裡換回來
DOMAIN_ALIASES = {
    "資料與資料庫": "資料庫", "程式與演算法": "程式設計", "AI 與機器學習": "機器學習", "AI與機器學習": "機器學習",
    "硬體、網路與資安": "科技", "研究方法": "", "學術寫作常用字": "", "學科與科學知識": "",
    "人物與身分": "", "情緒與個性": "", "社會、工作與經濟": "", "自然、地理與生物": "", "日常生活": "",
    "動作與變化": "", "性質與狀態": "", "抽象概念": "", "副詞、片語與連接詞": "",
}


def is_tech_path(path: str) -> bool:
    return (path or "").startswith("科技/") or (path or "") == "科技"


def has_tech_meaning(word: str, meanings: list[dict]) -> bool:
    """這個字有沒有技術方面的意思：意思標了技術領域，或字典有 [計] 的意思。"""
    if any((m.get("domain") or "").strip() in _TECH_DOMAINS for m in meanings):
        return True
    from . import dictionary
    info = dictionary.lookup(word)
    return bool(info and any(re.match(r"^\[計\]", line) for line in info["translation"]))


def general_path_for(meanings: list[dict], options: list[str]) -> str:
    """沒有技術意思的字被放進科技類時，改放「通用」裡依詞性對應的小類（清單裡有的話）。"""
    pos = ((meanings[0].get("pos") if meanings else "") or "").strip().lower()
    if pos.startswith("v"):
        want = "通用/動作與變化"
    elif pos.startswith(("adj", "a.")):
        want = "通用/性質與狀態"
    elif pos.startswith(("adv", "prep", "conj", "phr", "pron")):
        want = "通用/副詞、片語與連接詞"
    else:
        want = "通用/抽象概念"
    if want in options:
        return want
    return next((o for o in options if o.startswith("通用/")), "")


def check(word: str, meanings: list[dict], primary: str, others: list[str], options: list[str]) -> tuple[str, list[str]]:
    """分類規則（程式檢查，不只靠 AI）：
    - 沒有技術意思的字不能放科技類（主分類改到別的；其他分類拿掉）
    - 其他分類最多 1 個"""
    tech = has_tech_meaning(word, meanings)
    others = [o for o in others if o != primary and (tech or not is_tech_path(o))]
    if is_tech_path(primary) and not tech:
        primary = next((o for o in others if not is_tech_path(o)), "") or general_path_for(meanings, options)
        others = [o for o in others if o != primary]
    return primary, others[:1]
