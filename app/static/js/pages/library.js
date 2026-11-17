// 單字庫：表格檢視全部資料（資料庫可視化）
import { api, h, lightDot, progressDots, toast } from '../util.js';
import { openWordModal } from '../wordmodal.js';

const COLUMNS = [
  ['light', '燈號'],
  ['word', '英文'],
  ['pos', '詞性'],
  ['zh', '中文（主要）'],
  ['category', '主分類'],
  ['correct_count', '答對'],
  ['wrong_count', '答錯'],
  ['forget_count', '遺忘'],
  ['added_day', '加入日期'],
  ['due_day', '下次複習'],
];
const LIGHT_ORDER = { red: 0, yellow: 1, green: 2 };

// 'YYYY-MM-DD' 加減天數
function shiftDay(day, n) {
  const d = new Date(day + 'T00:00:00Z');
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

export async function render(el) {
  let [rows, cats, status] = await Promise.all([api('/words'), api('/categories'), api('/status')]);
  const today = status.today;  // 照程式的換日時間算的「今天」
  const state = { q: '', cat: '', lights: new Set(['red', 'yellow', 'green']), sort: 'added_day', dir: -1 };

  // ---- 日期篩選：加入日期、下次複習 ----
  const dateFilter = (label, presets, onChange) => {
    const from = h('input', { type: 'date', class: 'date-in' });
    const to = h('input', { type: 'date', class: 'date-in' });
    const custom = h('span', { class: 'row hidden', style: { gap: '4px' } }, from, '～', to);
    const sel = h('select', {}, ...presets.map(([v, t]) => h('option', { value: v }, t)));
    const f = { sel, from, to, get value() { return sel.value; } };
    const changed = () => { custom.classList.toggle('hidden', sel.value !== 'custom'); onChange(); };
    sel.addEventListener('change', changed);
    from.addEventListener('change', onChange);
    to.addEventListener('change', onChange);
    f.el = h('label', { class: 'date-filter' }, h('span', { class: 'muted small' }, label), sel, custom);
    return f;
  };
  const addedF = dateFilter('加入日期', [['', '全部'], ['today', '今天'], ['7', '最近 7 天'], ['30', '最近 30 天'], ['custom', '自訂…']], () => draw());
  const dueF = dateFilter('下次複習', [['', '全部'], ['due', '今天要複習（含過期）'], ['overdue', '已過期'], ['week', '7 天內'], ['graduated', '已畢業'], ['custom', '自訂…']], () => draw());
  const inRange = (d, a, b) => !!d && (!a || d >= a) && (!b || d <= b);
  function addedOk(r) {
    const v = addedF.value;
    if (!v) return true;
    if (v === 'today') return r.added_day === today;
    if (v === 'custom') return inRange(r.added_day, addedF.from.value, addedF.to.value);
    return inRange(r.added_day, shiftDay(today, 1 - Number(v)), today);
  }
  function dueOk(r) {
    const v = dueF.value;
    if (!v) return true;
    if (v === 'graduated') return !!r.graduated;
    if (r.graduated) return false;
    if (v === 'due') return !!r.due_day && r.due_day <= today;
    if (v === 'overdue') return !!r.due_day && r.due_day < today;
    if (v === 'week') return inRange(r.due_day, null, shiftDay(today, 6));
    return inRange(r.due_day, dueF.from.value, dueF.to.value);
  }

  const search = h('input', { placeholder: '搜尋英文或中文…', oninput: e => { state.q = e.target.value.trim().toLowerCase(); draw(); } });
  const catSel = h('select', { onchange: e => { state.cat = e.target.value; draw(); } },
    h('option', { value: '' }, '全部分類'),
    ...cats.map(c => h('option', { value: c.id }, (c.depth ? '　' : '') + c.name + (c.count ? ` (${c.count})` : ''))));
  const lightFilter = h('div', { class: 'light-filter' }, ...['red', 'yellow', 'green'].map(l => h('label', {},
    h('input', { type: 'checkbox', checked: true, onchange: e => { e.target.checked ? state.lights.add(l) : state.lights.delete(l); draw(); } }),
    lightDot(l), { red: '紅', yellow: '黃', green: '綠' }[l])));
  const countLine = h('span', { class: 'muted small' });
  let shown = [];
  const exportBtn = h('button', { class: 'small', onclick: () => exportCsv(shown.map(r => r.id)) }, '匯出 CSV');

  async function exportCsv(ids) {
    exportBtn.disabled = true;
    try {
      const res = await fetch('/api/export', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids }),
      });
      if (!res.ok) throw new Error('匯出失敗');
      const m = /filename\*=UTF-8''([^;]+)/.exec(res.headers.get('Content-Disposition') || '');
      const name = m ? decodeURIComponent(m[1]) : 'vocab.csv';
      const url = URL.createObjectURL(await res.blob());
      const a = h('a', { href: url, download: name });
      document.body.append(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
      toast(`已匯出 ${ids.length} 個字（${name}）`);
    } catch (e) {
      toast(e.message, 'error');
    } finally {
      exportBtn.disabled = !shown.length;
    }
  }

  const thead = h('thead');
  const tbody = h('tbody');
  const table = h('table', { class: 'data' }, thead, tbody);

  function drawHead() {
    thead.replaceChildren(h('tr', {}, ...COLUMNS.map(([key, label]) => h('th', {
      class: state.sort === key ? 'sorted' : '',
      onclick: () => {
        if (state.sort === key) state.dir = -state.dir;
        else { state.sort = key; state.dir = 1; }
        drawHead(); draw();
      },
    }, label + (state.sort === key ? (state.dir > 0 ? ' ▲' : ' ▼') : '')))));
  }

  function inCategory(r) {
    if (!state.cat) return true;
    const id = Number(state.cat);
    const ids = new Set([id, ...cats.filter(c => c.parent_id === id).map(c => c.id)]);
    return r.category_ids.some(c => ids.has(c));
  }

  function draw() {
    const q = state.q;
    const list = rows.filter(r =>
      state.lights.has(r.light) && inCategory(r) && addedOk(r) && dueOk(r) &&
      (!q || r.word.toLowerCase().includes(q) || (r.zh || '').includes(q)));
    const key = state.sort;
    list.sort((a, b) => {
      let x = a[key], y = b[key];
      if (key === 'light') { x = LIGHT_ORDER[x]; y = LIGHT_ORDER[y]; }
      if (x === y) return a.id - b.id;
      if (x === null || x === undefined || x === '') return 1;
      if (y === null || y === undefined || y === '') return -1;
      return (typeof x === 'string' ? x.localeCompare(y) : x - y) * state.dir;
    });
    countLine.textContent = `顯示 ${list.length} / ${rows.length} 個字`;
    shown = list;
    exportBtn.textContent = list.length === rows.length ? `匯出 CSV（全部 ${list.length} 個）` : `匯出 CSV（目前顯示的 ${list.length} 個）`;
    exportBtn.disabled = !list.length;
    tbody.replaceChildren(...list.map(r => h('tr', { onclick: () => openWordModal(r.id, { onChange: reload }) },
      h('td', {}, lightDot(r.light)),
      h('td', { class: 'w' }, r.word),
      h('td', { class: 'muted' }, r.pos),
      h('td', { class: 'zh' }, r.zh),
      h('td', { class: 'muted small' }, r.category),
      h('td', { class: 'num' }, r.graduated ? '✓' : progressDots(r.correct_count)),
      h('td', { class: 'num' }, r.wrong_count || ''),
      h('td', { class: 'num' }, r.forget_count ? h('span', { class: 'badge red' }, r.forget_count) : ''),
      h('td', { class: 'small muted' }, r.added_day || ''),
      h('td', { class: 'small muted' }, r.graduated ? '畢業' : (r.due_day || '')),
    )));
    if (!list.length) tbody.append(h('tr', {}, h('td', { colspan: COLUMNS.length, class: 'empty' }, rows.length ? '沒有符合條件的字' : '還沒有單字')));
  }

  async function reload() {
    [rows, cats] = await Promise.all([api('/words'), api('/categories')]);
    draw();
  }

  el.append(
    h('h1', {}, '單字庫'),
    h('div', { class: 'filters' }, search, catSel, lightFilter),
    h('div', { class: 'row date-filters' }, addedF.el, dueF.el),
    h('div', { class: 'row', style: { marginBottom: '8px' } }, countLine, h('span', { class: 'spacer' }), exportBtn),
    h('div', { class: 'table-wrap' }, table),
  );
  drawHead();
  draw();
}
