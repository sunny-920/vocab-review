import { api, h, lightDot } from '../util.js';
import { openWordModal } from '../wordmodal.js';

export async function render(el) {
  const s = await api('/status');
  const L = s.lights;
  const total = s.total || 1;
  const pending = (s.pending.generating || 0) + (s.pending.draft || 0) + (s.pending.error || 0);

  const stat = (num, label, dot) => h('div', { class: 'stat' },
    h('div', { class: 'num' }, num), h('div', { class: 'label' }, dot ? lightDot(dot) : null, label));

  const openWord = id => openWordModal(id, { onChange: () => { el.replaceChildren(); render(el); } });

  el.append(
    h('h1', {}, `今天 ${s.today}`),
    h('div', { class: 'stats' },
      stat(s.total, '單字總數'),
      stat(L.red, '紅燈・不熟', 'red'),
      stat(L.yellow, '黃燈・學習中', 'yellow'),
      stat(L.green, '綠燈・精熟', 'green'),
      stat(pending, '待確認'),
    ),
    s.total ? h('div', { class: 'lightbar', title: '燈號分布' },
      h('div', { class: 'red', style: { width: (L.red / total * 100) + '%' } }),
      h('div', { class: 'yellow', style: { width: (L.yellow / total * 100) + '%' } }),
      h('div', { class: 'green', style: { width: (L.green / total * 100) + '%' } }),
    ) : null,

    h('div', { class: 'panel review-cta', style: { marginTop: '20px' } },
      h('div', {},
        h('h2', { style: { margin: '0 0 4px' } }, '每日複習'),
        s.review.due + s.review.new
          ? h('div', { class: 'muted' },
            `今天到期 ${s.review.due} 個`, s.review.due_red ? h('span', { class: 'warn' }, `（紅燈 ${s.review.due_red}）`) : '',
            `、新字 ${s.review.new} 個`, s.review.done ? `，已完成 ${s.review.done} 個` : '')
          : h('div', { class: 'muted' }, s.review.done ? `🎉 今天的複習都完成了（${s.review.done} 個）` : '今天沒有要複習的字')),
      h('span', { class: 'spacer' }),
      s.review.due + s.review.new
        ? h('a', { class: 'btn primary big', href: '#/review' }, '開始複習')
        : h('a', { class: 'btn', href: '#/free' }, '自由複習'),
    ),

    h('div', { class: 'panel' },
      h('div', { class: 'row' },
        h('h2', { style: { margin: 0 } }, '今天的字'),
        h('span', { class: 'spacer' }),
        h('a', { class: 'btn', href: '#/add' }, '＋ 新增單字'),
        pending ? h('a', { class: 'btn', href: '#/add' }, `${pending} 個待確認`) : null,
      ),
      s.today_words.length
        ? h('div', { class: 'chips', style: { marginTop: '12px' } },
          ...s.today_words.map(w => h('span', { class: 'chip', onclick: () => openWord(w.id) },
            lightDot(w.light), w.word, h('span', { class: 'muted small' }, w.zh),
            w.forget_count ? h('span', { class: 'badge red' }, `忘×${w.forget_count}`) : null)))
        : h('div', { class: 'muted', style: { marginTop: '8px' } }, '今天還沒有新增單字。'),
    ),

    h('div', { class: 'panel' },
      h('h2', {}, '狀態'),
      h('div', { class: 'small' },
        h('div', {}, s.ai.ok ? `✅ AI 可以使用（${s.ai.model}）` : `⚠️ AI 無法使用：${s.ai.error}。新增的單字會等到 AI 可用時再整理，也可以先用字典資料存入。`),
        h('div', {}, s.dictionary ? '✅ 離線字典已載入' : '⚠️ 找不到離線字典，請執行「安裝.bat」'),
      ),
    ),
  );
}
