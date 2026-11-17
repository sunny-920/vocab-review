// 測驗：出題、作答、判分、推翻判定、答錯的字在這一輪最後再出現
import { api, h, lightDot, speak, stopSpeaking, isMuted, spellDiff, storageGet, storageSet, toast } from './util.js';
import { renderDetail, phoneticLine, highlight } from './detail.js';
import { openWordModal } from './wordmodal.js';

export const MODES = [
  ['en2zh', '英→中', '看英文，寫出中文意思（答中一個就算對）'],
  ['zh2en', '中→英（提示）', '看中文和首字母，拼出英文'],
  ['cloze', '中→英（例句填空）', '在例句的空格填入正確的字（要填句子裡的形態）'],
  ['listen', '聽寫', '聽英文發音，拼出單字'],
  ['mixed', '混合', '以上四種隨機出現（靜音時不出聽寫）'],
];

// 配對題只在自由複習（一次出一組，不能和一題一題的混在一起；不算進複習紀錄）
export const MATCH_MODE = ['match', '配對（拖曳）', '把中文拖到對應的英文，一次一組（練習用，不算進複習紀錄）'];

// opts.compact：精簡的選項清單（自由複習右邊那欄用），說明放在滑鼠提示；opts.withMatch：多「配對」
export function modePicker(opts = {}) {
  const modes = opts.withMatch ? [...MODES.slice(0, -1), MATCH_MODE, MODES[MODES.length - 1]] : MODES;
  let mode = storageGet('review-mode', 'mixed');
  if (!modes.some(([k]) => k === mode)) mode = 'mixed';  // 每日複習沒有「配對」
  let shuffle = storageGet('review-shuffle', false);
  if (opts.compact) {
    const items = modes.map(([key, label, desc]) => h('label', { class: 'mode-row', title: desc },
      h('input', { type: 'radio', name: 'mode', checked: key === mode, onchange: () => { mode = key; storageSet('review-mode', key); } }),
      h('span', {}, label)));
    const el = h('div', { class: 'mode-list' }, ...items,
      h('label', { class: 'mode-row small muted', title: '照分類排太好猜時再打開', style: { marginTop: '4px' } },
        h('input', { type: 'checkbox', checked: shuffle, onchange: e => { shuffle = e.target.checked; storageSet('review-shuffle', shuffle); } }),
        '同分類內打亂順序'));
    return { el, get mode() { return mode; }, get shuffle() { return shuffle; } };
  }
  const cards = modes.map(([key, label, desc]) => {
    const c = h('label', { class: 'mode-card' + (key === mode ? ' on' : '') },
      h('input', { type: 'radio', name: 'mode', checked: key === mode, onchange: () => {
        mode = key; storageSet('review-mode', key);
        cards.forEach(x => x.classList.toggle('on', x === c));
      } }),
      h('div', { class: 'mode-label' }, label),
      h('div', { class: 'mode-desc' }, desc));
    return c;
  });
  const el = h('div', {},
    h('div', { class: 'mode-grid' }, cards),
    h('label', { class: 'check', style: { marginTop: '10px' } },
      h('input', { type: 'checkbox', checked: shuffle, onchange: e => { shuffle = e.target.checked; storageSet('review-shuffle', shuffle); } }),
      '同分類內打亂順序（照分類排太好猜時再打開）'),
  );
  return { el, get mode() { return mode; }, get shuffle() { return shuffle; } };
}

// 「e _ _ _ _ _ _」：每個字只顯示第一個字母
function pattern(ans) {
  let out = '';
  for (let i = 0; i < ans.length; i++) {
    const c = ans[i];
    if (/[A-Za-z]/.test(c)) out += (i === 0 || !/[A-Za-z]/.test(ans[i - 1]) ? c : '_') + ' ';
    else if (/\s/.test(c)) out += '  ';
    else out += c + ' ';
  }
  return out.trim();
}
const letterCounts = ans => ans.split(/\s+/).map(w => w.replace(/[^A-Za-z]/g, '').length).join(' + ');

function pickMode(q, mode) {
  if (mode === 'cloze') return q.cloze.length ? 'cloze' : 'zh2en';
  if (mode !== 'mixed') return mode;
  const opts = ['en2zh', 'zh2en'];
  if (q.cloze.length) opts.push('cloze');
  if (!isMuted()) opts.push('listen');
  return opts[Math.floor(Math.random() * opts.length)];
}

function makeItem(q, mode) {
  const m = pickMode(q, mode);
  return { q, mode: m, cloze: m === 'cloze' ? q.cloze[Math.floor(Math.random() * q.cloze.length)] : null, retry: false };
}

/**
 * opts.session: 'daily' | 'free'
 * opts.mode:    'en2zh' | 'zh2en' | 'cloze' | 'mixed'
 * opts.loadRound(): Promise<{ questions, hasMore, moreCount }>
 * 回傳 cleanup()
 */
export function runSession(el, opts) {
  let items = [];
  let pos = 0;
  let total = 0;
  let firstDone = 0;
  let ok = 0;
  let ng = 0;
  let wrongWords = new Map();
  let phase = 'idle';  // ask / grading / result / end
  let current = null;
  let moreInfo = { hasMore: false, moreCount: 0 };

  const root = h('div', { class: 'session' });
  el.replaceChildren(root);

  async function startRound() {
    root.replaceChildren(h('div', { class: 'empty' }, '載入題目中…'));
    let r;
    try { r = await opts.loadRound(); } catch (e) { root.replaceChildren(h('div', { class: 'empty' }, '載入失敗：' + e.message)); return; }
    if (!r.questions.length) { showEnd(true); return; }
    moreInfo = r;
    items = r.questions.map(q => makeItem(q, opts.mode));
    pos = 0; total = items.length; firstDone = 0; ok = 0; ng = 0; wrongWords = new Map();
    showItem();
  }

  function header(item) {
    const pct = total ? Math.round(firstDone / total * 100) : 0;
    const badge = item.retry ? h('span', { class: 'badge yellow' }, '再練一次・不計分')
      : item.q.learning ? h('span', { class: 'badge accent' }, '今天的新字・練習不計分')
        : opts.session === 'free' ? h('span', { class: 'badge' }, '自由複習') : null;
    return h('div', { class: 'session-head' },
      h('div', { class: 'row' },
        h('span', { class: 'small muted' }, `${item.retry || phase !== 'ask' ? firstDone : firstDone + 1} / ${total}`),
        badge,
        h('span', { class: 'spacer' }),
        h('span', { class: 'small' }, h('span', { class: 'ok-text' }, `✓ ${ok}`), '　', h('span', { class: 'warn' }, `✗ ${ng}`)),
        lightDot(item.q.stats.light),
      ),
      h('div', { class: 'progress' }, h('div', { style: { width: pct + '%' } })),
    );
  }

  function prompt(item) {
    const q = item.q;
    if (item.mode === 'en2zh') {
      // 例句提示：按了才顯示，只給英文（中文翻譯會洩漏答案）
      const ex = q.hint_example;  // 一般用 AI 例句；自由複習選了文章時用那篇的原文（後端決定）
      const hintBox = h('div', { class: 'hint-sentence hidden' });
      const hintBtn = ex ? h('button', {
        class: 'small ghost hint-btn', type: 'button', onclick: () => {
          hintBox.replaceChildren(...highlight(ex.en, q.word));
          hintBox.classList.remove('hidden');
          hintBtn.remove();
          item.inputs && item.inputs[0].focus();
        },
      }, '💡 例句提示') : null;
      return h('div', { class: 'prompt' },
        h('div', { class: 'prompt-word' }, q.word,
          h('button', { class: 'speak', title: '發音 (P)', onclick: () => speak(q.word) }, '🔊')),
        phoneticLine(q),
        hintBtn, hintBox);
    }
    if (item.mode === 'listen') {
      return h('div', { class: 'prompt' },
        h('button', { class: 'listen-btn', type: 'button', title: '再聽一次（Ctrl+空白）', onclick: () => { speak(q.word); item.inputs && item.inputs[0].focus(); } }, '🔊'),
        h('div', { class: 'prompt-label' }, `拼出你聽到的字（${letterCounts(q.word)} 個字母）・Ctrl+空白 再聽一次`));
    }
    if (item.mode === 'zh2en') {
      return h('div', { class: 'prompt' },
        h('div', { class: 'prompt-meanings' }, ...q.prompt_meanings.map(m => h('div', {},
          h('span', { class: 'pos' }, m.pos), ' ', m.zh, m.domain ? h('span', { class: 'badge accent', style: { marginLeft: '6px' } }, m.domain) : null))),
        h('div', { class: 'prompt-pattern' }, pattern(q.word)),
        h('div', { class: 'prompt-label' }, `拼出英文（${letterCounts(q.word)} 個字母）`));
    }
    const c = item.cloze;
    return h('div', { class: 'prompt' },
      h('div', { class: 'prompt-sentence' }, c.before, h('span', { class: 'blank' }, pattern(c.answer)), c.after),
      c.zh ? h('div', { class: 'prompt-zh' }, c.zh) : null,
      h('div', { class: 'prompt-label' }, `填入空格（${letterCounts(c.answer)} 個字母，要填句子裡的形態）`));
  }

  function showItem() {
    const item = items[pos];
    current = item;
    phase = 'ask';
    const isZh = item.mode === 'en2zh';
    const input = h('input', {
      class: 'answer-input', autocomplete: 'off', spellcheck: 'false', autocapitalize: 'off',
      placeholder: isZh ? '輸入中文…' : '輸入英文…', lang: isZh ? 'zh-Hant' : 'en',
    });
    const submitBtn = h('button', { class: 'primary', onclick: () => submit(item, input.value) }, '送出');
    const giveUp = h('button', { onclick: () => submit(item, '') }, '不會');
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.isComposing && e.keyCode !== 229) { e.preventDefault(); submit(item, input.value); }
    });
    root.replaceChildren(
      header(item),
      h('div', { class: 'panel q-card' },
        prompt(item),
        h('div', { class: 'answer-row' }, input, giveUp, submitBtn),
        h('div', { class: 'small muted', style: { marginTop: '8px' } }, h('kbd', {}, 'Enter'), ' 送出　空白送出＝不會'),
      ),
    );
    item.inputs = [input, submitBtn, giveUp];
    input.focus();
    // 自動念：英→中、聽寫一出題就念單字；中→英兩種等答完才念（不然等於念出答案）
    if (item.mode === 'en2zh') speak(item.q.word, { auto: true });
    else if (item.mode === 'listen') speak(item.q.word);  // 聽寫一定要有聲音：靜音時會提示
    else stopSpeaking();
  }

  async function submit(item, answer) {
    if (phase !== 'ask' || item !== current) return;
    phase = 'grading';
    item.inputs.forEach(x => { x.disabled = true; });
    const waiting = h('div', { class: 'small muted', style: { marginTop: '10px' } },
      h('span', { class: 'spinner' }), item.mode === 'en2zh' ? ' 判斷中…' : '');
    item.inputs[0].closest('.q-card').append(waiting);
    const expected = item.mode === 'cloze' ? item.cloze.answer : item.q.word;
    try {
      item.result = await api('/review/answer', {
        method: 'POST',
        body: { word_id: item.q.id, mode: item.mode, answer, expected, session: opts.session, retry: item.retry },
      });
    } catch (e) {
      toast(e.message, 'error');
      waiting.remove();
      item.inputs.forEach(x => { x.disabled = false; });
      phase = 'ask';
      return;
    }
    item.answer = answer;
    if (!item.retry) {
      firstDone++;
      item.result.correct ? ok++ : ng++;
    }
    showResult(item);
  }

  async function flip(item) {
    if (phase !== 'result' || item.result.method === 'blank') return;
    const to = !item.result.correct;
    try {
      const r = await api('/review/override', { method: 'POST', body: { event_id: item.result.event_id, correct: to } });
      if (!item.retry) { if (to) { ok++; ng--; } else { ok--; ng++; } }
      item.result = r;
      showResult(item);
    } catch (e) { toast(e.message, 'error'); }
  }

  function showResult(item) {
    phase = 'result';
    const r = item.result;
    const q = item.q;
    const expected = item.mode === 'cloze' ? item.cloze.answer : q.word;
    const note = {
      ai: 'AI 判斷：' + r.reason,
      accepted: r.reason,
      ai_unavailable: 'AI 無法使用，請自己判斷對錯（' + r.reason + '）',
      override: r.reason,
    }[r.method];

    const lines = [];
    if (!r.correct && item.answer.trim()) {
      if (item.mode === 'en2zh') {
        lines.push(h('div', {}, '你寫的：', h('strong', {}, item.answer)));
      } else {
        const d = spellDiff(item.answer.trim(), expected);
        lines.push(h('div', { class: 'diff' }, h('span', { class: 'muted' }, '你寫的　'), d.mine));
        lines.push(h('div', { class: 'diff' }, h('span', { class: 'muted' }, '正確的　'), d.right));
      }
    } else if (!r.correct && item.mode !== 'en2zh') {
      lines.push(h('div', { class: 'diff' }, h('span', { class: 'muted' }, '正確的　'), h('strong', {}, expected)));
    }
    const fullSentence = item.mode === 'cloze' ? item.cloze.before + item.cloze.answer + item.cloze.after : '';
    const sayAnswer = auto => (item.mode === 'cloze'
      ? speak(fullSentence, { kind: 'sentence', auto })   // 例句即時產生、不存
      : speak(q.word, { auto }));
    if (item.mode === 'cloze') {
      lines.push(h('div', { class: 'prompt-sentence small-sentence' }, item.cloze.before, h('mark', {}, item.cloze.answer), item.cloze.after,
        h('button', { class: 'speak', title: '念這句 (P)', onclick: () => sayAnswer(false) }, '🔊')));
    }
    item.sayAnswer = sayAnswer;

    const overrideBtn = r.method === 'blank' ? null : h('button', { onclick: () => flip(item) },
      r.correct ? '其實錯了' : '我其實答對了', h('kbd', { style: { marginLeft: '6px' } }, r.correct ? '2' : '1'));
    const nextBtn = h('button', { class: 'primary', onclick: next }, '下一題', h('kbd', { style: { marginLeft: '6px' } }, 'Enter'));

    root.replaceChildren(
      header(item),
      h('div', { class: 'panel result ' + (r.correct ? 'is-ok' : 'is-ng') },
        h('div', { class: 'result-head' },
          h('span', { class: 'verdict' }, r.correct ? '✓ 答對了' : r.method === 'blank' ? '✗ 不會' : '✗ 答錯'),
          h('span', { class: 'spacer' }),
          overrideBtn, nextBtn),
        note ? h('div', { class: 'small muted' }, note) : null,
        ...lines,
        h('div', { class: 'effect small' }, r.effect),
      ),
      h('div', { class: 'panel' },
        h('div', { class: 'row', style: { justifyContent: 'flex-end', marginBottom: '-8px' } },
          h('button', {
            class: 'small', title: '修改這個字的資料（意思、例句、分類、燈號…）',
            onclick: () => openWordModal(q.id, {
              edit: true,
              onChange: w => { if (w) { r.word = w; item.q = { ...item.q, ...w }; showResult(item); } },
            }),
          }, '✎ 編輯單字')),
        renderDetail(r.word)),
    );
    // 焦點不要留在按鈕上，否則按 Enter 會同時觸發按鈕和快捷鍵
    if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur();
    // 中→英：答完念一次正確的英文（推翻判定、編輯後重畫不再念）
    if (!item.saidAnswer && (item.mode === 'zh2en' || item.mode === 'cloze')) { item.saidAnswer = true; sayAnswer(true); }
  }

  function next() {
    if (phase !== 'result') return;
    const item = items[pos];
    if (!item.result.correct) {  // 答錯的字放到這一輪最後，答對一次才結束
      wrongWords.set(item.q.id, item.q);
      items.push({ q: item.q, mode: item.mode, cloze: item.cloze, retry: true });
    }
    pos++;
    if (pos < items.length) showItem(); else showEnd(false);
  }

  function showEnd(nothing) {
    phase = 'end';
    if (nothing) {
      root.replaceChildren(h('div', { class: 'panel empty' },
        h('div', { style: { fontSize: '20px', marginBottom: '8px' } }, '🎉 沒有要複習的字了'),
        h('a', { class: 'btn', href: '#/' }, '回首頁')));
      return;
    }
    const wrong = [...wrongWords.values()];
    root.replaceChildren(h('div', { class: 'panel' },
      h('h2', {}, '這一輪完成了'),
      h('div', { class: 'stats', style: { marginBottom: '14px' } },
        h('div', { class: 'stat' }, h('div', { class: 'num' }, total), h('div', { class: 'label' }, '題數')),
        h('div', { class: 'stat' }, h('div', { class: 'num ok-text' }, ok), h('div', { class: 'label' }, '第一次就答對')),
        h('div', { class: 'stat' }, h('div', { class: 'num warn' }, ng), h('div', { class: 'label' }, '答錯'))),
      wrong.length ? h('div', {},
        h('div', { class: 'small muted', style: { marginBottom: '6px' } }, '這一輪答錯的字'),
        h('div', { class: 'chips' }, ...wrong.map(q => h('span', { class: 'chip' }, lightDot('red'), q.word, h('span', { class: 'muted small' }, q.prompt_meanings[0]?.zh || ''))))) : null,
      h('div', { class: 'row', style: { marginTop: '16px' } },
        h('span', { class: 'spacer' }),
        h('a', { class: 'btn', href: '#/' }, '回首頁'),
        moreInfo.hasMore ? h('button', { class: 'primary', onclick: startRound }, `再來 ${moreInfo.moreCount} 個`) : null),
    ));
  }

  const onKey = e => {
    if (phase !== 'result') return;
    if (document.querySelector('.modal-backdrop')) return;  // 編輯視窗開著時不要觸發快捷鍵
    if (e.target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return;
    if (e.ctrlKey || e.altKey || e.metaKey) return;
    if (e.key === 'Enter') { e.preventDefault(); next(); }
    else if (e.key === '1' && !current.result.correct) { e.preventDefault(); flip(current); }
    else if (e.key === '2' && current.result.correct) { e.preventDefault(); flip(current); }
    else if (e.key === 'p' || e.key === 'P') (current.sayAnswer ? current.sayAnswer(false) : speak(current.q.word));
  };
  // 聽寫作答時要在輸入框打字，不能用 P；改用 Ctrl+空白 再聽一次
  const onAskKey = e => {
    if (phase !== 'ask' || !current || current.mode !== 'listen') return;
    if (e.ctrlKey && e.key === ' ') { e.preventDefault(); speak(current.q.word); }
  };
  document.addEventListener('keydown', onKey);
  document.addEventListener('keydown', onAskKey);
  startRound();
  return () => { document.removeEventListener('keydown', onKey); document.removeEventListener('keydown', onAskKey); stopSpeaking(); };
}
