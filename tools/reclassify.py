"""2026-11 重新分類：依「字本身最常見的意思」重排所有單字的分類（舊的分類常常是照「在哪篇文章讀到」放的）。

用法：
  .venv\\Scripts\\python.exe -I tools\\reclassify.py            只列出會怎麼改（不寫入）
  .venv\\Scripts\\python.exe -I tools\\reclassify.py --apply    先備份，再寫入；刪掉清空的舊分類
環境變數 VOCAB_DATA 可以指到別的資料夾（測試用）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import backup, db, taxonomy, words  # noqa: E402

CODE = {
    "D": "科技/資料與資料庫", "P": "科技/程式與演算法", "A": "科技/AI 與機器學習", "H": "科技/硬體、網路與資安",
    "R": "學術/研究方法", "W": "學術/學術寫作常用字", "K": "學術/學科與科學知識",
    "PE": "人與社會/人物與身分", "E": "人與社會/情緒與個性", "S": "人與社會/社會、工作與經濟",
    "N": "自然與生活/自然、地理與生物", "L": "自然與生活/日常生活",
    "V": "通用/動作與變化", "Q": "通用/性質與狀態", "C": "通用/抽象概念", "F": "通用/副詞、片語與連接詞",
}

# 單字|主分類|其他分類（最多 1 個，只有另一個常見意思屬於別的分類才放）
MAPPING = """
retrieve|D|V
service|S|H
servers|H|
relational|D|
relational database|D|
table|D|L
key|D|L
relevant|W|
prevent|V|
unnecessary|Q|
duplication|D|
keep|V|
consistent|W|
backup|D|
expose|V|H
serious|Q|
increasingly|F|
examine|V|R
identify|V|
sign|C|
disease|L|
organize|V|
decision|C|
prediction|A|
case|C|
professional|PE|
judgment|C|
algorithm|P|
compare|V|
require|V|
element|C|D
repeatedly|F|
sorted|Q|P
collection|C|D
directly|F|
ordered|Q|P
appropriate|Q|
depend|V|
available|Q|
suitable|Q|
particular|W|
a set of|F|
one by one|F|
divide A into B|V|
be suitable for|F|
artificial|Q|A
intelligence|C|A
concept|C|W
extra|Q|
tutor|PE|
dependent|Q|
independent|Q|
whether|F|
simply|F|
complete|V|
assignment|S|
approach|W|
lack|V|
reliable|Q|
document|S|
selected|Q|
passage|W|L
produced|V|
evaluation|R|A
factual|Q|
accuracy|R|A
suggest|V|W
external|Q|
delivery|S|
obstacle|C|
surroundings|L|
detection|H|A
uncertain|Q|
operator|PE|P
no longer|F|
be limited to|F|
for this reason|F|
more than|F|
complexity|C|P
traversal|P|
collaborator|PE|
transpose|P|V
biomedical|K|
device|H|
signal|H|C
intend|V|
movement|C|
disability|L|
adjust|V|
individual|Q|
cosine|K|
speech|C|A
accent|C|
pronunciation|C|
remain|V|
several|F|
reliability|R|
address|V|
develop|V|
evaluate|R|
pattern|C|A
quantity|C|
significantly|W|
investigate|R|
generalization|R|A
experimental|R|
demonstrate|W|
noise|C|A
jungle|N|
companion|PE|
round-trip|L|
carpet|L|
dock|L|
within|F|
archaeologist|PE|
paleontologist|PE|
avid|E|
eventually|F|
little-understood|Q|
evolutionary|K|
authority|S|
frustrating|E|
flee|V|
discourage|E|
vantage|C|
vegetarian|L|
flesh|N|
nest|N|
rough|Q|
strip|V|
stem|N|V
fashion|L|V
anthropologist|PE|
trait|C|
mankind|PE|
distinction|C|
blur|V|
ecstatic|E|
arrange|V|
enroll|S|
mind|C|E
deepen|V|
distinct|Q|
mesh|V|
ethologist|PE|
colleague|PE|
impersonal|Q|
mentor|PE|
methodology|R|
firm|Q|
foundation|C|
insist|V|
validity|R|
instead|F|
captivate|E|
permanent|Q|
expand|V|
promote|S|V
biologist|PE|
urgent|Q|
threat|C|H
continent|N|
recharge|V|H
battery|H|L
passion|E|
curiosity|E|
courage|E|
priority|S|
critical|Q|
exhaust|V|
purpose|C|
overwhelm|V|E
mire|V|
crisis|C|
descendant|PE|
operation|S|
indomitable|E|
unattainable|Q|
against|F|
blaze|V|
presidential|S|
resilience|E|
atomic|K|
manage|V|S
crack|V|
fissure|N|
extinction|N|
brink|C|
tremendous|Q|
enthusiasm|E|
commitment|C|
heritage|C|S
vest|L|
interest|C|S
workforce|S|
inform|V|
truly|F|
underestimate|V|
restore|V|D
shelter|L|
continual|Q|
inspiration|C|
intellect|C|
staunch|E|
compassion|E|
elementary|Q|
ahead of|F|
dedicate|V|
endemic|N|
campuse|L|
express|V|
admiration|E|
extensive|Q|
primatologist|PE|
commemorate|V|
anniversary|L|
articulate|V|
gratitude|E|
"""


def plan():
    out = {}
    for line in MAPPING.strip().splitlines():
        w, p, o = (line.split("|") + [""])[:3]
        out[w.strip().lower()] = (CODE[p], [CODE[o]] if o else [])
    return out


def main():
    apply = "--apply" in sys.argv
    mp = plan()
    db.init()
    if apply:
        backup.pre_upgrade_backup()
    with db.tx() as con:
        cats = {c["id"]: c for c in words.categories(con)}
        rows = con.execute("SELECT id, word FROM words WHERE status IN ('active','draft','error')").fetchall()
        missing, changed = [], 0
        lines = []
        for r in rows:
            cur = [cats[i]["path"] for i in words._word_cat_ids(con, r["id"]) if i in cats]
            target = mp.get(r["word"].lower())
            if not target:
                missing.append(r["word"])
                continue
            primary, others = target
            if cur[:1] != [primary] or sorted(cur[1:]) != sorted(others):
                changed += 1
            lines.append(f"{r['word']:<20} {' + '.join(cur) or '-':<55} → {primary}" + (f" + {others[0]}" if others else ""))
            if apply:
                for path in [primary, *others]:
                    words.ensure_category(con, path)
                words.set_categories(con, r["id"], primary, others)
        if apply:
            # 新分類的說明（給 AI 看）
            for path, note in taxonomy.NOTES.items():
                cid = words.ensure_category(con, path)
                con.execute("UPDATE categories SET description=? WHERE id=?", (note, cid))
            # 刪掉沒有字、也不在新分類表裡的舊分類（小類先刪，大類沒有小類了才刪）
            keep = set(taxonomy.PATHS) | {p.split("/")[0] for p in taxonomy.PATHS}
            for c in sorted(words.categories(con), key=lambda c: -c["depth"]):
                if c["system"] or c["path"] in keep:
                    continue
                used = con.execute("SELECT 1 FROM word_categories WHERE category_id=?", (c["id"],)).fetchone()
                kids = con.execute("SELECT 1 FROM categories WHERE parent_id=?", (c["id"],)).fetchone()
                if not used and not kids:
                    words.delete_category(con, c["id"], None)
            # 分類順序照新的分類表
            for i, (top, kids) in enumerate(taxonomy.TREE):
                tid = words.ensure_category(con, top)
                con.execute("UPDATE categories SET sort=? WHERE id=?", (i, tid))
                for j, (child, _) in enumerate(kids):
                    con.execute("UPDATE categories SET sort=? WHERE id=?", (j, words.ensure_category(con, f"{top}/{child}")))
    print("\n".join(lines))
    print(f"\n共 {len(lines)} 個字，{changed} 個分類有變。")
    if missing:
        print("對照表裡沒有、維持原分類的字：" + "、".join(missing))
    print("已寫入。" if apply else "（只是預覽，加 --apply 才會寫入）")


if __name__ == "__main__":
    main()
