// 簡單的 Markdown：只支援筆記常用的幾種（標題、條列、粗體、斜體、引用、分隔線、程式碼）
// 自己寫、不用套件；所有文字都先跳脫，不會執行貼進來的 HTML。
import { h } from './util.js';

const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

function inline(s) {
  let t = esc(s);
  t = t.replace(/`([^`]+)`/g, '<code>$1</code>');
  t = t.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  t = t.replace(/(^|[^*])\*([^*\s][^*]*)\*/g, '$1<em>$2</em>');
  return t;
}

export function markdownHtml(text) {
  const lines = (text || '').replace(/\r\n?/g, '\n').split('\n');
  const out = [];
  let list = null;   // 'ul' | 'ol'
  let para = [];
  const flushPara = () => { if (para.length) { out.push(`<p>${para.map(inline).join('<br>')}</p>`); para = []; } };
  const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };
  for (const raw of lines) {
    const line = raw.replace(/\s+$/, '');
    let m;
    if (!line.trim()) { flushPara(); closeList(); continue; }
    if ((m = line.match(/^(#{1,3})\s+(.*)$/))) {
      flushPara(); closeList();
      const lv = m[1].length + 2;  // # → h3、## → h4、### → h5（備註裡的標題不要比頁面標題大）
      out.push(`<h${lv}>${inline(m[2])}</h${lv}>`);
    } else if (/^(-{3,}|\*{3,})$/.test(line.trim())) {
      flushPara(); closeList(); out.push('<hr>');
    } else if ((m = line.match(/^\s*[-*•]\s+(.*)$/)) || (m = line.match(/^\s*\d+[.)]\s+(.*)$/))) {
      flushPara();
      const kind = /^\s*\d/.test(line) ? 'ol' : 'ul';
      if (list !== kind) { closeList(); out.push(`<${kind}>`); list = kind; }
      out.push(`<li>${inline(m[1])}</li>`);
    } else if ((m = line.match(/^>\s?(.*)$/))) {
      flushPara(); closeList(); out.push(`<blockquote>${inline(m[1])}</blockquote>`);
    } else {
      closeList(); para.push(line);
    }
  }
  flushPara(); closeList();
  return out.join('');
}

// 工具列：按了在文字框裡加上（或拿掉）整行的符號、或把選的字加粗。tools 可用：h2 h3 li b q x
export function mdToolbar(ta, tools, extra = []) {
  const wrapLine = (prefix) => () => {
    const { selectionStart: a, selectionEnd: b, value: v } = ta;
    const ls = v.lastIndexOf('\n', a - 1) + 1;
    let le = v.indexOf('\n', b);
    if (le < 0) le = v.length;
    const block = v.slice(ls, le).split('\n')
      .map(l => (l.startsWith(prefix) ? l.slice(prefix.length) : prefix + l.replace(/^(#{1,3}\s+|[-*]\s+|>\s?|~\s?)/, '')))
      .join('\n');
    ta.setRangeText(block, ls, le, 'select');
    ta.focus();
  };
  const wrapSel = mark => () => {
    const { selectionStart: a, selectionEnd: b, value: v } = ta;
    const sel = v.slice(a, b) || '文字';
    ta.setRangeText(mark + sel + mark, a, b, 'end');
    ta.setSelectionRange(a + mark.length, a + mark.length + sel.length);
    ta.focus();
  };
  const defs = {
    h2: ['大標', '大標題（## ）', wrapLine('## ')],
    h3: ['小標', '小標題（### ）', wrapLine('### ')],
    li: ['• 條列', '條列（- ）', wrapLine('- ')],
    b: ['B', '粗體（**文字**）', wrapSel('**')],
    q: ['引用', '引用（> ）', wrapLine('> ')],
    x: ['雜訊', '頁碼、頁首這類雜訊（~ ），顯示成灰色小字、朗讀時跳過', wrapLine('~ ')],
  };
  return h('div', { class: 'md-toolbar' },
    ...tools.map(k => h('button', { type: 'button', class: 'small ghost', title: defs[k][1], onmousedown: e => e.preventDefault(), onclick: defs[k][2] }, defs[k][0])),
    h('span', { class: 'spacer' }), ...extra);
}

// 筆記框：平常顯示排版好的樣子，點一下（或按 ✎）進入編輯；上方有工具列，不用背語法
// opts: { value, placeholder, onSave(text) → Promise }
export function noteEditor(opts) {
  let value = opts.value || '';
  let editing = false;
  const view = h('div', { class: 'md-view', title: '點一下編輯' });
  const ta = h('textarea', { class: 'md-input', rows: 8, placeholder: opts.placeholder || '' });
  const toolbar = mdToolbar(ta, ['h2', 'h3', 'li', 'b', 'q'],
    [h('button', { type: 'button', class: 'small primary', onclick: () => finish() }, '完成')]);
  const editBox = h('div', { class: 'md-edit hidden' }, toolbar, ta,
    h('div', { class: 'muted small' }, '可以直接打：## 大標　### 小標　- 條列　**粗體**　> 引用'));
  const box = h('div', { class: 'md-note' }, view, editBox);

  function drawView() {
    if (value.trim()) { view.innerHTML = markdownHtml(value); view.classList.remove('empty'); }
    else { view.textContent = opts.placeholder || '（空白，點一下開始寫）'; view.classList.add('empty'); }
  }
  function edit() {
    if (editing) return;
    editing = true;
    ta.value = value;
    view.classList.add('hidden');
    editBox.classList.remove('hidden');
    ta.focus();
  }
  async function finish() {
    if (!editing) return;
    const nv = ta.value;
    if (nv !== value) {
      try { await opts.onSave(nv); value = nv; }
      catch { return; }  // 存失敗就留在編輯狀態
    }
    editing = false;
    editBox.classList.add('hidden');
    view.classList.remove('hidden');
    drawView();
  }
  view.addEventListener('click', e => { if (!e.target.closest('a')) edit(); });
  ta.addEventListener('keydown', e => { if (e.key === 'Escape' || ((e.ctrlKey || e.metaKey) && e.key === 'Enter')) { e.preventDefault(); finish(); } });
  // 點到筆記框外面就自動存
  ta.addEventListener('blur', () => setTimeout(() => { if (editing && !box.contains(document.activeElement)) finish(); }, 150));
  drawView();
  return { el: box, edit, finish, get editing() { return editing; } };
}
