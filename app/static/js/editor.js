// 單字編輯器（確認 AI 結果、修改單字共用）
import { api, h, toast } from './util.js';

// 記憶法候選的種類（和後端 words.MEMORY_LABELS 一致）
const MEM_KINDS = [['family', '家族'], ['link', '聯想']];

const POS_LIST = ['n.', 'v.', 'adj.', 'adv.', 'prep.', 'conj.', 'pron.', 'phr.'];

export function createEditor(word, categories) {
  const paths = categories.map(c => c.path);
  const state = {
    word: word.word,
    kk_user: word.kk_user || '',
    meanings: word.meanings.map(m => ({ ...m })),
    examples: word.examples.map(e => ({ ...e })),
    related: (word.related || []).map(r => ({ word: r.word, zh: r.zh || '', pos: r.pos || '', rel: r.rel || '相關', note: r.note || '' })),
    primary: word.categories.primary || '',
    others: [...word.categories.others],
    roots: word.roots || '',
    mnemonic: word.mnemonic || '',
    supplement: word.supplement || '',
    my_note: word.my_note || '',
  };
  const extraPaths = new Set(); // AI 建議、使用者按「採用」的新分類，存檔時才建立

  const root = h('div', { class: 'editor' });

  const bind = (key, el) => {
    el.value = state[key];
    el.addEventListener('input', () => { state[key] = el.value; });
    return el;
  };
  const del = onclick => h('button', { class: 'ghost icon', type: 'button', title: '刪除', onclick }, '✕');

  // --- 英文、音標 ---
  const top = h('div', { class: 'two' },
    h('label', { class: 'field' }, h('span', {}, '英文'), bind('word', h('input', {}))),
    h('label', { class: 'field' },
      h('span', {}, 'KK 音標（你自己的，選填）' + (word.kk_ai ? `　AI：${word.kk_ai}` : '')),
      bind('kk_user', h('input', { placeholder: word.kk_ai ? `留空就顯示 AI 的：${word.kk_ai}` : '' }))),
  );

  // --- 中文意思 ---
  const meaningsBox = h('div', { class: 'list-rows' });
  const drawMeanings = () => {
    meaningsBox.replaceChildren(...state.meanings.map((m, i) => {
      const pos = h('input', { list: 'pos-list', value: m.pos, placeholder: '詞性', oninput: e => { m.pos = e.target.value; } });
      const zh = h('input', { value: m.zh, placeholder: '中文，例如：檢查、審查', oninput: e => { m.zh = e.target.value; } });
      const domain = h('input', { class: 'domain', value: m.domain, placeholder: '領域（選填）', oninput: e => { m.domain = e.target.value; } });
      const star = h('label', { class: 'star', title: '主要意思：複習時答到這個就一定對' },
        h('input', { type: 'checkbox', checked: m.is_primary, onchange: e => { m.is_primary = e.target.checked; } }), '★主要');
      return h('div', { class: 'meaning-row' }, pos, zh, domain, star,
        del(() => { state.meanings.splice(i, 1); drawMeanings(); }));
    }));
  };
  drawMeanings();
  const meanings = h('div', {},
    h('div', { class: 'sec-title' }, '中文意思（答中任何一個都算對）'),
    meaningsBox,
    h('button', { class: 'link small', type: 'button', style: { marginTop: '6px' },
      onclick: () => { state.meanings.push({ pos: '', zh: '', domain: '', is_primary: false, source: 'user' }); drawMeanings(); } }, '＋ 新增意思'),
    h('datalist', { id: 'pos-list' }, ...POS_LIST.map(p => h('option', { value: p }))),
  );

  // --- 分類 ---
  const catBox = h('div', {});
  const drawCats = () => {
    const allPaths = [...paths, ...extraPaths];
    const options = (selected, placeholder) => [
      h('option', { value: '' }, placeholder),
      ...allPaths.map(p => {
        const depth = p.includes('/') ? 1 : 0;
        const o = h('option', { value: p }, (depth ? '　' : '') + (depth ? p.split('/')[1] : p));
        if (p === selected) o.selected = true;
        return o;
      }),
    ];
    const primarySel = h('select', { onchange: e => { state.primary = e.target.value; state.others = state.others.filter(o => o !== state.primary); drawCats(); } },
      ...options(state.primary, '— 選擇主分類 —'));
    const addOther = h('select', { onchange: e => { const v = e.target.value; if (v && v !== state.primary && !state.others.includes(v)) state.others.push(v); drawCats(); } },
      ...options('', '＋ 加其他分類'));
    const chips = state.others.map((o, i) => h('span', { class: 'badge' }, o, ' ',
      h('button', { class: 'link', type: 'button', onclick: () => { state.others.splice(i, 1); drawCats(); } }, '✕')));

    const sug = word.ai_suggest_category;
    const suggestion = sug && !allPaths.includes(sug) ? h('div', { class: 'suggest' },
      `AI 建議新分類：${sug}`,
      h('button', { class: 'small', type: 'button', onclick: () => { extraPaths.add(sug); state.primary = sug; drawCats(); } }, '採用（存檔時建立）'),
    ) : null;

    catBox.replaceChildren(...[
      h('div', { class: 'sec-title' }, '分類'),
      h('div', { class: 'two' }, primarySel, addOther),
      chips.length ? h('div', { class: 'chips', style: { marginTop: '6px' } }, chips) : null,
      suggestion ? h('div', { style: { marginTop: '6px' } }, suggestion) : null,
    ].filter(Boolean));
  };
  drawCats();

  // --- 字根、記憶法 ---
  const rootsEl = bind('roots', h('textarea', { rows: 2 }));
  const mnemonicEl = bind('mnemonic', h('textarea', { rows: 3 }));
  const notes = h('div', { class: 'two' },
    h('label', { class: 'field' }, h('span', {}, '字根字首（選填）'), rootsEl),
    h('label', { class: 'field' }, h('span', {}, '記憶法（選填）'), mnemonicEl),
  );
  let alts = word.mnemonic_alts || null;
  let memState = word.mem_state || '';
  let memBusy = false;
  const memBox = h('div', { class: 'mem-box' });
  const setField = (key, el, v) => { state[key] = v; el.value = v; };
  const lineOf = (label, text) => `${label}：${text}`;
  const mnLines = () => state.mnemonic.split('\n').map(l => l.trim()).filter(Boolean);
  const drawMem = () => {
    const rows = [];
    if (memBusy || memState === 'pending') {
      rows.push(h('div', { class: 'muted small row' }, h('span', { class: 'spinner' }), 'AI 正在想記憶法…（約 10～40 秒，可以先改其他欄位）'));
    } else if (memState === 'error') {
      rows.push(h('div', { class: 'warn small' }, '記憶法產生失敗，可以按「重新產生記憶法」再試一次。'));
    }
    if (alts && !memBusy) {
      const cands = MEM_KINDS.filter(([k]) => alts[k]);
      if (alts.roots && alts.roots !== state.roots) {
        rows.push(h('div', { class: 'mem-cand' },
          h('span', { class: 'mn-tag' }, '拆解'), h('span', { class: 'grow' }, alts.roots),
          h('button', { class: 'small', type: 'button', onclick: () => { setField('roots', rootsEl, alts.roots); drawMem(); } }, '放進字根欄')));
      }
      for (const [k, label] of cands) {
        const line = lineOf(label, alts[k]);
        const on = mnLines().includes(line);
        rows.push(h('label', { class: 'mem-cand' },
          h('input', {
            type: 'checkbox', checked: on, onchange: e => {
              // 候選照「家族、聯想」的順序排在前面，你自己寫的行放後面
              const all = cands.map(([ck, cl]) => lineOf(cl, alts[ck]));
              const cur = mnLines();
              const keep = all.filter(l => (l === line ? e.target.checked : cur.includes(l)));
              setField('mnemonic', mnemonicEl, [...keep, ...cur.filter(l => !all.includes(l))].join('\n'));
            },
          }),
          h('span', { class: 'mn-tag' }, label), h('span', { class: 'grow' }, alts[k])));
      }
      if (!cands.length && !alts.roots) rows.push(h('div', { class: 'muted small' }, 'AI 這次想不到好的記憶法。'));
      else rows.push(h('div', { class: 'muted small' }, '勾選的會放進記憶法欄位。AI 寫不出好的方法時會留空。'));
    }
    rows.push(h('div', {}, h('button', {
      class: 'small', type: 'button', disabled: memBusy || memState === 'pending' || !word.id, onclick: regen,
    }, '✨ 重新產生記憶法')));
    memBox.replaceChildren(...rows);
  };
  const applyAlts = (a, fillEmpty) => {
    alts = a; memState = 'done';
    if (fillEmpty && !state.roots.trim() && a.roots) setField('roots', rootsEl, a.roots);
    if (fillEmpty && !state.mnemonic.trim()) {
      setField('mnemonic', mnemonicEl, MEM_KINDS.filter(([k]) => a[k]).map(([k, label]) => lineOf(label, a[k])).join('\n'));
    }
    drawMem();
  };
  async function regen() {
    memBusy = true; drawMem();
    try { applyAlts(await api(`/words/${word.id}/memory`, { method: 'POST' }), false); }
    catch (e) { toast(e.message, 'error'); }
    finally { memBusy = false; drawMem(); }
  }
  // 勾選框要跟著手動修改的記憶法欄位更新
  mnemonicEl.addEventListener('input', () => { clearTimeout(mnemonicEl._t); mnemonicEl._t = setTimeout(drawMem, 400); });
  drawMem();

  // --- 例句 ---
  const exBox = h('div', { class: 'list-rows' });
  let examplesTouched = false; // 你改過例句，背景檢查完的例句就不蓋過去
  const drawExamples = () => {
    exBox.replaceChildren(...state.examples.map((e, i) => h('div', { class: 'example-row' },
      h('textarea', { rows: 2, value: e.en, placeholder: '英文例句', oninput: ev => { e.en = ev.target.value; examplesTouched = true; } }),
      h('textarea', { rows: 2, value: e.zh, placeholder: '中文翻譯', oninput: ev => { e.zh = ev.target.value; examplesTouched = true; } }),
      h('span', { class: 'badge', title: e.source_title || '' }, e.source === 'context' ? '原文' : 'AI'),
      del(() => { state.examples.splice(i, 1); examplesTouched = true; drawExamples(); }),
    )));
  };
  drawExamples();
  const examples = h('div', {},
    h('div', { class: 'sec-title' }, '例句'),
    exBox,
    h('button', { class: 'link small', type: 'button', style: { marginTop: '6px' },
      onclick: () => { state.examples.push({ en: '', zh: '', source: 'user', source_title: '' }); examplesTouched = true; drawExamples(); } }, '＋ 新增例句'),
  );

  // --- 相關字 ---
  // 英文、中文、詞性、關係、說明分開填；打完英文會查字典：查不到提醒拼字，中文、詞性空的就帶入
  const relBox = h('div', { class: 'list-rows' });
  const REL_OPTS = ['同家族', '近義', '反義', '易混淆', '相關'];
  const REL_POS = ['', 'n.', 'v.', 'adj.', 'adv.', 'phr.'];
  const relRow = (r, i) => {
    const warn = h('div', { class: 'rel-warn small' });
    const zh = h('input', { value: r.zh, placeholder: '中文', oninput: e => { r.zh = e.target.value; } });
    const pos = h('select', { title: '詞性', onchange: e => { r.pos = e.target.value; } },
      ...REL_POS.map(p => h('option', { value: p, selected: p === r.pos }, p || '詞性')));
    const rel = h('select', { title: '關係', onchange: e => { r.rel = e.target.value; } },
      ...REL_OPTS.map(x => h('option', { value: x, selected: x === r.rel }, x)));
    const check = async () => {
      const w = r.word.trim();
      if (!w) { warn.textContent = ''; return; }
      try {
        const d = await api('/dict/brief?word=' + encodeURIComponent(w));
        if (r.word.trim() !== w) return;
        warn.replaceChildren(...(d.found ? [] : [h('span', { class: 'warn' }, '⚠ 字典查不到，拼對了嗎？')]),
          ...(d.exists_id ? [h('span', { class: 'muted' }, '（單字庫裡有）')] : []));
        if (d.found && !r.zh.trim() && d.zh) { r.zh = d.zh; zh.value = d.zh; }
        if (d.found && !r.pos && d.pos) { r.pos = d.pos; pos.value = d.pos; }
      } catch { /* 查不到就算了 */ }
    };
    const en = h('input', { value: r.word, placeholder: '英文', oninput: e => { r.word = e.target.value; }, onchange: check });
    const row = h('div', { class: 'rel-edit' },
      h('div', { class: 'related-row rel-row' }, en, zh, pos, rel,
        h('input', { value: r.note, placeholder: '說明（選填）', oninput: e => { r.note = e.target.value; } }),
        del(() => { state.related.splice(i, 1); drawRelated(); })),
      warn);
    if (r.word.trim()) check();
    return row;
  };
  const drawRelated = () => relBox.replaceChildren(...state.related.map(relRow));
  drawRelated();
  const related = h('div', {},
    h('div', { class: 'sec-title' }, '相關字'),
    relBox,
    h('button', { class: 'link small', type: 'button', style: { marginTop: '6px' },
      onclick: () => { state.related.push({ word: '', zh: '', pos: '', rel: '相關', note: '' }); drawRelated(); relBox.lastChild.querySelector('input').focus(); } }, '＋ 新增相關字'),
  );

  const bottom = h('div', { class: 'two' },
    h('label', { class: 'field' }, h('span', {}, '補充（易混淆字、對比字，選填）'), bind('supplement', h('textarea', { rows: 2 }))),
    h('label', { class: 'field' }, h('span', {}, '我的筆記'), bind('my_note', h('textarea', { rows: 2 }))),
  );

  root.append(top, meanings, catBox, notes, memBox, examples, related, bottom);

  return {
    el: root,
    // 背景的記憶法做好時（新增單字頁），把候選放進來；欄位還是空的才自動填
    setMemory(w) {
      memState = w.mem_state || '';
      if (w.mnemonic_alts) applyAlts(w.mnemonic_alts, true); else drawMem();
      // 背景也檢查過例句（文法、用法）；你沒動過例句才換成檢查後的版本
      if (!examplesTouched && w.examples) {
        state.examples = w.examples.map(e => ({ ...e }));
        drawExamples();
      }
    },
    getValue() {
      return {
        word: state.word,
        kk_user: state.kk_user,
        meanings: state.meanings.filter(m => m.zh.trim()),
        examples: state.examples.filter(e => e.en.trim()).map(e => ({ en: e.en, zh: e.zh || '', source: e.source || 'user', source_title: e.source_title || '' })),
        related: state.related.filter(r => r.word.trim()),
        categories: { primary: state.primary || null, others: state.others },
        roots: state.roots,
        mnemonic: state.mnemonic,
        supplement: state.supplement,
        my_note: state.my_note,
      };
    },
  };
}
