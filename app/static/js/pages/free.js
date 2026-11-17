// 自由複習：自己選範圍（可複選、可組合），可以存成常用組合
// 版面：左邊是條件（每個條件收在下拉選單裡，按鈕上寫目前選了什麼），右邊固定顯示符合幾個字、測驗方式、開始按鈕。
// 分類、文章再多，畫面也不會變長。
import { api, h, lightDot, toast } from '../util.js';
import { modePicker, runSession } from '../session.js';
import { runMatch } from '../match.js';

const LIGHT_NAMES = { red: '紅燈', yellow: '黃燈', green: '綠燈' };
const ADDED_PRESETS = [['', '全部'], ['today', '今天'], ['7', '最近 7 天'], ['30', '最近 30 天'], ['custom', '自訂…']];
const DUE_PRESETS = [['', '全部'], ['due', '今天要複習（含過期）'], ['overdue', '已過期'], ['week', '7 天內'], ['graduated', '已畢業'], ['custom', '自訂…']];
const PREVIEW = 12;

const emptyFilter = () => ({
  cats: new Set(), lights: new Set(['red', 'yellow']),  // 預設不選綠燈（已經會了的字）
  added: { p: '', from: '', to: '' }, due: { p: '', from: '', to: '' },
  forget: 0, rate: 0, pos: new Set(), sources: new Set(), ctxOnly: false,
});

const serialize = f => ({
  cats: [...f.cats], lights: [...f.lights], added: { ...f.added }, due: { ...f.due },
  forget: f.forget, rate: f.rate, pos: [...f.pos], sources: [...f.sources], ctxOnly: f.ctxOnly,
});

const deserialize = d => {
  const f = {
    ...emptyFilter(), ...d,
    cats: new Set(d.cats || []), lights: new Set(d.lights || ['red', 'yellow', 'green']),
    pos: new Set(d.pos || []), sources: new Set(d.sources || []),
    added: { p: '', from: '', to: '', ...(d.added || {}) }, due: { p: '', from: '', to: '', ...(d.due || {}) },
  };
  if (!d.added && (d.from || d.to)) f.added = { p: 'custom', from: d.from || '', to: d.to || '' };  // 舊版存的加入日期
  delete f.from; delete f.to;
  return f;
};

function shiftDay(day, n) {
  const d = new Date(day + 'T00:00:00Z');
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}
const inRange = (d, a, b) => !!d && (!a || d >= a) && (!b || d <= b);
const short = (s, n = 14) => (s.length > n ? s.slice(0, n) + '…' : s);

export async function render(el) {
  const [rows, cats, status, articleList] = await Promise.all([api('/words'), api('/categories'), api('/status'), api('/articles')]);
  let saved = await api('/filters');
  const today = status.today;
  let cleanup = null;

  if (!rows.length) {
    el.append(h('h1', {}, '自由複習'), h('div', { class: 'panel empty' }, '還沒有單字。', h('a', { href: '#/add' }, '去新增單字 →')));
    return;
  }

  let f = emptyFilter();
  // 從文章頁按「複習這篇的字」：#/free?source=文章標題
  const fromSource = new URLSearchParams(location.hash.split('?')[1] || '').get('source');
  if (fromSource) f.sources = new Set([fromSource]);
  let activeSaved = null;  // 目前套用的常用組合 id

  // ---------- 資料 ----------
  const childrenOf = id => cats.filter(c => c.parent_id === id).map(c => c.id);
  const catCount = new Map(cats.map(c => {
    const ids = new Set(c.depth ? [c.id] : [c.id, ...childrenOf(c.id)]);
    return [c.id, rows.filter(r => r.category_ids.some(x => ids.has(x))).length];
  }));
  const tops = cats.filter(c => !c.depth && catCount.get(c.id) > 0);
  const catLabel = id => { const c = cats.find(x => x.id === id); return c ? c.path.replace('/', ' › ') : '（已刪除的分類）'; };
  const posValues = [...new Set(rows.flatMap(r => r.pos_list))].sort();
  // 出處文章：最近讀的排前面，其他出處照字母
  const opened = new Map(articleList.map(a => [a.title, a.opened_at || a.created_at || '']));
  const sourceCount = new Map();
  rows.forEach(r => r.sources.forEach(s => sourceCount.set(s, (sourceCount.get(s) || 0) + 1)));
  const sourceValues = [...sourceCount.keys()].sort((a, b) => (opened.get(b) || '').localeCompare(opened.get(a) || '') || a.localeCompare(b));

  // ---------- 篩選 ----------
  function addedOk(r) {
    const { p, from, to } = f.added;
    if (!p) return true;
    if (p === 'today') return r.added_day === today;
    if (p === 'custom') return inRange(r.added_day, from, to);
    return inRange(r.added_day, shiftDay(today, 1 - Number(p)), today);
  }
  function dueOk(r) {
    const { p, from, to } = f.due;
    if (!p) return true;
    if (p === 'graduated') return !!r.graduated;
    if (r.graduated) return false;
    if (p === 'due') return !!r.due_day && r.due_day <= today;
    if (p === 'overdue') return !!r.due_day && r.due_day < today;
    if (p === 'week') return inRange(r.due_day, null, shiftDay(today, 6));
    return inRange(r.due_day, from, to);
  }
  function matches(r) {
    if (f.cats.size) {
      const ids = new Set();
      for (const id of f.cats) { ids.add(id); childrenOf(id).forEach(c => ids.add(c)); }
      if (!r.category_ids.some(id => ids.has(id))) return false;
    }
    if (!f.lights.has(r.light)) return false;
    if (!addedOk(r) || !dueOk(r)) return false;
    if (r.forget_count < f.forget) return false;
    if (f.rate > 0 && (!r.answers || r.wrong_answers / r.answers * 100 < f.rate)) return false;
    if (f.pos.size && !r.pos_list.some(p => f.pos.has(p))) return false;
    if (f.sources.size && !r.sources.some(s => f.sources.has(s))) return false;
    if (f.ctxOnly && !r.has_context) return false;
    return true;
  }

  // ---------- 條件的文字說明 ----------
  const catNames = () => [...f.cats].filter(id => {  // 大類已選的話，不再列出它底下的小類
    const c = cats.find(x => x.id === id);
    return !(c && c.depth && f.cats.has(c.parent_id));
  }).map(catLabel);
  const dateText = (d, presets) => (d.p === 'custom'
    ? `${d.from || '…'}～${d.to || '…'}`
    : (presets.find(([v]) => v === d.p) || ['', ''])[1]);
  const moreCount = () => (f.forget ? 1 : 0) + (f.rate ? 1 : 0) + (f.pos.size ? 1 : 0) + (f.ctxOnly ? 1 : 0);
  const listText = (names, unit) => (names.length === 1 ? short(names[0]) : `${short(names[0], 10)} 等 ${names.length} ${unit}`);

  function autoName() {
    const parts = [...catNames()];
    if (f.lights.size && f.lights.size < 3) parts.push([...f.lights].map(l => LIGHT_NAMES[l]).join('/'));
    if (f.added.p) parts.push('加入' + dateText(f.added, ADDED_PRESETS));
    if (f.due.p) parts.push('複習' + dateText(f.due, DUE_PRESETS));
    if (f.forget) parts.push(`忘記≥${f.forget}`);
    if (f.rate) parts.push(`答錯率≥${f.rate}%`);
    if (f.pos.size) parts.push([...f.pos].join('/'));
    f.sources.forEach(s => parts.push(s));
    if (f.ctxOnly) parts.push('有原文句子');
    return parts.join('＋') || '全部';
  }

  // ---------- 下拉選單 ----------
  let openDD = null;
  const closeDD = () => { if (openDD) { openDD.panel.classList.add('hidden'); openDD.btn.classList.remove('open'); openDD = null; } };
  const onDocClick = e => { if (openDD && !openDD.wrap.contains(e.target)) closeDD(); };
  const onDocKey = e => { if (e.key === 'Escape') closeDD(); };
  document.addEventListener('mousedown', onDocClick);
  document.addEventListener('keydown', onDocKey);

  const dropdowns = [];
  function dropdown(title, label, isOn, build) {
    const btn = h('button', { type: 'button', class: 'dd-btn' });
    const panel = h('div', { class: 'dd-panel hidden' });
    const wrap = h('div', { class: 'dd' }, btn, panel);
    const dd = {
      wrap, btn, panel,
      draw() {
        btn.replaceChildren(h('span', { class: 'dd-k' }, title + '：'), h('span', { class: 'dd-v' }, label()), h('span', { class: 'dd-caret' }, '▾'));
        btn.classList.toggle('on', isOn());
      },
      fill() { panel.replaceChildren(...[].concat(build())); },
    };
    btn.addEventListener('click', () => {
      if (openDD === dd) { closeDD(); return; }
      closeDD();
      dd.fill();
      panel.classList.remove('hidden');
      btn.classList.add('open');
      openDD = dd;
      const inp = panel.querySelector('input[type=search]');
      if (inp) inp.focus();
    });
    dd.draw();
    dropdowns.push(dd);
    return wrap;
  }

  const check = (on, label, onchange, extra = {}) => h('label', { class: 'dd-check', ...extra },
    h('input', { type: 'checkbox', checked: on, onchange: e => onchange(e.target.checked) }), label);

  // 分類：樹狀，大類預設收合；有搜尋框
  const expanded = new Set();
  function catPanel() {
    const list = h('div', { class: 'dd-list' });
    const search = h('input', { type: 'search', placeholder: '搜尋分類…', oninput: () => drawList() });
    function toggleCat(c, on) {
      if (!c.depth) [c.id, ...childrenOf(c.id)].forEach(id => (on ? f.cats.add(id) : f.cats.delete(id)));
      else {
        on ? f.cats.add(c.id) : f.cats.delete(c.id);
        const sibs = childrenOf(c.parent_id).filter(id => catCount.get(id) > 0);
        if (sibs.every(id => f.cats.has(id))) f.cats.add(c.parent_id); else f.cats.delete(c.parent_id);
      }
      changed();
      drawList();
    }
    function drawList() {
      const q = search.value.trim().toLowerCase();
      const out = [];
      for (const t of tops) {
        const kids = cats.filter(c => c.parent_id === t.id && catCount.get(c.id) > 0);
        const hit = c => !q || c.name.toLowerCase().includes(q);
        const kidHits = kids.filter(hit);
        if (q && !hit(t) && !kidHits.length) continue;
        const open = q ? true : expanded.has(t.id);
        const someOn = !f.cats.has(t.id) && kids.some(k => f.cats.has(k.id));
        out.push(h('div', { class: 'dd-tree-top' },
          kids.length ? h('button', {
            type: 'button', class: 'dd-twisty', title: open ? '收合' : '展開',
            onclick: () => { expanded.has(t.id) ? expanded.delete(t.id) : expanded.add(t.id); drawList(); },
          }, open ? '▾' : '▸') : h('span', { class: 'dd-twisty' }),
          check(f.cats.has(t.id), h('span', {}, h('strong', {}, t.name), h('span', { class: 'muted' }, ` ${catCount.get(t.id)}`),
            someOn ? h('span', { class: 'muted small' }, '（部分）') : null), on => toggleCat(t, on))));
        if (open) (q && !hit(t) ? kidHits : kids).forEach(c => out.push(h('div', { class: 'dd-tree-child' },
          check(f.cats.has(c.id), h('span', {}, c.name, h('span', { class: 'muted' }, ` ${catCount.get(c.id)}`)), on => toggleCat(c, on)))));
      }
      list.replaceChildren(...(out.length ? out : [h('div', { class: 'muted small' }, '找不到')]));
    }
    drawList();
    return [search, list, ddFoot(() => { f.cats.clear(); changed(); drawList(); })];
  }
  const ddFoot = clear => h('div', { class: 'dd-foot' },
    h('button', { type: 'button', class: 'small ghost', onclick: clear }, '清除'),
    h('span', { class: 'spacer' }),
    h('button', { type: 'button', class: 'small primary', onclick: closeDD }, '完成'));

  function lightPanel() {
    return [h('div', { class: 'dd-list' }, ...['red', 'yellow', 'green'].map(l =>
      check(f.lights.has(l), h('span', { class: 'row', style: { gap: '6px' } }, lightDot(l), LIGHT_NAMES[l]),
        on => { on ? f.lights.add(l) : f.lights.delete(l); changed(); }))),
    h('div', { class: 'muted small', style: { marginTop: '6px' } }, '預設不含綠燈（已經會了的字）')];
  }

  function datePanel(key, presets) {
    const box = h('div', {});
    const draw = () => {
      const d = f[key];
      box.replaceChildren(h('div', { class: 'dd-list' }, ...presets.map(([v, t]) => h('label', { class: 'dd-check' },
        h('input', { type: 'radio', name: 'dd-' + key, checked: d.p === v, onchange: () => { d.p = v; changed(); draw(); } }), t))),
      d.p === 'custom' ? h('div', { class: 'row dd-dates' },
        h('input', { type: 'date', value: d.from, onchange: e => { d.from = e.target.value; changed(); } }), '～',
        h('input', { type: 'date', value: d.to, onchange: e => { d.to = e.target.value; changed(); } })) : null);
    };
    draw();
    return [box, h('div', { class: 'muted small', style: { marginTop: '6px' } }, `今天是 ${today}（照換日時間算）`)];
  }

  function sourcePanel() {
    const list = h('div', { class: 'dd-list dd-scroll' });
    const search = h('input', { type: 'search', placeholder: '搜尋文章或出處…', oninput: () => drawList() });
    function drawList() {
      const q = search.value.trim().toLowerCase();
      const vals = sourceValues.filter(s => !q || s.toLowerCase().includes(q));
      list.replaceChildren(...(vals.length ? vals.map(s => check(f.sources.has(s),
        h('span', { class: 'dd-src' }, h('span', {}, s), h('span', { class: 'muted' }, ` ${sourceCount.get(s)}`)),
        on => { on ? f.sources.add(s) : f.sources.delete(s); changed(); }, { title: s }))
        : [h('div', { class: 'muted small' }, sourceValues.length ? '找不到' : '還沒有從文章加入的字')]));
    }
    drawList();
    return [search, list, ddFoot(() => { f.sources.clear(); changed(); drawList(); })];
  }

  function morePanel() {
    const num = (key, attrs) => h('input', { type: 'number', value: f[key] || '', min: 0, placeholder: '0', ...attrs, oninput: e => { f[key] = Number(e.target.value) || 0; changed(); } });
    const posBox = h('div', { class: 'chips' }, ...posValues.map(v => {
      const c = h('span', { class: 'chip toggle' + (f.pos.has(v) ? ' on' : ''), onclick: () => { f.pos.has(v) ? f.pos.delete(v) : f.pos.add(v); c.classList.toggle('on', f.pos.has(v)); changed(); } }, v);
      return c;
    }));
    return [
      h('div', { class: 'dd-field' }, h('span', {}, '遺忘次數 ≥'), num('forget', { style: { width: '90px' } })),
      h('div', { class: 'dd-field' }, h('span', {}, '答錯率 ≥（%）'), num('rate', { max: 100, step: 10, style: { width: '90px' } })),
      h('div', { class: 'dd-field col' }, h('span', {}, '詞性'), posValues.length ? posBox : h('span', { class: 'muted small' }, '（沒有資料）')),
      check(f.ctxOnly, '只看有原文句子的字', on => { f.ctxOnly = on; changed(); }),
      ddFoot(() => { f.forget = 0; f.rate = 0; f.pos.clear(); f.ctxOnly = false; changed(); openDD && openDD.fill(); }),
    ];
  }

  const filterBar = h('div', { class: 'dd-bar' },
    dropdown('分類', () => (f.cats.size ? listText(catNames(), '類') : '全部'), () => f.cats.size > 0, catPanel),
    dropdown('燈號', () => (f.lights.size === 3 ? '全部' : f.lights.size ? [...f.lights].map(l => LIGHT_NAMES[l].replace('燈', '')).join('、') : '都沒選'),
      () => f.lights.size !== 3, lightPanel),
    dropdown('加入日期', () => dateText(f.added, ADDED_PRESETS), () => !!f.added.p, () => datePanel('added', ADDED_PRESETS)),
    dropdown('下次複習', () => dateText(f.due, DUE_PRESETS), () => !!f.due.p, () => datePanel('due', DUE_PRESETS)),
    dropdown('出處文章', () => (f.sources.size ? listText([...f.sources], '篇') : '全部'), () => f.sources.size > 0, sourcePanel),
    dropdown('更多條件', () => (moreCount() ? `${moreCount()} 個` : '無'), () => moreCount() > 0, morePanel),
  );

  // ---------- 已選的條件（每個都可以單獨拿掉）----------
  const activeBox = h('div', { class: 'active-filters' });
  function drawActive() {
    const tags = [];
    const tag = (label, clear) => tags.push(h('span', { class: 'chip static af' }, label,
      h('button', { class: 'link chip-x', title: '拿掉這個條件', onclick: () => { clear(); changed(); } }, '✕')));
    catNames().forEach(n => tag(n, () => {
      const c = cats.find(x => catLabel(x.id) === n);
      if (c) [c.id, ...(c.depth ? [] : childrenOf(c.id))].forEach(id => f.cats.delete(id));
      if (c && c.depth) f.cats.delete(c.parent_id);
    }));
    if (f.lights.size !== 3) tag(h('span', { class: 'row', style: { gap: '4px' } }, ...[...f.lights].map(l => lightDot(l)), f.lights.size ? [...f.lights].map(l => LIGHT_NAMES[l]).join('、') : '燈號都沒選'),
      () => { f.lights = new Set(['red', 'yellow', 'green']); });
    if (f.added.p) tag('加入：' + dateText(f.added, ADDED_PRESETS), () => { f.added = { p: '', from: '', to: '' }; });
    if (f.due.p) tag('下次複習：' + dateText(f.due, DUE_PRESETS), () => { f.due = { p: '', from: '', to: '' }; });
    f.sources.forEach(s => tag('📄 ' + short(s, 24), () => f.sources.delete(s)));
    if (f.forget) tag(`遺忘 ≥ ${f.forget}`, () => { f.forget = 0; });
    if (f.rate) tag(`答錯率 ≥ ${f.rate}%`, () => { f.rate = 0; });
    if (f.pos.size) tag('詞性：' + [...f.pos].join('、'), () => f.pos.clear());
    if (f.ctxOnly) tag('有原文句子', () => { f.ctxOnly = false; });
    activeBox.replaceChildren(
      h('span', { class: 'muted small' }, '已選：'),
      ...(tags.length ? tags : [h('span', { class: 'muted small' }, '沒有限制（全部的字）')]),
      tags.length ? h('button', { class: 'small ghost', title: '回到預設（紅燈、黃燈，其他不限制）', onclick: () => { f = emptyFilter(); changed(); } }, '清除全部') : null);
  }

  // ---------- 常用組合 ----------
  const SAVED_SHOW = 6;
  const savedBox = h('div', { class: 'saved-row' });
  function applySaved(s) { f = deserialize(s.data); activeSaved = s.id; closeDD(); refreshAll(); }
  async function deleteSaved(s) {
    if (!confirm(`刪除常用組合「${s.name}」？（只刪除組合，不會刪到單字）`)) return;
    await api('/filters/' + s.id, { method: 'DELETE' });
    saved = await api('/filters');
    if (activeSaved === s.id) activeSaved = null;
    closeDD();
    drawSaved();
  }
  const savedChip = s => h('span', { class: 'chip toggle' + (s.id === activeSaved ? ' on' : ''), title: '套用這個組合' },
    h('span', { onclick: () => applySaved(s) }, s.name),
    h('button', { class: 'link chip-x', title: '刪除這個組合', onclick: e => { e.stopPropagation(); deleteSaved(s); } }, '✕'));
  let moreSavedDD = null;
  function drawSaved() {
    const shown = saved.slice(0, SAVED_SHOW);
    const rest = saved.slice(SAVED_SHOW);
    if (rest.length) {
      moreSavedDD = { btn: h('button', { type: 'button', class: 'small ghost' }, `更多 ${rest.length} 個 ▾`), panel: h('div', { class: 'dd-panel hidden' }) };
      moreSavedDD.wrap = h('div', { class: 'dd' }, moreSavedDD.btn, moreSavedDD.panel);
      moreSavedDD.fill = () => moreSavedDD.panel.replaceChildren(h('div', { class: 'dd-list dd-scroll' }, ...rest.map(s => h('div', { class: 'dd-saved' + (s.id === activeSaved ? ' on' : '') },
        h('a', { href: '#', onclick: e => { e.preventDefault(); applySaved(s); } }, s.name),
        h('button', { class: 'link chip-x', title: '刪除這個組合', onclick: () => deleteSaved(s) }, '✕')))));
      moreSavedDD.btn.onclick = () => {
        if (openDD === moreSavedDD) { closeDD(); return; }
        closeDD(); moreSavedDD.fill(); moreSavedDD.panel.classList.remove('hidden'); openDD = moreSavedDD;
      };
    }
    savedBox.replaceChildren(...[
      h('span', { class: 'muted small' }, '常用組合'),
      ...shown.map(savedChip),
      rest.length ? moreSavedDD.wrap : null,
      saved.length ? null : h('span', { class: 'muted small' }, '還沒有。選好條件後可以存起來，下次一鍵套用。'),
      h('span', { class: 'spacer' }),
      h('button', {
        class: 'small', onclick: async () => {
          const name = prompt('幫這個組合取個名字', autoName());
          if (!name || !name.trim()) return;
          try {
            const { id } = await api('/filters', { method: 'POST', body: { name: name.trim(), data: serialize(f) } });
            saved = await api('/filters');
            activeSaved = id;
            drawSaved();
            toast('已存成常用組合');
          } catch (e) { toast(e.message, 'error'); }
        },
      }, '＋ 存成常用組合'),
    ].filter(Boolean));
  }

  // ---------- 右邊：結果、測驗方式、開始 ----------
  const countEl = h('div', { class: 'free-count' });
  const previewEl = h('div', { class: 'free-preview' });
  const startBtn = h('button', { class: 'primary big free-start' }, '開始');
  let showAll = false;
  let selected = [];
  function update() {
    selected = rows.filter(matches);
    countEl.replaceChildren(h('span', { class: 'num' }, selected.length), ' 個字符合');
    startBtn.disabled = !selected.length;
    startBtn.textContent = selected.length ? `開始（${selected.length} 個）` : '沒有符合的字';
    const list = showAll ? selected.slice(0, 300) : selected.slice(0, PREVIEW);
    previewEl.replaceChildren(
      ...list.map(r => h('span', { class: 'pv' }, lightDot(r.light), r.word)),
      selected.length > PREVIEW ? h('button', { class: 'link small', onclick: () => { showAll = !showAll; update(); } },
        showAll ? '收起' : `看全部 ${selected.length} 個`) : null);
  }

  function changed() {
    activeSaved = null;
    drawSaved();
    refreshAll(false);
  }
  function refreshAll(redrawSaved = true) {
    dropdowns.forEach(d => d.draw());
    drawActive();
    if (redrawSaved) drawSaved();
    update();
  }

  const picker = modePicker({ compact: true, withMatch: true });
  startBtn.onclick = async () => {
    const ids = selected.map(r => r.id);
    if (picker.mode === 'en2zh' || picker.mode === 'mixed') api('/warmup', { method: 'POST' }).catch(() => {});
    const all = await api('/review/free', { method: 'POST', body: { ids, shuffle: picker.shuffle, sources: [...f.sources] } });
    const queue = all.questions;
    const limit = all.limit;
    detach();
    if (picker.mode === 'match') { cleanup = runMatch(el, queue); return; }  // 配對：不寫進複習紀錄
    cleanup = runSession(el, {
      session: 'free',
      mode: picker.mode,
      loadRound: async () => {
        const chunk = queue.splice(0, limit);
        return { questions: chunk, hasMore: queue.length > 0, moreCount: Math.min(queue.length, limit) };
      },
    });
  };

  el.append(
    h('h1', {}, '自由複習'),
    h('div', { class: 'free-layout' },
      h('div', { class: 'free-main' },
        h('div', { class: 'panel' },
          savedBox,
          filterBar,
          activeBox,
          h('div', { class: 'muted small', style: { marginTop: '10px' } }, '沒選的條件就是不限制。答對不計入累計，答錯一樣會扣（一天最多一次）。'))),
      h('aside', { class: 'panel free-side' },
        countEl, previewEl,
        h('div', { class: 'free-sec' }, '測驗方式'),
        picker.el,
        startBtn)),
  );
  refreshAll();

  function detach() {
    document.removeEventListener('mousedown', onDocClick);
    document.removeEventListener('keydown', onDocKey);
  }
  return () => { detach(); if (cleanup) cleanup(); };
}
