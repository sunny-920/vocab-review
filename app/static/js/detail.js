// 卡片背面：單字的完整資料
import { api, h, lightDot, progressDots, speak, toast, LIGHT_NAMES } from './util.js';

export function highlight(sentence, word) {
  // 把例句中的單字（含變化形）標出來
  const stem = word.toLowerCase().replace(/(e|y|ies|es|s)$/, '');
  const re = new RegExp(`\\b(${stem.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}[a-z]*)`, 'gi');
  const parts = [];
  let last = 0;
  for (const m of sentence.matchAll(re)) {
    parts.push(sentence.slice(last, m.index), h('mark', {}, m[0]));
    last = m.index + m[0].length;
  }
  parts.push(sentence.slice(last));
  return parts;
}

// 一鍵複製單字
const COPY_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/></svg>';
export function copyButton(text) {
  return h('button', {
    class: 'speak', title: '複製單字', onclick: async e => {
      e.stopPropagation();
      try { await navigator.clipboard.writeText(text); }
      catch {
        const t = h('textarea', { value: text, style: { position: 'fixed', opacity: 0 } });
        document.body.append(t); t.select(); document.execCommand('copy'); t.remove();
      }
      toast(`已複製 ${text}`);
    },
  }, h('span', { html: COPY_ICON }));  // ⧉ 這個符號 Mac 的字型沒有，改用圖
}

// 記憶法：「家族：…」「字源：…」「聯想：…」每行前面加小標籤
export function mnemonicView(text) {
  return h('div', { class: 'mnemonic' }, ...text.split('\n').filter(l => l.trim()).map(line => {
    const m = line.match(/^(家族|字源|聯想)[：:]\s*(.*)$/);
    return h('div', {}, m ? [h('span', { class: 'mn-tag' }, m[1]), m[2]] : line);
  }));
}

export function phoneticLine(w) {
  const bits = [];
  if (w.kk_user) bits.push(h('span', { title: 'KK 音標（你填的）' }, `KK [${w.kk_user}]`));
  else if (w.kk_ai) bits.push(h('span', { title: 'AI 產生，可能有錯' }, `KK [${w.kk_ai}]`));
  if (w.dict && w.dict.phonetic) bits.push(h('span', { title: '字典音標（IPA）' }, `IPA /${w.dict.phonetic}/`));
  return bits.length ? h('span', { class: 'phon' }, bits.flatMap((b, i) => (i ? [' · ', b] : [b]))) : null;
}

// 手動改狀態：燈號（紅／黃／綠）＋複習進度（0 重新開始 … 3 已經會了＝綠燈）
// onStatus('light', 'red') 或 onStatus('count', 2)
export function statusControl(w, onStatus) {
  const cur = Math.min(w.stats.correct_count, 3);
  const light = w.stats.light;
  const labels = ['0 重新開始', '1', '2', '3 我已經會了'];
  const hint = cur >= 3 ? '已畢業，不會出現在每日複習（自由複習還是可以練）'
    : `下次複習：${w.stats.due_day || '-'}`;
  const click = (kind, v, same) => e => { e.stopPropagation(); if (!same) onStatus(kind, v); };
  return h('div', { class: 'progress-ctl' },
    h('div', { class: 'ctl-row' },
      h('span', { class: 'small muted ctl-label' }, '燈號'),
      h('div', { class: 'seg-group' }, ...['red', 'yellow', 'green'].map(l => h('button', {
        class: 'seg light-seg ' + l + (l === light ? ' on' : ''),
        title: { red: '標成不熟，明天就複習', yellow: '學習中', green: '已經會了，直接畢業' }[l],
        onclick: click('light', l, l === light),
      }, lightDot(l), { red: '紅', yellow: '黃', green: '綠' }[l])))),
    h('div', { class: 'ctl-row' },
      h('span', { class: 'small muted ctl-label' }, '複習進度（不同天答對）'),
      h('div', { class: 'seg-group' }, ...labels.map((label, n) => h('button', {
        class: 'seg' + (n === cur ? ' on' : ''),
        title: n === 3 ? '直接畢業（綠燈），不再出現在每日複習' : n === 0 ? '進度歸零，明天開始重新複習' : `設成 ${n}/3`,
        onclick: click('count', n, n === cur),
      }, label)))),
    h('span', { class: 'small muted' }, hint));
}

// 共用：呼叫 API 改狀態，回傳更新後的單字
export function applyStatus(id, kind, value) {
  return kind === 'light'
    ? api(`/words/${id}/light`, { method: 'POST', body: { light: value } })
    : api(`/words/${id}/progress`, { method: 'POST', body: { count: value } });
}

export function statusToast(w, kind, value) {
  if (kind === 'light') return `${w.word} 改成${{ red: '紅燈', yellow: '黃燈', green: '綠燈（畢業）' }[value]}`;
  return value >= 3 ? `${w.word} 已畢業，不會再出現在每日複習` : `${w.word} 的進度設成 ${value}/3`;
}

export function renderDetail(w, { onOpenWord, onStatus } = {}) {
  const s = w.stats || {};
  const sec = (label, ...body) => h('div', { class: 'sec' }, h('div', { class: 'sec-label' }, label), ...body);

  const head = h('div', { class: 'head' },
    h('span', { class: 'w' }, w.word),
    h('button', { class: 'speak', title: '發音 (P)', onclick: e => { e.stopPropagation(); speak(w.word); } }, '🔊'),
    copyButton(w.word),
    phoneticLine(w),
  );

  const status = w.status === 'active' ? h('div', { class: 'row small muted' },
    lightDot(s.light), LIGHT_NAMES[s.light],
    s.light !== 'green' ? progressDots(s.correct_count) : null,
    s.forget_count ? h('span', { class: 'badge red' }, `忘記過 ×${s.forget_count}`) : null,
    w.categories && w.categories.primary ? h('span', { class: 'badge accent' }, w.categories.primary) : null,
    ...(w.categories ? w.categories.others.map(c => h('span', { class: 'badge' }, c)) : []),
  ) : null;

  const meanings = sec('中文意思', ...w.meanings.map(m =>
    h('div', { class: 'meaning' + (m.is_primary ? ' primary' : '') },
      h('span', { class: 'pos' }, m.pos),
      h('span', { class: 'zh' }, m.zh),
      m.domain ? h('span', { class: 'badge accent' }, m.domain) : null,
      m.is_primary ? h('span', { class: 'muted small', title: '主要意思' }, '★') : null,
    )));

  const parts = [head, status];
  if (onStatus && w.status === 'active') parts.push(statusControl(w, onStatus));
  parts.push(meanings);
  if (w.roots) parts.push(sec('字根字首', w.roots));
  if (w.mnemonic) parts.push(sec('記憶法', mnemonicView(w.mnemonic)));
  if (w.examples.length) {
    parts.push(sec('例句', ...w.examples.map(e => h('div', { class: 'example' },
      h('div', { class: 'en' }, highlight(e.en, w.word),
        e.source === 'context' ? h('span', { class: 'badge', style: { marginLeft: '6px' }, title: e.source_title || '' },
          '原文' + (e.source_title ? '・' + e.source_title : '')) : null),
      e.zh ? h('div', { class: 'zh' }, e.zh) : null,
    ))));
  }
  if (w.supplement) parts.push(sec('補充', h('div', { style: { whiteSpace: 'pre-line' } }, w.supplement)));
  const rel = [...(w.related || []), ...(w.backlinks || []).map(b => ({ word: b.word, note: '', exists_id: b.id }))];
  if (rel.length) {
    // 英文　中文　詞性　[關係]　還沒學／（說明）；學習狀態是即時查單字庫，不是存的
    parts.push(sec('相關字', h('div', { class: 'related' }, ...rel.map(r => h('div', {},
      r.exists_id && onOpenWord
        ? h('a', { href: '#', onclick: e => { e.preventDefault(); onOpenWord(r.exists_id); } }, h('strong', {}, r.word))
        : h('strong', {}, r.word),
      r.zh ? h('span', { class: 'rel-zh' }, r.zh) : null,
      r.pos ? h('span', { class: 'rel-pos' }, r.pos) : null,
      r.rel ? h('span', { class: 'rel-tag r-' + r.rel }, r.rel) : null,
      r.exists_id ? null : h('span', { class: 'rel-new', title: '單字庫裡還沒有這個字' }, '還沒學'),
      r.note ? h('span', { class: 'muted small' }, '— ' + r.note) : null,
    )))));
  }
  if (w.my_note) parts.push(sec('我的筆記', h('div', { style: { whiteSpace: 'pre-line' } }, w.my_note)));
  if (w.dict && w.dict.translation && w.dict.translation.length) {
    parts.push(sec('字典原文', h('div', { class: 'dict-preview' }, w.dict.translation.join('\n'))));
  }
  if (w.status === 'active') {
    parts.push(h('div', { class: 'sec small muted' },
      `加入：${s.added_day || '-'}　下次複習：${s.graduated ? '已畢業' : (s.due_day || '-')}　答錯：${s.wrong_count} 次`));
  }
  return h('div', { class: 'detail' }, parts);
}
