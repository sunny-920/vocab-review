// 新增單字 + 待確認清單
import { api, h, toast, LIGHT_NAMES } from '../util.js';
import { createEditor } from '../editor.js';
import { phoneticLine } from '../detail.js';
import { parsePaste } from '../parse.js';

const EXAMPLE = [
  ['word', 'retrieve', '[rɪˈtriv]', '擷取；取回'],
  ['sentence', 'A database is an organized collection of information that a computer can store and retrieve.'],
  ['word', 'servers', '', '伺服器'],
  ['word', 'relational database', '', '關聯式資料庫'],
];

function formatGuide() {
  return h('details', { class: 'guide' },
    h('summary', {}, '格式說明'),
    h('div', { class: 'guide-body' },
      h('div', { class: 'guide-example' }, ...EXAMPLE.map(([type, en, kk, zh]) => type === 'word'
        ? h('div', { class: 'g-row' },
          h('span', { class: 'g-tag' }, '單字'),
          h('span', { class: 'g-en' }, en),
          kk ? h('span', { class: 'g-kk' }, kk) : null,
          h('span', { class: 'g-zh' }, zh))
        : h('div', { class: 'g-row' },
          h('span', { class: 'g-tag sent' }, '句子'),
          h('span', { class: 'g-sent' }, en)))),
      h('ul', {},
        h('li', {}, '一行一個單字。KK 音標和中文可以省略，用 Tab 或空格隔開都可以。'),
        h('li', {}, '句子放在單字的下一行，會當作那個字的原文句子；可以放好幾句。'),
        h('li', {}, '片語也可以，例如 relational database。'),
      ),
    ),
  );
}

export async function render(el) {
  let cats = await api('/categories');

  // ================= 輸入區 =================
  const source = h('input', { placeholder: '文章名稱或網址（選填，這一批單字共用）' });
  const box = h('textarea', { class: 'paste-box', rows: 9, spellcheck: 'false', placeholder: '在這裡貼上單字，一行一個；句子放在單字的下一行' });
  api('/warmup', { method: 'POST' }).catch(() => {}); // 先在背景載入模型
  const preview = h('div', { class: 'preview' });
  const resultLine = h('div', { class: 'small', style: { marginTop: '10px' } });
  const checks = new Map(); // 小寫單字 -> /check 結果
  let parsed = { items: [], orphans: [] };
  let timer = null;

  // 在輸入框裡按 Tab 是插入定位字元，不是跳到下一個欄位
  box.addEventListener('keydown', e => {
    if (e.key === 'Tab' && !e.shiftKey && !e.ctrlKey) {
      e.preventDefault();
      const { selectionStart: s, selectionEnd: t } = box;
      box.setRangeText('\t', s, t, 'end');
      box.dispatchEvent(new Event('input'));
    }
  });
  box.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(update, 350);
  });

  function update() {
    parsed = parsePaste(box.value);
    drawPreview();
    fetchChecks();
  }

  async function fetchChecks() {
    const todo = parsed.items.filter(it => !checks.has(it.word.toLowerCase()));
    if (!todo.length) return;
    await Promise.all(todo.map(async it => {
      const key = it.word.toLowerCase();
      checks.set(key, null);
      try { checks.set(key, await api('/check?word=' + encodeURIComponent(it.word))); }
      catch { checks.delete(key); }
    }));
    drawPreview();
  }

  function useLemma(it, lemma) {
    const lines = box.value.split('\n');
    lines[it.line] = lines[it.line].replace(it.word, lemma);
    box.value = lines.join('\n');
    update();
  }

  function hints(it) {
    const c = checks.get(it.word.toLowerCase());
    const out = [];
    if (c && c.existing && c.existing.status === 'active') {
      out.push(h('div', { class: 'warn' },
        `⚠ 學過了（${LIGHT_NAMES[c.existing.light]}${c.existing.forget_count ? `，忘記過 ${c.existing.forget_count} 次` : ''}），送出後會標紅`));
    } else if (c && c.existing) {
      out.push(h('div', { class: 'muted' }, '已經在待確認清單'));
    }
    if (c && c.lemma) {
      out.push(h('div', { class: 'lemma' },
        `是「${c.lemma.lemma}」的${c.lemma.forms.join('、') || '變化形'}${c.lemma.existing ? `（你學過 ${c.lemma.lemma}）` : ''} `,
        h('button', { class: 'link', type: 'button', onclick: () => useLemma(it, c.lemma.lemma) }, `改用 ${c.lemma.lemma}`)));
    }
    if (c && !c.dict && !c.existing) out.push(h('div', { class: 'muted' }, '字典查不到，會完全由 AI 整理'));
    for (const w of it.warnings) out.push(h('div', { class: 'warn' }, w));
    return out;
  }

  function drawPreview() {
    const { items, orphans } = parsed;
    if (!items.length && !orphans.length) {
      preview.replaceChildren(h('div', { class: 'muted small' }, '輸入後，這裡會即時顯示分割結果，確認沒問題再送出。'));
      return;
    }
    const rows = items.map((it, i) => h('tr', {},
      h('td', { class: 'num muted' }, i + 1),
      h('td', {}, h('div', { class: 'w' }, it.word), h('div', { class: 'hint-cell' }, hints(it))),
      h('td', { class: 'kk-line' }, it.kk || h('span', { class: 'muted' }, '—')),
      h('td', {}, it.zh || h('span', { class: 'muted' }, '—')),
      h('td', { class: 'ctx' }, it.contexts.length
        ? it.contexts.map(c => h('div', {}, c))
        : h('span', { class: 'muted' }, '—')),
    ));
    preview.replaceChildren(...[
      h('div', { class: 'small muted', style: { margin: '14px 0 6px' } }, `分割結果：${items.length} 個字`),
      items.length ? h('div', { class: 'table-wrap' }, h('table', { class: 'data static' },
        h('thead', {}, h('tr', {}, ...['', '英文', 'KK', '中文', '原文句子'].map(t => h('th', {}, t)))),
        h('tbody', {}, rows))) : null,
      orphans.length ? h('div', { class: 'warn small', style: { marginTop: '6px' } },
        `第 ${orphans.join('、')} 行找不到對應的單字，送出時會略過。`) : null,
    ].filter(Boolean));
  }

  async function submit() {
    clearTimeout(timer);
    parsed = parsePaste(box.value);
    drawPreview();
    if (!parsed.items.length) { toast('請先輸入英文單字', 'error'); return; }
    submitBtn.disabled = true;
    try {
      const items = parsed.items.map(it => ({ word: it.word, kk: it.kk, zh: it.zh, contexts: it.contexts }));
      const { results } = await api('/words/batch', { method: 'POST', body: { source_title: source.value.trim(), items } });
      const queued = results.filter(r => r.action === 'queued');
      const re = results.filter(r => r.action === 'reinput');
      const pend = results.filter(r => r.action === 'pending');
      const parts = [];
      if (queued.length) parts.push(`${queued.length} 個字送去 AI 整理`);
      if (re.length) parts.push(`學過又忘記，已標紅：${re.map(r => `${r.word}（忘記過 ${r.forget_count} 次）`).join('、')}`);
      if (pend.length) parts.push(`已經在待確認清單：${pend.map(r => r.word).join('、')}`);
      resultLine.replaceChildren(h('span', { class: re.length ? 'warn' : '' }, '已送出：' + parts.join('；')));
      toast('已送出');
      box.value = '';
      checks.clear();
      update();
      box.focus();
      clearTimeout(poll);
      poll = setTimeout(tick, 300);
    } catch (e) {
      toast(e.message, 'error');
    } finally {
      submitBtn.disabled = false;
    }
  }

  const submitBtn = h('button', { class: 'primary', onclick: submit }, '送出');
  const form = h('div', { class: 'panel' },
    h('div', { class: 'row', style: { marginBottom: '12px' } },
      h('h1', { style: { margin: 0 } }, '新增單字'),
      h('span', { class: 'spacer' }),
      h('span', { class: 'muted small' }, h('kbd', {}, 'Ctrl'), ' + ', h('kbd', {}, 'Enter'), ' 送出'),
    ),
    h('label', { class: 'field', style: { marginBottom: '12px' } }, h('span', {}, '出處'), source),
    formatGuide(),
    box,
    preview,
    h('div', { class: 'row', style: { marginTop: '12px' } }, h('span', { class: 'spacer' }), submitBtn),
    resultLine,
  );
  form.addEventListener('keydown', e => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); submit(); }
  });
  drawPreview();

  // ================= 待確認清單 =================
  const draftsTitle = h('h2', { style: { margin: 0 } }, '待確認');
  const draftsHint = h('div', { class: 'muted small' }, 'AI 整理好的單字會出現在這裡。檢查、修改後按「確認存入」。');
  const draftsBox = h('div', { style: { marginTop: '12px' } });
  const emptyMsg = h('div', { class: 'empty' }, '目前沒有待確認的單字。');
  const shown = new Map(); // id -> { status, el, queueEl }

  const dictPreview = d => d.dict
    ? h('div', { class: 'dict-preview' }, '字典：\n' + d.dict.translation.join('\n'))
    : h('div', { class: 'dict-preview' }, '字典查不到這個字。');

  const queueText = d => d.queue_position === 0 ? 'AI 整理中…' : d.queue_position ? `排隊中（前面還有 ${d.queue_position} 個）` : '等待 AI…';

  async function act(fn) {
    try { await fn(); } catch (e) { toast(e.message, 'error'); }
    loadDrafts();
  }

  const removeBtn = d => h('button', {
    class: 'danger', onclick: () => {
      if (confirm(`刪除「${d.word}」？`)) act(() => api('/words/' + d.id, { method: 'DELETE' }));
    },
  }, '刪除');

  function renderDraft(d) {
    const head = h('div', { class: 'draft-head' }, h('span', { class: 'w' }, d.word), phoneticLine(d));
    if (d.status === 'generating') {
      const q = h('span', { class: 'muted small' }, queueText(d));
      head.append(h('span', { class: 'spinner' }), q, h('span', { class: 'spacer' }), removeBtn(d));
      return { el: h('div', { class: 'draft' }, head, dictPreview(d)), queueEl: q };
    }
    if (d.status === 'error') {
      head.append(h('span', { class: 'badge red' }, '失敗'), h('span', { class: 'spacer' }),
        h('button', { onclick: () => act(() => api(`/words/${d.id}/regenerate`, { method: 'POST' })) }, '重試'),
        d.dict ? h('button', { onclick: () => act(() => api(`/words/${d.id}/dict-fill`, { method: 'POST' })) }, '只用字典資料') : null,
        removeBtn(d));
      return { el: h('div', { class: 'draft' }, head, h('div', { class: 'error-box' }, d.error || '發生錯誤'), dictPreview(d)) };
    }
    // draft：可編輯
    const ed = createEditor(d, cats);
    const confirmBtn = h('button', {
      class: 'primary', onclick: async () => {
        confirmBtn.disabled = true;
        try {
          const saved = await api(`/words/${d.id}/confirm`, { method: 'POST', body: ed.getValue() });
          toast(`${saved.word} 已存入`);
          if (saved.categories.primary && !cats.some(c => c.path === saved.categories.primary)) cats = await api('/categories');
          loadDrafts();
        } catch (e) { toast(e.message, 'error'); confirmBtn.disabled = false; }
      },
    }, '確認存入');
    head.append(h('span', { class: 'badge accent' }, 'AI 整理好了，請檢查'), h('span', { class: 'spacer' }),
      h('button', {
        onclick: () => {
          if (confirm(`重新生成「${d.word}」？你在這張卡上的修改會被覆蓋。`)) act(() => api(`/words/${d.id}/regenerate`, { method: 'POST' }));
        },
      }, '重新生成'),
      removeBtn(d), confirmBtn);
    return { el: h('div', { class: 'draft' }, head, ed.el), ed };
  }

  async function saveAll() {
    const ready = [...shown.entries()].filter(([, s]) => s.status === 'draft' && s.ed);
    if (!ready.length) return;
    saveAllBtn.disabled = true;
    let ok = 0;
    const failed = [];
    for (const [id, s] of ready) {
      try {
        const saved = await api(`/words/${id}/confirm`, { method: 'POST', body: s.ed.getValue() });
        if (saved.categories.primary && !cats.some(c => c.path === saved.categories.primary)) cats = await api('/categories');
        ok++;
      } catch (e) {
        failed.push(`${s.ed.getValue().word}：${e.message}`);
      }
    }
    toast(`已存入 ${ok} 個字` + (failed.length ? `，${failed.length} 個沒存：${failed.join('；')}` : ''), failed.length ? 'error' : '');
    await loadDrafts();
  }

  async function loadDrafts() {
    let list;
    try { list = await api('/drafts'); } catch { return; }
    const ids = new Set(list.map(d => d.id));
    for (const [id, s] of shown) {
      if (!ids.has(id)) { s.el.remove(); shown.delete(id); }
    }
    for (const d of list) {
      const cur = shown.get(d.id);
      if (cur && cur.status === d.status) {
        if (cur.queueEl) cur.queueEl.textContent = queueText(d);
        if (cur.ed && cur.mem !== d.mem_state) { cur.mem = d.mem_state; cur.ed.setMemory(d); } // 記憶法做好了
        continue; // 狀態沒變就不重畫，避免洗掉正在編輯的內容
      }
      const r = renderDraft(d);
      if (cur) cur.el.replaceWith(r.el); else draftsBox.append(r.el);
      shown.set(d.id, { status: d.status, mem: d.mem_state, ...r });
    }
    draftsTitle.textContent = list.length ? `待確認（${list.length}）` : '待確認';
    emptyMsg.classList.toggle('hidden', list.length > 0);
    busy = list.some(d => d.status === 'generating' || d.mem_state === 'pending');
    const nReady = list.filter(d => d.status === 'draft').length;
    saveAllBtn.textContent = nReady ? `一鍵全部存入（${nReady}）` : '一鍵全部存入';
    saveAllBtn.disabled = !nReady;
  }
  let busy = false;
  const saveAllBtn = h('button', { class: 'primary', disabled: true, onclick: saveAll, title: '把所有 AI 整理好的卡片，照目前畫面上的內容全部存入' }, '一鍵全部存入');

  el.append(
    form,
    h('div', { class: 'panel' },
      h('div', { class: 'row' }, draftsTitle, h('span', { class: 'spacer' }), saveAllBtn),
      draftsHint,
      draftsBox,
      emptyMsg,
    ),
  );
  box.focus();
  await loadDrafts();
  // AI 整理中每 1 秒檢查一次，沒事時每 5 秒
  let poll = null;
  let alive = true;
  const tick = async () => {
    if (!document.hidden) await loadDrafts();
    if (alive) poll = setTimeout(tick, busy ? 1000 : 5000);
  };
  poll = setTimeout(tick, 1000);
  return () => { alive = false; clearTimeout(poll); clearTimeout(timer); };
}
