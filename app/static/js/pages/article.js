// 文章閱讀：選字查詢、整句翻譯、加入生字、片語與文法筆記、標出資料庫裡的紅黃燈字、單字表、文章備註、朗讀
// 版面：右邊固定一欄（平常列出這篇的紅黃燈字，查詢、字卡、片語也在這裡），文章欄寬度不會變，不會跳動
import { api, h, toast, lightDot, speak, stopSpeaking, prefetchSpeech, storageGet, storageSet, LIGHT_NAMES } from '../util.js';
import { renderDetail, applyStatus, statusToast, copyButton } from '../detail.js';
import { openWordModal } from '../wordmodal.js';
import { noteEditor, mdToolbar } from '../markdown.js';

const SENT_RE = /[^.!?。！？]+(?:[.!?。！？]+["'”’)\]]*|$)\s*/g;

function sentenceAt(text, offset) {
  for (const m of text.matchAll(SENT_RE)) {
    if (offset >= m.index && offset < m.index + m[0].length) return m[0].trim();
  }
  return text.trim();
}

// 把一段切成句子，切出來的片段接起來要和原文一模一樣（漏掉的標點、空白也自成一段）
function sentences(text) {
  const out = [];
  let last = 0;
  for (const m of text.matchAll(SENT_RE)) {
    if (!m[0]) continue;
    if (m.index > last) out.push(text.slice(last, m.index));
    out.push(m[0]);
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

// 右欄標題的字太長就縮小字體（underestimate、characteristically…）
const wordSize = w => (w.length > 18 ? ' xlong' : w.length > 11 ? ' long' : '');

const escRe = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const SIZES = [['小', 16], ['中', 18], ['大', 21]];
const WORD_LIMIT = 6;  // 選 6 個字以內查字；更長的當成句子（翻譯、存成片語）

export async function render(el) {
  const id = Number(new URLSearchParams(location.hash.split('?')[1] || '').get('id'));
  if (!id) { location.hash = '#/articles'; return; }
  let art = await api(`/articles/${id}?touch=true`);
  let alive = true;
  let pollTimer = null;
  let lookupToken = 0;
  let targets = [];         // 紅黃燈字：[{id, word, light, forms, zh}]
  let markRe = null;
  let formMap = new Map();  // 小寫變化形 → target
  let showMarks = storageGet('reader-marks', true);

  // ================= 版面 =================
  const side = h('aside', { class: 'reader-side' });
  const textEl = h('article', { class: 'reader-text' });
  const banner = h('div', {});
  const wordsBox = h('div', {});
  const phrasesBox = h('div', {});
  const titleEl = h('h1', { class: 'reader-title' });
  const sourceEl = h('div', { class: 'muted small' });

  const marksBtn = h('button', { class: 'small', onclick: () => { showMarks = !showMarks; storageSet('reader-marks', showMarks); drawMarksBtn(); drawText(); } });
  const drawMarksBtn = () => { marksBtn.textContent = showMarks ? '隱藏標記' : '顯示標記'; };
  drawMarksBtn();

  let size = storageGet('reader-size', 18);
  const applySize = () => textEl.style.setProperty('--reader-size', size + 'px');
  const sizeSel = h('select', { class: 'small-select', title: '字體大小', onchange: e => { size = Number(e.target.value); storageSet('reader-size', size); applySize(); } },
    ...SIZES.map(([t, v]) => h('option', { value: v, selected: v === size }, '字 ' + t)));
  applySize();

  const note = noteEditor({
    value: art.note || '',
    placeholder: '整篇文章的心得、重點…（點一下開始寫）',
    onSave: async text => {
      try { await api('/articles/' + id, { method: 'PUT', body: { note: text } }); toast('已儲存文章備註'); }
      catch (e) { toast(e.message, 'error'); throw e; }
    },
  });

  const drawHead = () => {
    titleEl.replaceChildren(art.title, ' ', h('button', { class: 'ghost small', title: '改標題', onclick: rename }, '✎'));
    sourceEl.replaceChildren(...(art.source
      ? [/^https?:\/\//.test(art.source) ? h('a', { href: art.source, target: '_blank', rel: 'noopener' }, art.source) : art.source]
      : []));
  };
  async function rename() {
    const t = prompt('文章標題', art.title);
    if (t == null || !t.trim() || t.trim() === art.title) return;
    try { art = { ...art, ...(await api('/articles/' + id, { method: 'PUT', body: { title: t } })) }; drawHead(); toast('已改標題'); }
    catch (e) { toast(e.message, 'error'); }
  }

  // ================= 文章內容 =================
  function wordMarks(text) {
    if (!markRe || !showMarks) return [text];
    const out = [];
    let last = 0;
    for (const m of text.matchAll(markRe)) {
      const t = formMap.get(m[0].toLowerCase().replace(/\s+/g, ' '));
      if (!t) continue;
      out.push(text.slice(last, m.index));
      out.push(t.local
        ? h('mark', { class: 'hl local', 'data-awid': t.awid, title: `${t.word}${t.zh ? '：' + t.zh : ''}（只記在這篇）` }, m[0])
        : h('mark', { class: 'hl ' + t.light, 'data-wid': t.id, title: `${t.word}・${LIGHT_NAMES[t.light]}` }, m[0]));
      last = m.index + m[0].length;
    }
    out.push(text.slice(last));
    return out;
  }
  // 存過的片語畫底線（裡面的紅黃燈字照樣標）
  function blockNodes(text) {
    const spans = phraseSpans(text);
    if (!spans.length) return wordMarks(text);
    const out = [];
    let last = 0;
    for (const sp of spans) {
      const p = sp.p;
      out.push(...wordMarks(text.slice(last, sp.s)));
      out.push(h('span', { class: 'phr', 'data-pid': p.id, title: [p.zh ? `${p.text}：${p.zh}` : p.text, p.note].filter(Boolean).join('\n') }, ...wordMarks(text.slice(sp.s, sp.e))));
      last = sp.e;
    }
    out.push(...wordMarks(text.slice(last)));
    return out;
  }

  // ---- 片語比對：不用和原文一模一樣 ----
  // 存的是 be taken with、take a study of sth、It is ... that ...，文章寫 was taken with、undertake a study of…也對得到：
  // 片語裡的字照順序出現在同一句裡（中間可以夾幾個字），每個字比原形（arrived＝arrive、was＝be、took＝take）。
  // sth、sb、one's、doing、a、the 這種佔位字可有可無；中文、+、/、... 不算。
  const OPTIONAL = new Set(['sth', 'something', 'sb', 'somebody', 'someone', "one's", "someone's", 'oneself', 'one', 'doing', 'do', 'a', 'an', 'the', 'adj', 'adv', 'etc',
    'ving', 'ved', 'ven', 'vpp', 'pp', 'noun', 'verb', 'sbd', 'smth', 'sth.', 'somewhere', 'oneself', 'yourself', 'your', 'my', 'his', 'her', 'their', 'our']);
  const BE = new Set(['be', 'am', 'is', 'are', 'was', 'were', 'been', 'being', "'s", "'re", "'m"]);
  const stem = w => {
    w = w.replace(/'s$/, '');
    if (w.length > 4) w = w.replace(/(ies|ied)$/, 'y').replace(/(ing|ed|es|s)$/, '');
    return w.replace(/e$/, '');
  };
  let phraseList = [];
  function buildPhraseRe() {
    phraseList = [];
    for (const p of art.phrases) {
      const toks = (p.text.match(/[A-Za-z]+(?:'[A-Za-z]+)?/g) || []).map(w => w.toLowerCase());
      const need = toks.filter(w => !OPTIONAL.has(w) && w.length > 1);  // N、V、O 這種單一字母也是佔位
      if (!need.length || (need.length === 1 && need[0].length < 3)) continue;
      const forms = p.word_forms || {};
      phraseList.push({ p, need: need.map(w => ({ w, st: stem(w), be: BE.has(w), forms: new Set((forms[w] || []).map(x => x.toLowerCase())) })) });
    }
  }
  const tokMatch = (t, n) => t === n.w || (n.be && BE.has(t)) || n.forms.has(t) || (t.length > 2 && stem(t) === n.st);
  function phraseSpans(text) {
    if (!phraseList.length) return [];
    const toks = [...text.matchAll(/[A-Za-z]+(?:'[A-Za-z]+)?/g)].map(m => ({ w: m[0].toLowerCase(), s: m.index, e: m.index + m[0].length }));
    const found = [];
    for (const ph of phraseList) {
      const n = ph.need.length;
      const maxGap = n === 1 ? 0 : n + 3;  // 整段最多比片語多幾個字
      for (let i = 0; i < toks.length; i++) {
        if (!tokMatch(toks[i].w, ph.need[0])) continue;
        let j = i, k = 1;
        while (k < n) {
          let hit = -1;
          for (let x = j + 1; x < toks.length && x - i <= n - 1 + maxGap; x++) if (tokMatch(toks[x].w, ph.need[k])) { hit = x; break; }
          if (hit < 0) break;
          j = hit; k++;
        }
        if (k === n) { found.push({ s: toks[i].s, e: toks[j].e, p: ph.p }); i = j; }
      }
    }
    // 重疊的只留一個（先出現的、比較長的）
    found.sort((a, b) => a.s - b.s || b.e - a.e);
    const out = [];
    for (const f of found) if (!out.length || f.s >= out[out.length - 1].e) out.push(f);
    return out;
  }
  function drawText() {
    textEl.replaceChildren(...art.body.map((b, i) => {
      const tag = b.t === 'h' ? 'h' + (b.l || (i === 0 ? 2 : 3)) : 'p';
      if (b.t === 'x') return h('div', { class: 'para' }, h(tag, { class: 'noise', 'data-pi': i }, ...blockNodes(b.text)));
      // 每一句包成一個 span，朗讀時才能標出念到哪一句（文字本身不變，選字算位置不受影響）
      const block = h(tag, { 'data-pi': i, class: b.t === 'li' ? 'li' : b.t === 'q' ? 'quote' : null },
        ...sentences(b.text).map((s, k) => h('span', { class: 'sent', 'data-si': k }, ...blockNodes(s))));
      // 朗讀按鈕放在段落外面，選字時算位置才不會算到它
      return h('div', { class: 'para' }, block,
        h('button', { class: 'para-play', title: '朗讀這段', onclick: () => (reading && reading.single === i ? stopReading() : readFrom(i, 0, i)) }, '🔊'));
    }));
    if (reading && reading.at) markReading(reading.at.pi, reading.at.si, false);
  }

  // ================= 朗讀 =================
  // 一句一句念（Chrome 一次念太長會自己停掉；Kokoro 也是一句一句產生），念到哪句就標出那句
  let reading = null;  // { queue: [{pi, si, text}], at: {pi, si}, single }
  const rates = [['慢', 0.75], ['正常', 0.9], ['快', 1.05]];
  let rate = storageGet('read-rate', 0.9);
  const readBtn = h('button', { onclick: () => (reading && reading.single == null ? stopReading() : readFrom(0, 0, null)) });
  const rateSel = h('select', { class: 'small-select', title: '朗讀速度', onchange: e => { rate = Number(e.target.value); storageSet('read-rate', rate); } },
    ...rates.map(([t, v]) => h('option', { value: v, selected: v === rate }, t)));
  const readHint = h('div', { class: 'muted small hidden', style: { marginTop: '4px' } }, '念的時候點任何一句，可以跳到那句');
  const drawReadBtn = () => {
    readBtn.textContent = reading && reading.single == null ? '⏹ 停止朗讀' : '▶ 朗讀全文';
    readHint.classList.toggle('hidden', !reading);
  };

  function markReading(pi, si, scroll) {
    textEl.querySelectorAll('.reading, .reading-p').forEach(x => x.classList.remove('reading', 'reading-p'));
    const p = pi == null ? null : textEl.querySelector(`[data-pi="${pi}"]`);
    if (!p) return;
    p.classList.add('reading-p');
    const s = p.querySelector(`[data-si="${si}"]`) || p;
    s.classList.add('reading');
    if (scroll) {
      const r = s.getBoundingClientRect();
      if (r.top < 70 || r.bottom > innerHeight) s.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  }
  // 從第 pi 段第 si 句開始念；single=段落編號時只念那一段，null 念到文章結尾
  function readFrom(pi, si, single = null) {
    stopReading();
    const queue = [];
    for (let i = pi; i < art.body.length && (single == null || i === single); i++) {
      const b = art.body[i];
      if (b.t === 'x') continue;
      sentences(b.text).forEach((s, k) => { if ((i > pi || k >= si) && s.trim()) queue.push({ pi: i, si: k, text: s.trim() }); });
    }
    if (!queue.length) return;
    const me = reading = { queue, at: null, single };
    drawReadBtn();
    const next = e => {
      if (reading !== me) return;
      if (e && e.type === 'error') { stopReading(); return; }  // 被打斷（按了單字發音、停止）就不再往下念
      const item = me.queue.shift();
      if (!item) { stopReading(); return; }
      me.at = item;
      markReading(item.pi, item.si, true);
      speak(item.text, { rate, onend: next, keep: true, kind: 'sentence' });
      if (me.queue[0]) prefetchSpeech(me.queue[0].text, { rate, kind: 'sentence' });  // 念這句時先準備下一句
    };
    next();
  }
  function stopReading() {
    const was = reading;
    reading = null;
    if (was) stopSpeaking();
    markReading(null);
    drawReadBtn();
  }
  drawReadBtn();

  // ================= 標出紅黃燈的字 =================
  // 一進文章就掃描；燈號改了、加了新字之後再掃一次
  async function scan() {
    try { targets = await api('/scan-targets'); } catch (e) { toast(e.message, 'error'); return; }
    buildMarks();
    drawText();
    drawWords();  // 左欄照出現順序排要用到變化形
    if (sideMode === 'home') sideHome();
  }
  // 紅黃燈字＋這篇的灰色字（只記在這篇的專有名詞）；同一個字資料庫的優先
  function buildMarks() {
    formMap = new Map();
    for (const x of art.words) if (x.local) {
      const t = { local: true, awid: x.id, word: x.lemma, zh: x.meaning };
      for (const f of x.forms) formMap.set(f, t);
    }
    for (const t of targets) for (const f of t.forms) formMap.set(f, t);
    const forms = [...formMap.keys()].sort((a, b) => b.length - a.length);
    markRe = forms.length ? new RegExp(`(?<![A-Za-z])(${forms.map(f => escRe(f).replace(/ /g, '\\s+')).join('|')})(?![A-Za-z])`, 'gi') : null;
  }

  // ================= 這篇的單字（合併清單）=================
  // 列：文章裡出現的紅黃燈字＋灰色字＋在這篇加入的字（含整理中、待確認、已變綠燈的）；不列：不是這篇加的綠燈字。
  // 照在文章裡第一次出現的順序，不重複。
  function mergedWords() {
    const items = new Map();  // key → {key, kind, light, word, zh, n, pos, surface, sentence, wid, row}
    const order = [];
    const fullBlocks = art.body.map((b, pi) => ({ b, pi })).filter(o => o.b.t !== 'x');
    // 1. 掃描文章：紅黃燈字、灰色字
    if (markRe) {
      let offset = 0;
      for (const { b, pi } of fullBlocks) {
        for (const m of b.text.matchAll(markRe)) {
          const t = formMap.get(m[0].toLowerCase().replace(/\s+/g, ' '));
          if (!t) continue;
          const key = t.local ? 'l' + t.awid : 'w' + t.id;
          const it = items.get(key);
          if (it) { it.n++; continue; }
          const v = {
            key, n: 1, pos: offset + m.index, surface: m[0], sentence: sentenceAt(b.text, m.index), pi,
            ...(t.local ? { kind: 'local', light: 'gray', word: t.word, zh: t.zh, awid: t.awid }
              : { kind: 'word', light: t.light, word: t.word, zh: t.zh, wid: t.id }),
          };
          items.set(key, v); order.push(v);
        }
        offset += b.text.length + 1;
      }
    }
    // 2. 在這篇加入的字（含文章裡找不到的、綠燈的、還沒存入的）
    const full = fullBlocks.map(o => o.b.text).join('\n');
    const findPos = forms => {
      let best = Infinity;
      for (const f of forms) {
        const m = new RegExp(`(?<![A-Za-z])${escRe(f).replace(/ /g, '\\s+')}(?![A-Za-z])`, 'i').exec(full);
        if (m && m.index < best) best = m.index;
      }
      return best;
    };
    art.words.forEach((x, i) => {
      const active = x.word && x.word.status === 'active';
      const key = x.local ? 'l' + x.id : active ? 'w' + x.word.id : 'a' + x.id;
      const it = items.get(key);
      if (it) { it.row = x; it.added = true; if (x.meaning) it.zh = x.meaning; return; }  // 優先顯示在這篇的意思
      const v = {
        key, row: x, added: true, n: 0, word: x.lemma, zh: x.meaning, surface: x.surface, sentence: x.sentence,
        pos: findPos([x.lemma, x.surface, ...(x.forms || [])].filter(Boolean)), late: i,
        kind: x.local ? 'local' : active ? 'word' : 'pending',
        light: x.local ? 'gray' : active ? x.word.light : '', wid: active ? x.word.id : null, awid: x.id,
      };
      items.set(key, v); order.push(v);
    });
    return order.sort((a, b) => a.pos - b.pos || (a.late || 0) - (b.late || 0));
  }

  let wordFilter = 'all';
  const FILTERS = [['all', '全部'], ['red', '紅'], ['yellow', '黃'], ['gray', '灰'], ['added', '這篇加的']];
  const passFilter = v => wordFilter === 'all' || (wordFilter === 'added' ? v.added : v.light === wordFilter);

  function openItem(v) {
    if (v.kind === 'local') {
      const x = art.words.find(w => w.id === v.awid);
      if (x) { showLocal(x); jumpToLocal(x.id); }
    } else if (v.kind === 'word') {
      showCard(v.wid, { surface: v.surface || v.word, sentence: v.sentence || '', para: v.pi != null ? art.body[v.pi].text : '' });
      jumpToWord(v.wid);
    }
  }
  function itemState(v) {
    if (v.kind !== 'pending') return v.light === 'gray'
      ? h('span', { class: 'light gray', title: '只記在這篇（灰色），不進單字庫' }) : lightDot(v.light);
    const w = v.row.word;
    if (!w) return h('span', { class: 'lc-state muted', title: '單字已刪除' }, '已刪');
    if (w.status === 'generating') return h('span', { class: 'lc-state muted', title: 'AI 整理中' }, '整理中');
    if (w.status === 'error') return h('span', { class: 'lc-state warn', title: 'AI 整理失敗' }, '失敗');
    return h('a', { href: '#/add', class: 'lc-state', title: '到「新增單字」確認存入' }, '待確認');
  }

  // ================= 右欄 =================
  let sideMode = 'home';  // home（清單）/ lookup / card / phrase
  const isPhone = () => matchMedia('(max-width: 700px)').matches;
  // 手機：查字、字卡從下方拉出來；同時把「這篇的單字」抽屜收起來
  function openSide() { side.classList.add('open'); document.body.classList.remove('show-left'); side.scrollTop = 0; }
  // 捲到某個字：手機上下半部被抽屜蓋住，放在畫面上方；電腦放中間
  function scrollToEl(el) {
    if (!isPhone()) { el.scrollIntoView({ block: 'center', behavior: 'smooth' }); return; }
    scrollTo({ top: el.getBoundingClientRect().top + scrollY - 110, behavior: 'smooth' });
  }
  const backBtn = () => h('button', { class: 'small ghost', onclick: sideHome }, '✕ 關閉');

  function sideHome() {
    sideMode = 'home'; side.classList.remove('open');
    lookupToken++;
    side.replaceChildren(h('div', { class: 'side-empty' },
      h('div', { class: 'side-title' }, '查字'),
      h('p', {}, '・選取（或雙擊）不會的字：查意思、加入生字，或只記在這篇（灰色）'),
      h('p', {}, '・選取一整句：翻譯、存成片語／文法'),
      h('p', {}, '・點文章裡有底色的字：看字卡'),
      h('p', {}, '・底線是你存過的片語，點一下看說明'),
      h('p', {}, '・左邊「這篇的單字」照文章順序列出這篇裡你不熟的字')));
  }
  function jumpToLocal(awid) {
    if (!showMarks) { showMarks = true; storageSet('reader-marks', true); drawMarksBtn(); drawText(); }
    const m = textEl.querySelector(`mark.hl[data-awid="${awid}"]`);
    if (!m) return;
    scrollToEl(m);
    m.classList.remove('flash'); void m.offsetWidth; m.classList.add('flash');
  }
  function jumpToWord(wid) {
    if (!showMarks) { showMarks = true; storageSet('reader-marks', true); drawMarksBtn(); drawText(); }
    const m = textEl.querySelector(`mark.hl[data-wid="${wid}"]`);
    if (!m) return;
    scrollToEl(m);
    m.classList.remove('flash'); void m.offsetWidth; m.classList.add('flash');
  }

  function contextOf(node) {
    const p = node && (node.nodeType === 1 ? node : node.parentElement)?.closest('[data-pi]');
    return p ? art.body[Number(p.dataset.pi)].text : '';
  }

  // 選字 → 查詢；選很多字 → 句子（翻譯、存成片語）
  textEl.addEventListener('mouseup', () => setTimeout(onSelect, 0));
  let selTimer = null, lastSel = '';
  const onSelChange = () => {
    clearTimeout(selTimer);
    selTimer = setTimeout(() => {
      const sel = window.getSelection();
      const t = sel && sel.rangeCount ? sel.toString().trim() : '';
      if (!t || t === lastSel || !textEl.contains(sel.anchorNode)) { if (!t) lastSel = ''; return; }
      lastSel = t;
      onSelect();
    }, 550);
  };
  if (matchMedia('(hover: none)').matches) document.addEventListener('selectionchange', onSelChange);
  function onSelect() {
    const sel = window.getSelection();
    const text = sel ? sel.toString().replace(/\s+/g, ' ').trim() : '';
    if (!text || !/[A-Za-z]/.test(text)) return;
    const range = sel.getRangeAt(0);
    const p = (range.startContainer.nodeType === 1 ? range.startContainer : range.startContainer.parentElement).closest('[data-pi]');
    if (!p || !textEl.contains(p)) return;
    const para = art.body[Number(p.dataset.pi)].text;
    const pre = document.createRange();
    pre.setStart(p, 0);
    pre.setEnd(range.startContainer, range.startOffset);
    const sentence = sentenceAt(para, pre.toString().length);
    if (text.length <= 80 && text.split(' ').length <= WORD_LIMIT) showLookup(text, sentence, para);
    else showSentence(text.slice(0, 1500), sentence, para);
  }

  textEl.addEventListener('click', e => {
    if (window.getSelection() && window.getSelection().toString().trim()) return;
    // 點標記的字 → 字卡
    const m = e.target.closest('mark.hl');
    if (m && m.dataset.awid) {
      const x = art.words.find(w => w.id === Number(m.dataset.awid));
      if (x) showLocal(x);
      return;
    }
    if (m) {
      const para = contextOf(m);
      const pre = document.createRange();
      const p = m.closest('[data-pi]');
      pre.setStart(p, 0); pre.setEndBefore(m);
      showCard(Number(m.dataset.wid), { surface: m.textContent, sentence: sentenceAt(para, pre.toString().length), para });
      return;
    }
    if (e.target.closest('button')) return;
    // 念的時候點一句 → 從那句開始念（沒在念時點文字不做事，才不會跟選字查詢打架）
    if (reading) {
      const s = e.target.closest('.sent');
      const p = s && s.closest('[data-pi]');
      if (!p) return;
      const pi = Number(p.dataset.pi);
      readFrom(pi, Number(s.dataset.si), reading.single == null ? null : pi);
      return;
    }
    // 點底線的片語 → 看說明
    const ph = e.target.closest('.phr');
    if (ph) {
      const p = art.phrases.find(x => x.id === Number(ph.dataset.pid));
      if (p) showPhrase(p);
    }
  });

  // ---- 翻譯（按了才翻，AI）----
  function translateBox(text, context) {
    const box = h('div', { class: 'side-translate' });
    const btn = h('button', {
      class: 'small', onclick: async () => {
        btn.disabled = true;
        box.replaceChildren(h('div', { class: 'muted small row' }, h('span', { class: 'spinner' }), 'AI 翻譯中…'));
        try {
          const r = await api('/translate', { method: 'POST', body: { text, context } });
          out.zh = r.zh;
          box.replaceChildren(h('div', { class: 'side-zh' }, r.zh));
        } catch (e) { box.replaceChildren(h('div', { class: 'warn small' }, '翻譯失敗：' + e.message)); btn.disabled = false; }
      },
    }, '🌐 翻譯');
    const out = { btn, box, zh: '' };
    return out;
  }

  function showSentence(text, sentence, para) {
    sideMode = 'lookup'; openSide();
    lookupToken++;
    const tr = translateBox(text, para);
    side.replaceChildren(
      h('div', { class: 'row', style: { justifyContent: 'space-between' } }, h('div', { class: 'side-title', style: { margin: 0 } }, '選取的句子'), backBtn()),
      h('div', { class: 'side-sentence', style: { marginTop: '8px' } }, text),
      h('div', { class: 'row', style: { marginTop: '10px' } },
        tr.btn,
        h('button', { class: 'small', onclick: () => speak(text, { kind: 'sentence' }) }, '🔊 念'),
        h('button', { class: 'small', onclick: () => phraseForm({ text, zh: tr.zh, sentence: text.length < 300 ? sentence : '' }) }, '＋ 存成片語／文法')),
      tr.box,
    );
  }

  async function showLookup(text, sentence, para) {
    sideMode = 'lookup'; openSide();
    const token = ++lookupToken;
    side.replaceChildren(h('div', { class: 'muted' }, '查詢中…'));
    let q;
    try { q = await api('/lookup', { method: 'POST', body: { text } }); }
    catch (e) { if (token === lookupToken) side.replaceChildren(backBtn(), h('div', { class: 'error-box' }, e.message)); return; }
    if (token !== lookupToken) return;

    const aiBox = h('div', { class: 'side-ai' }, h('div', { class: 'muted small row' }, h('span', { class: 'spinner' }), 'AI 正在看上下文…'));
    const actions = h('div', { class: 'side-actions' });
    let res = null;

    const head = h('div', { class: 'side-head' },
      h('span', { class: 'side-word' + wordSize(q.selected) }, q.selected),
      h('button', { class: 'speak', title: '發音', onclick: () => speak(q.lemma) }, '🔊'),
      copyButton(q.lemma));
    const lemmaLine = q.lemma.toLowerCase() !== q.selected.toLowerCase()
      ? h('div', { class: 'small' }, '原形 ', h('strong', {}, q.lemma), q.forms.length ? `（這裡是${q.forms.join('、')}）` : '') : null;
    const dictBox = q.dict
      ? h('div', { class: 'dict-preview' }, q.dict.translation.slice(0, 5).join('\n'))
      : h('div', { class: 'muted small' }, '字典查不到');
    const tr = translateBox(sentence, para);
    tr.btn.textContent = '🌐 翻譯這句';
    tr.btn.className = 'link small';
    const sentBox = h('div', { class: 'side-sentence' }, sentence);

    const drawActions = () => {
      const lemma = (res && res.lemma) || q.lemma;
      const ex = (res && res.existing) || q.existing;
      const btns = [];
      if (ex && ex.status === 'active') {
        btns.push(h('div', { class: 'small row' }, '資料庫裡有 ', h('strong', {}, ex.word), lightDot(ex.light), LIGHT_NAMES[ex.light]));
        btns.push(h('div', { class: 'row' },
          h('button', { class: 'small', onclick: () => showCard(ex.id, { surface: q.selected, sentence, para }) }, '看字卡'),
          h('button', { class: 'small primary', onclick: e => addExisting(ex, q.selected, sentence, para, res, e.currentTarget) }, '加到這篇的單字表')));
      } else if (ex) {
        btns.push(h('div', { class: 'small muted' }, `「${ex.word}」已經在待確認清單，到「新增單字」確認後就會存入。`));
        btns.push(h('button', { class: 'small', onclick: () => addWord(ex.word, q.selected, sentence, res && res.meaning, ex) }, '加到這篇的單字表'));
      } else {
        btns.push(h('button', { class: 'primary', onclick: () => addWord(lemma, q.selected, sentence, res && res.meaning, null) },
          `＋ 加入生字 ${lemma}`));
        btns.push(h('button', {
          class: 'small local-btn', title: '專有名詞、很少用到的字：只列在這篇（灰色），不進單字庫、不複習',
          onclick: () => addLocal(lemma, q.selected, sentence, (res && res.meaning) || ''),
        }, '＋ 只記在這篇（灰色，不進單字庫）'));
      }
      if (res && res.phrase) {
        const pe = res.phrase_existing;
        btns.push(h('button', {
          onclick: () => addWord(res.phrase, q.selected, sentence, res.phrase_meaning, pe && pe.status === 'active' ? pe : null),
        }, pe ? `片語 ${res.phrase} 加到單字表` : `＋ 加入片語 ${res.phrase}（進複習）`));
      }
      btns.push(h('button', {
        class: 'small ghost', title: '存在這篇文章的「片語與文法」筆記（不進複習）',
        onclick: () => phraseForm({ text: (res && res.phrase) || q.selected, zh: res ? (res.phrase ? res.phrase_meaning : res.meaning) || '' : '', sentence }),
      }, '＋ 存成片語／文法筆記'));
      actions.replaceChildren(...btns);
    };
    drawActions();

    side.replaceChildren(h('div', { class: 'row side-top' }, backBtn()), head, lemmaLine || '',
      h('div', { class: 'sec-label row' }, '在這句裡', h('span', { class: 'spacer' }), tr.btn), sentBox, tr.box, aiBox,
      h('div', { class: 'sec-label' }, '字典'), dictBox, actions);

    try {
      res = await api('/lookup/explain', { method: 'POST', body: { text, sentence, paragraph: para } });
    } catch (e) {
      if (token === lookupToken) aiBox.replaceChildren(h('div', { class: 'warn small' }, 'AI 無法使用：' + e.message));
      return;
    }
    if (token !== lookupToken) return;
    aiBox.replaceChildren(...[
      h('div', { class: 'side-meaning' }, res.meaning || '—',
        res.pos ? h('span', { class: 'badge', style: { marginLeft: '6px' } }, res.pos) : null),
      res.form ? h('div', { class: 'small muted' }, `型態：${res.form}` + (res.lemma && res.lemma.toLowerCase() !== q.selected.toLowerCase() ? `（原形 ${res.lemma}）` : '')) : null,
      res.note ? h('div', { class: 'small' }, res.note) : null,
      res.phrase ? h('div', { class: 'side-phrase' }, '片語 ', h('strong', {}, res.phrase), res.phrase_meaning ? '：' + res.phrase_meaning : '') : null,
      res.existing && res.existing.status === 'active'
        ? compareLine(res, res.existing.id, res.existing.word, q.selected, sentence, null) : null,
    ].filter(Boolean));  // replaceChildren 遇到 null 會印出「null」
    if (res.existing) ctxCache.set(`${res.existing.id}|${sentence}`, res);  // 之後打開字卡不用再查
    drawActions();
  }

  // 學過的字加到這篇：先看這句的意思（沒查過就先查），是新的意思就一起加進那個字的意思
  async function addExisting(ex, surface, sentence, para, res, btn, after) {
    const key = `${ex.id}|${sentence}`;
    if (!res || res.match == null) res = ctxCache.get(key) || null;
    if (!res) {
      if (btn) { btn.disabled = true; btn.textContent = 'AI 看這句的意思…'; }
      try {
        res = await api('/lookup/explain', { method: 'POST', body: { text: surface || ex.word, sentence, paragraph: para || sentence } });
        ctxCache.set(key, res);
      } catch { res = null; }  // AI 不能用就照舊只加例句
    }
    if (res && res.match === -1 && res.meaning) {
      try {
        await api(`/articles/${id}/words/${ex.id}/meaning`, { method: 'POST', body: { pos: res.pos || '', zh: res.meaning, surface, sentence } });
        toast(`已加到這篇的單字表；新意思「${res.meaning}」也加到 ${ex.word}，這句存成例句`);
        ctxCache.clear();
        await reloadWords();
        await scan();
        if (after) after();
      } catch (e) { toast(e.message, 'error'); if (btn) { btn.disabled = false; btn.textContent = '加到這篇的單字表'; } }
      return;
    }
    await addWord(ex.word, surface, sentence, res && res.meaning, ex);  // 意思一樣：只加例句、記在這篇
  }

  async function addWord(lemma, surface, sentence, meaning, existing) {
    try {
      const r = await api(`/articles/${id}/words`, { method: 'POST', body: { lemma, surface, sentence, meaning: meaning || '' } });
      if (r.action === 'queued') toast(`${r.word} 已送去 AI 整理，好了到「新增單字」確認存入`);
      else toast(`${r.word} 已加到這篇的單字表` + (existing && existing.status === 'active' ? '，這句也存成例句了' : ''));
      await reloadWords();
      // 學過的字：不自動變紅燈，問你要不要
      if (existing && existing.status === 'active' && existing.light !== 'red') askRed(existing);
    } catch (e) { toast(e.message, 'error'); }
  }

  function askRed(ex) {
    const box = h('div', { class: 'side-ask' },
      h('div', {}, `「${ex.word}」目前是${LIGHT_NAMES[ex.light]}，要標成紅燈、明天重新複習嗎？`),
      h('div', { class: 'row' },
        h('button', {
          class: 'small danger', onclick: async () => {
            try { const w = await applyStatus(ex.id, 'light', 'red'); toast(statusToast(w, 'light', 'red')); box.remove(); ex.light = 'red'; await reloadWords(); scan(); }
            catch (e) { toast(e.message, 'error'); }
          },
        }, '標成紅燈'),
        h('button', { class: 'small ghost', onclick: () => box.remove() }, '不用')));
    side.append(box);
    box.scrollIntoView({ block: 'nearest' });
  }

  // ---- 在這句的意思：和學過的比，新的意思可以加進去 ----
  const ctxCache = new Map();  // 同一個字、同一句查過就記住
  function compareLine(res, wid, word, surface, sentence, after) {
    if (res.match == null) return null;
    const known = res.known_meanings || [];
    if (res.match >= 0) {
      const m = known[res.match];
      return h('div', { class: 'ctx-same small' }, '＝ 你學過的意思：', m ? `${m.pos ? m.pos + ' ' : ''}${m.zh}` : '');
    }
    const btn = h('button', {
      class: 'small primary', onclick: async () => {
        btn.disabled = true;
        try {
          await api(`/articles/${id}/words/${wid}/meaning`, { method: 'POST', body: { pos: res.pos || '', zh: res.meaning, surface, sentence } });
          toast(`已把「${res.meaning}」加到 ${word}，這句也存成例句`);
          ctxCache.clear();
          await reloadWords();
          await scan();
          if (after) after();
        } catch (e) { toast(e.message, 'error'); btn.disabled = false; }
      },
    }, `＋ 把這個意思加到 ${word}`);
    return h('div', { class: 'ctx-new' },
      h('div', { class: 'small' }, '⚠ 這是新的意思', known.length ? h('span', { class: 'muted' }, `（你學過的是：${known.map(m => m.zh).join('；')}）`) : null),
      btn);
  }
  function contextMeaningBox(w, ctx, after) {
    const box = h('div', { class: 'ctx-box' });
    const key = `${w.id}|${ctx.sentence}`;
    const show = res => box.replaceChildren(
      h('div', { class: 'sec-label', style: { marginTop: 0 } }, '在這句的意思'),
      h('div', { class: 'side-meaning' }, res.meaning || '—', res.pos ? h('span', { class: 'badge', style: { marginLeft: '6px' } }, res.pos) : null),
      res.note ? h('div', { class: 'small' }, res.note) : null,
      compareLine(res, w.id, w.word, ctx.surface || w.word, ctx.sentence, after));
    const run = async () => {
      box.replaceChildren(h('div', { class: 'muted small row' }, h('span', { class: 'spinner' }), 'AI 正在看上下文…'));
      try {
        const res = await api('/lookup/explain', { method: 'POST', body: { text: ctx.surface || w.word, sentence: ctx.sentence, paragraph: ctx.para || ctx.sentence } });
        ctxCache.set(key, res);
        if (box.isConnected) show(res);
      } catch (e) { box.replaceChildren(h('div', { class: 'warn small' }, 'AI 無法使用：' + e.message), startBtn()); }
    };
    const startBtn = () => h('button', { class: 'small', title: '請 AI 看上下文，判斷這個字在這句是什麼意思、是不是你學過的意思', onclick: run }, '🔍 看這句的意思');
    if (ctxCache.has(key)) show(ctxCache.get(key));
    else box.replaceChildren(startBtn());
    return box;
  }

  async function showCard(wid, ctx = {}) {
    sideMode = 'card'; openSide();
    lookupToken++;
    side.replaceChildren(h('div', { class: 'muted' }, '載入中…'));
    let w;
    try { w = await api('/words/' + wid); } catch (e) { side.replaceChildren(backBtn(), h('div', { class: 'error-box' }, e.message)); return; }
    // 在文章裡打開的字卡：可以請 AI 看這句的意思（按了才查，查過就記住）
    const ctxBox = ctx.sentence ? contextMeaningBox(w, ctx, () => showCard(wid, ctx)) : null;
    const draw = () => side.replaceChildren(
      h('div', { class: 'row' },
        backBtn(), h('span', { class: 'spacer' }),
        ctx.sentence ? h('button', { class: 'small', onclick: e => addExisting({ id: w.id, word: w.word, status: w.status, light: w.stats.light }, ctx.surface || w.word, ctx.sentence, ctx.para, null, e.currentTarget, () => showCard(wid, ctx)) }, '加到這篇的單字表') : null,
        h('button', { class: 'small', onclick: () => openWordModal(wid, { edit: true, onChange: nw => { if (nw) { w = nw; draw(); } else sideHome(); reloadWords(); scan(); } }) }, '✎ 編輯')),
      ctxBox,
      renderDetail(w, {
        onOpenWord: other => showCard(other),
        onStatus: async (kind, value) => {
          try { w = await applyStatus(wid, kind, value); toast(statusToast(w, kind, value)); draw(); reloadWords(); scan(); }
          catch (e) { toast(e.message, 'error'); }
        },
      }));
    draw();
    side.scrollTop = 0;
  }

  // ================= 片語與文法（手填，不進複習）=================
  function phraseForm(p = {}) {
    sideMode = 'phrase'; openSide();
    lookupToken++;
    const text = h('input', { value: p.text || '', placeholder: '例如 no longer、It is ... that ...' });
    const zhIn = h('input', { value: p.zh || '', placeholder: '中文意思，例如：抵達（某地）' });
    const noteIn = h('textarea', { rows: 3, value: p.note || '', placeholder: '用法、搭配、注意的地方（可以空白）' });
    const sent = h('textarea', { rows: 3, value: p.sentence || '', placeholder: '原句（選填）' });
    const save = async () => {
      if (!text.value.trim()) { toast('請填片語或文法', 'error'); text.focus(); return; }
      const body = { text: text.value, zh: zhIn.value, note: noteIn.value, sentence: sent.value };
      try {
        if (p.id) await api('/phrases/' + p.id, { method: 'PUT', body });
        else await api(`/articles/${id}/phrases`, { method: 'POST', body });
        toast(p.id ? '已更新' : '已存到「片語與文法」');
        await reloadPhrases();
        sideHome();
      } catch (e) { toast(e.message, 'error'); }
    };
    side.replaceChildren(
      h('div', { class: 'row', style: { justifyContent: 'space-between' } },
        h('div', { class: 'side-title', style: { margin: 0 } }, p.id ? '修改片語／文法' : '存成片語／文法'), backBtn()),
      h('label', { class: 'field', style: { marginTop: '8px' } }, h('span', {}, '片語或文法'), text),
      h('label', { class: 'field', style: { marginTop: '8px' } }, h('span', {}, '中文'), zhIn),
      h('label', { class: 'field', style: { marginTop: '8px' } }, h('span', {}, '說明'), noteIn),
      h('label', { class: 'field', style: { marginTop: '8px' } }, h('span', {}, '原句'), sent),
      h('div', { class: 'row', style: { marginTop: '10px' } }, h('span', { class: 'spacer' }),
        h('button', { class: 'ghost', onclick: sideHome }, '取消'),
        h('button', { class: 'primary', onclick: save }, '儲存')),
      h('div', { class: 'muted small', style: { marginTop: '8px' } }, '只是筆記，不會進複習。文章裡找得到的片語會畫底線。'),
    );
    (!p.text ? text : !p.zh ? zhIn : noteIn).focus();
  }

  function showPhrase(p) {
    sideMode = 'phrase'; openSide();
    lookupToken++;
    side.replaceChildren(
      h('div', { class: 'row' }, backBtn(), h('span', { class: 'spacer' }),
        h('button', { class: 'small', onclick: () => phraseForm(p) }, '✎ 修改'),
        h('button', { class: 'small ghost danger-text', onclick: () => deletePhrase(p) }, '刪除')),
      h('div', { class: 'side-word' + wordSize(p.text), style: { marginTop: '6px' } }, p.text),
      p.zh ? h('div', { class: 'side-meaning', style: { marginTop: '4px' } }, p.zh) : null,
      p.note ? h('div', { class: 'phrase-note' }, p.note) : (p.zh ? null : h('div', { class: 'muted small' }, '（沒有中文和說明）')),
      p.sentence ? h('div', { class: 'side-sentence', style: { marginTop: '10px' } }, p.sentence) : null,
    );
  }

  async function deletePhrase(p) {
    if (!confirm(`刪除「${p.text}」這筆片語／文法筆記？`)) return;
    try { await api('/phrases/' + p.id, { method: 'DELETE' }); toast('已刪除'); await reloadPhrases(); sideHome(); }
    catch (e) { toast(e.message, 'error'); }
  }

  async function reloadPhrases() {
    try { art.phrases = (await api('/articles/' + id)).phrases; } catch { return; }
    buildPhraseRe(); drawText(); drawPhrases();
  }

  // ================= 左欄：這篇的單字、片語與文法（固定在左邊）=================
  // 重新整理：重新搜尋單字庫（燈號改了、AI 整理好了、在別頁改過），不用離開再進來
  async function refreshAll(btn) {
    if (btn) btn.disabled = true;
    try {
      const a = await api('/articles/' + id);
      art.words = a.words; art.phrases = a.phrases;
      buildPhraseRe(); drawWords(); drawPhrases();
      await scan();  // 會重畫文章標記和右欄清單
      if (btn) toast('已重新整理');
    } catch (e) { toast(e.message, 'error'); }
    finally { if (btn) btn.disabled = false; }
  }
  const refreshBtn = () => {
    const b = h('button', { class: 'ghost icon small', title: '重新搜尋單字庫（燈號、新加的字、片語）', onclick: () => refreshAll(b) }, '🔄');
    return b;
  };

  function drawPhrases() {
    const ps = art.phrases;
    phrasesBox.replaceChildren(
      h('div', { class: 'lc-head' },
        h('span', { class: 'lc-title' }, `片語與文法（${ps.length}）`),
        h('span', { class: 'spacer' }),
        h('button', { class: 'ghost icon small', title: '新增片語或文法', onclick: () => phraseForm({}) }, '＋')),
      ps.length ? h('div', { class: 'lc-list' }, ...ps.map(p => h('div', { class: 'lc-item', title: [p.note, p.sentence].filter(Boolean).join('\n\n') },
        h('a', { href: '#', class: 'lc-main', onclick: e => { e.preventDefault(); showPhrase(p); } },
          h('span', { class: 'lc-en' }, p.text), p.zh ? h('span', { class: 'lc-zh' }, p.zh) : null),
        h('span', { class: 'lc-acts' },
          h('button', { class: 'ghost icon', title: '修改', onclick: () => phraseForm(p) }, '✎'),
          h('button', { class: 'ghost icon', title: '刪除', onclick: () => deletePhrase(p) }, '✕')))))
        : h('div', { class: 'muted small lc-empty' }, '選取片語或句子，按「存成片語／文法」，或按 ＋ 自己寫。'),
      h('a', { href: '#/phrases', class: 'small lc-foot' }, '所有文章的片語 →'),
    );
  }

  // ================= 單字表 =================
  async function reloadWords() {
    try { art.words = (await api('/articles/' + id)).words; } catch { return; }
    drawWords();
    buildMarks(); drawText();  // 灰色字的標記跟著更新
  }
  async function addLocal(lemma, surface, sentence, meaning) {
    try {
      const r = await api(`/articles/${id}/words/local`, { method: 'POST', body: { lemma, surface, sentence, meaning } });
      toast(`${r.word} 只記在這篇（灰色）`);
      await reloadWords();
      const x = art.words.find(w => w.lemma.toLowerCase() === r.word.toLowerCase());
      if (x) showLocal(x);
    } catch (e) { toast(e.message, 'error'); }
  }
  // 灰色字：只記在這篇，不進單字庫
  function showLocal(x) {
    sideMode = 'local'; openSide();
    lookupToken++;
    const zh = h('input', { value: x.meaning || '', placeholder: '中文意思' });
    const saveZh = async () => {
      if (zh.value.trim() === (x.meaning || '')) return;
      try {
        await api(`/articles/${id}/words/${x.id}/meaning`, { method: 'PUT', body: { meaning: zh.value } });
        x.meaning = zh.value.trim(); toast('已儲存'); drawWords(); buildMarks(); drawText();
      } catch (e) { toast(e.message, 'error'); }
    };
    zh.addEventListener('change', saveZh);
    side.replaceChildren(
      h('div', { class: 'row' }, backBtn(), h('span', { class: 'spacer' }), h('span', { class: 'badge local-badge' }, '只記在這篇')),
      h('div', { class: 'side-head', style: { marginTop: '6px' } },
        h('span', { class: 'side-word' + wordSize(x.lemma) }, x.lemma),
        h('button', { class: 'speak', title: '發音', onclick: () => speak(x.lemma) }, '🔊'),
        copyButton(x.lemma)),
      h('label', { class: 'field', style: { marginTop: '8px' } }, h('span', {}, '中文'), zh),
      x.sentence ? h('div', { class: 'side-sentence', style: { marginTop: '10px' } }, x.sentence) : null,
      h('div', { class: 'side-actions' },
        h('button', { class: 'small', title: '改成一般生字：送 AI 整理、進單字庫和複習', onclick: () => addWord(x.lemma, x.surface || x.lemma, x.sentence, x.meaning, null) }, '＋ 改成加入單字庫'),
        h('button', { class: 'small ghost danger-text', onclick: async () => { await api(`/articles/${id}/words/${x.id}`, { method: 'DELETE' }); await reloadWords(); sideHome(); } }, '從這篇移除')),
      h('div', { class: 'muted small', style: { marginTop: '8px' } }, '灰色的字只列在這篇，不會進單字庫、也不會出現在複習裡。'),
    );
  }

  function drawWords() {
    const all = mergedWords();
    const count = k => all.filter(v => (k === 'added' ? v.added : v.light === k)).length;
    const list = all.filter(passFilter);
    const nAdded = art.words.filter(x => x.word && x.word.status === 'active').length;
    wordsBox.replaceChildren(
      h('div', { class: 'lc-head' },
        h('span', { class: 'lc-title' }, `這篇的單字（${all.length}）`),
        h('span', { class: 'spacer' }),
        refreshBtn()),
      h('div', { class: 'lc-filters' }, ...FILTERS.map(([k, t]) => {
        const n = k === 'all' ? all.length : count(k);
        if (k !== 'all' && !n) return null;
        return h('button', { type: 'button', class: 'lc-filter' + (wordFilter === k ? ' on' : ''), onclick: () => { wordFilter = k; drawWords(); } },
          k === 'all' ? t : `${t} ${n}`);
      })),
      list.length ? h('div', { class: 'lc-list' }, ...list.map(v => h('div', {
        class: 'lc-item', title: [v.surface && v.surface.toLowerCase() !== v.word.toLowerCase() ? `文章裡：${v.surface}` : '', v.sentence].filter(Boolean).join('\n'),
      },
        itemState(v),
        v.kind === 'pending'
          ? h('span', { class: 'lc-main' }, h('span', { class: 'lc-en' }, v.word), v.zh ? h('span', { class: 'lc-zh' }, v.zh) : null)
          : h('a', { href: '#', class: 'lc-main', onclick: e => { e.preventDefault(); openItem(v); } },
            h('span', { class: 'lc-en' }, v.word), v.zh ? h('span', { class: 'lc-zh' }, v.zh) : null),
        v.n > 1 ? h('span', { class: 'lc-n muted' }, `×${v.n}`) : null,
        v.added && !v.row.local ? h('span', { class: 'lc-added', title: '在這篇加入的' }, '＋') : null,
        v.row ? h('span', { class: 'lc-acts' }, h('button', {
          class: 'ghost icon', title: '從這篇的單字表移除（單字本身不會刪）', onclick: async () => {
            await api(`/articles/${id}/words/${v.row.id}`, { method: 'DELETE' }); reloadWords();
          },
        }, '✕')) : null)))
        : h('div', { class: 'muted small lc-empty' }, all.length ? '這個篩選沒有字' : (targets.length || art.words.length ? '這篇沒有你不熟的字。' : '正在找…')),
      nAdded ? h('button', { class: 'small lc-foot', title: '自由複習，出處選這篇（這篇加入的字＋文章裡出現的字）', onclick: () => { location.hash = '#/free?source=' + encodeURIComponent(art.title); } }, '複習這篇的字') : null,
    );
  }

  // ================= AI 排版 =================
  function drawBanner() {
    const st = art.layout_state;
    if (st === 'pending') {
      const j = art.layout_job;
      const prog = !j || !j.total ? '' : j.phase === 'split' ? `（切開太長的段落 ${j.done}/${j.total}）` : `（${j.done}/${j.total} 行）`;
      banner.replaceChildren(h('div', { class: 'layout-banner' }, h('span', { class: 'spinner' }),
        `AI 正在重新排版${prog}… 可以先讀，好了會問你要不要套用。`));
    } else if (st === 'ready') {
      banner.replaceChildren(h('div', { class: 'layout-banner accent' }, 'AI 排版好了（分段、標題、去掉頁碼等雜訊）。',
        h('span', { class: 'spacer' }),
        h('button', {
          class: 'small primary', onclick: async () => {
            try { art = { ...art, ...(await api(`/articles/${id}/layout/apply`, { method: 'POST' })) }; drawText(); drawBanner(); drawTools(); if (sideMode === 'home') sideHome(); toast('已套用 AI 排版'); }
            catch (e) { toast(e.message, 'error'); }
          },
        }, '套用'),
        h('button', { class: 'small ghost', onclick: async () => { await api(`/articles/${id}/layout/dismiss`, { method: 'POST' }); art.layout_state = 'rule'; drawBanner(); } }, '維持現在的')));
    } else {
      banner.replaceChildren(...(art.layout_error ? [h('div', { class: 'layout-banner warn' }, 'AI 排版失敗，目前是自動規則排版。',
        h('span', { class: 'spacer' }), redoBtn())] : []));
    }
  }
  const redoBtn = () => h('button', {
    class: 'small ghost', onclick: async () => {
      if (art.layout_state === 'manual' && !confirm('重新 AI 排版會從原文重排。\n好了之後按「套用」才會換掉你手動改的排版，按「維持現在的」就不會。\n要開始嗎？')) return;
      await api(`/articles/${id}/layout/redo`, { method: 'POST' });
      art.layout_state = 'pending'; art.layout_error = null; drawBanner(); poll();
    },
  }, '重新 AI 排版');
  async function poll() {
    clearTimeout(pollTimer);
    if (!alive || art.layout_state !== 'pending') return;
    pollTimer = setTimeout(async () => {
      try {
        const a = await api('/articles/' + id);
        art.layout_state = a.layout_state; art.layout_job = a.layout_job; art.layout_error = a.layout_error;
        drawBanner();
      } catch { /* 下次再試 */ }
      poll();
    }, 2000);
  }

  // ================= 手動編輯排版（Markdown）=================
  // 只有整段的格式：## 大標、### 小標、- 條列、> 引用、~ 雜訊；空一行是新的一段。粗體、斜體等符號存的時候自動拿掉。
  const bodyToMarkdown = body => body.map((b, i) => {
    if (b.t === 'h') return ((b.l || (i === 0 ? 2 : 3)) === 2 ? '## ' : '### ') + b.text;
    if (b.t === 'li') return '- ' + b.text;
    if (b.t === 'q') return '> ' + b.text;
    if (b.t === 'x') return '~ ' + b.text;
    return b.text;
  }).join('\n\n');
  const layoutTa = h('textarea', { class: 'md-input layout-input', spellcheck: 'false' });
  const layoutEditor = h('div', { class: 'panel layout-editor hidden' },
    mdToolbar(layoutTa, ['h2', 'h3', 'li', 'q', 'x'], [
      h('button', { type: 'button', class: 'small ghost', onclick: () => closeLayoutEditor() }, '取消'),
      h('button', { type: 'button', class: 'small primary', onclick: () => saveLayout() }, '儲存排版')]),
    h('div', { class: 'muted small', style: { margin: '0 0 6px' } },
      '空一行＝新的一段。行首：## 大標　### 小標　- 條列　> 引用　~ 雜訊（灰色小字、朗讀跳過）。只改排版就好，改到文字的話查字、標記也會跟著新的文字。'),
    layoutTa);
  const editLayoutBtn = h('button', { class: 'small', onclick: () => openLayoutEditor() }, '✎ 編輯排版');
  function openLayoutEditor() {
    stopReading();
    layoutTa.value = bodyToMarkdown(art.body);
    layoutTa.style.height = Math.min(Math.max(textEl.offsetHeight, 300), innerHeight * 0.75) + 'px';
    textEl.classList.add('hidden');
    layoutEditor.classList.remove('hidden');
    editLayoutBtn.disabled = true;
    layoutTa.focus();
    layoutTa.setSelectionRange(0, 0);
    layoutTa.scrollTop = 0;
  }
  function closeLayoutEditor() {
    layoutEditor.classList.add('hidden');
    textEl.classList.remove('hidden');
    editLayoutBtn.disabled = false;
  }
  async function saveLayout() {
    try {
      art = { ...art, ...(await api(`/articles/${id}/body`, { method: 'PUT', body: { markdown: layoutTa.value } })) };
    } catch (e) { toast(e.message, 'error'); return; }
    closeLayoutEditor();
    drawText(); drawBanner(); drawTools();
    if (sideMode === 'home') sideHome();
    toast('已儲存排版');
  }

  // ================= 記住讀到哪裡 =================
  // 畫面最上面那一段的編號存到伺服器（Mac、Windows 共用）；下次打開捲回去
  let savedPi = art.read_pi || 0;
  let posTimer = null;
  function currentPi() {
    for (const p of textEl.querySelectorAll('[data-pi]')) {
      if (p.getBoundingClientRect().bottom > 80) return Number(p.dataset.pi);
    }
    return 0;
  }
  const onScroll = () => {
    clearTimeout(posTimer);
    posTimer = setTimeout(() => {
      if (!alive) return;
      const pi = currentPi();
      if (pi === savedPi) return;
      savedPi = pi;
      api(`/articles/${id}/read-pos`, { method: 'PUT', body: { pi } }).catch(() => {});
    }, 1200);
  };

  // ================= 組合 =================
  const toolsEl = h('div', { class: 'row reader-tools' });
  function drawTools() {
    toolsEl.replaceChildren(
      h('button', { class: 'small m-only', onclick: () => { side.classList.remove('open'); document.body.classList.toggle('show-left'); } }, '📋 這篇的單字'),
      readBtn, rateSel, sizeSel, marksBtn, h('span', { class: 'spacer' }), editLayoutBtn,
      ['ai', 'rule', 'manual'].includes(art.layout_state) ? redoBtn() : null);
  }
  drawTools();
  buildPhraseRe();
  drawHead(); drawText(); drawWords(); drawPhrases(); drawBanner(); sideHome(); poll();
  document.body.classList.add('reader-wide');  // 文章頁三欄，畫面放寬
  el.append(
    h('div', { class: 'reader' },
      h('aside', { class: 'reader-left' },
        h('button', { class: 'small ghost m-only left-close', onclick: () => document.body.classList.remove('show-left') }, '✕ 收起'),
        h('div', { class: 'lc-box' }, wordsBox),
        h('div', { class: 'lc-box' }, phrasesBox)),
      h('div', { class: 'reader-main' },
        h('div', { class: 'reader-top' },
          h('a', { href: '#/articles', class: 'small' }, '← 文章清單'),
          titleEl, sourceEl,
          toolsEl,
          readHint,
          banner),
        textEl,
        layoutEditor,
        h('div', { class: 'panel reader-note' }, h('h2', {}, '文章備註'), note.el),
      ),
      side,
    ),
  );
  scan();
  if (savedPi > 0) {
    requestAnimationFrame(() => {
      const p = textEl.querySelector(`[data-pi="${savedPi}"]`);
      if (p) { p.scrollIntoView({ block: 'start' }); scrollBy(0, -80); toast('已回到上次讀到的地方'); }
    });
  }
  window.addEventListener('scroll', onScroll, { passive: true });
  return () => {
    alive = false; clearTimeout(pollTimer); clearTimeout(posTimer); stopReading();
    document.body.classList.remove('reader-wide', 'show-left');
    document.removeEventListener('selectionchange', onSelChange);
    window.removeEventListener('scroll', onScroll);
    if (note.editing) note.finish();  // 離開頁面時備註還在編輯就先存
  };
}
