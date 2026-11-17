// 把貼上的文字分割成單字清單（在瀏覽器裡用規則分割，不需要 AI，打字時就能即時預覽）
//
// 支援的寫法（格式不用完全固定）：
//   retrieve	[rɪˈtriv]	擷取；取回        ← 單字行：英文、KK（選填）、中文（選填）
//   A database is ... store and retrieve.  ← 句子行：接在上一個單字後面，當作原文句子
//   relational database		關聯式資料庫    ← 片語也可以

const CJK = /[㐀-鿿豈-﫿　-〿＀-￯]/;
const CJK_CHAR = /[㐀-鿿豈-﫿]/;
const KK_RE = /[[/]([^[\]/]+)[\]/]/;
const POS_TAIL = /\s*\(?\b(n|v|vt|vi|adj|adv|prep|conj|pron|phr|aux)\.\)?\s*$/i;

export function isSentence(line) {
  if (CJK_CHAR.test(line) || /\[[^\]]+\]/.test(line)) return false;
  const words = line.split(/\s+/).filter(Boolean);
  if (words.length >= 5) return true;
  return words.length >= 2 && /[.?!]["')\]]?$/.test(line);
}

export function parseWordLine(line) {
  // 中文從第一個漢字開始；音標只在中文前面找（避免把「擷取/取回/讀取」當成音標）
  const ci = line.search(CJK_CHAR);
  let en = ci >= 0 ? line.slice(0, ci) : line;
  let zh = ci >= 0 ? line.slice(ci) : '';
  let kk = '';
  const m = en.match(KK_RE);
  if (m) {
    kk = m[1].trim();
    en = en.slice(0, m.index) + '\t' + en.slice(m.index + m[0].length);
  }
  en = en
    .replace(/^\s*(\d+[.)、]|[-*•・])\s*/, '')   // 開頭的編號、項目符號
    .replace(/[\s:：\-–—=|,，;；(（]+$/, '')     // 結尾的分隔符號
    .replace(POS_TAIL, '')                      // 結尾的詞性 n. v.
    .replace(/\s+/g, ' ')
    .trim();
  zh = zh.replace(/^[\s:：\-–—=|]+/, '').replace(/\s+$/, '');
  return { word: en, kk, zh };
}

function containsWord(sentence, word) {
  const s = sentence.toLowerCase();
  const w = word.toLowerCase();
  if (s.includes(w)) return true;
  const stem = w.length > 5 ? w.slice(0, w.length - 2) : w.slice(0, Math.max(3, w.length - 1));
  return s.includes(stem);
}

// 回傳 { items: [{word, kk, zh, contexts, line, warnings}], orphans: [行號] }
export function parsePaste(text) {
  const items = [];
  const byKey = new Map();
  const orphans = [];
  let last = null;

  text.split(/\r?\n/).forEach((raw, i) => {
    const line = raw.trim();
    if (!line) return;
    if (isSentence(line)) {
      if (last) last.contexts.push(line);
      else orphans.push(i + 1);
      return;
    }
    const p = parseWordLine(line);
    if (!p.word || CJK.test(p.word)) {
      orphans.push(i + 1);
      return;
    }
    const key = p.word.toLowerCase();
    const dup = byKey.get(key);
    if (dup) {        // 同一個字出現兩次：合併
      if (!dup.kk) dup.kk = p.kk;
      if (!dup.zh) dup.zh = p.zh;
      last = dup;
      return;
    }
    last = { ...p, contexts: [], line: i, warnings: [] };
    byKey.set(key, last);
    items.push(last);
  });

  for (const it of items) {
    for (const c of it.contexts) {
      if (!containsWord(c, it.word)) it.warnings.push('句子裡好像沒有這個字，確認是不是放錯位置');
    }
  }
  return { items, orphans };
}
