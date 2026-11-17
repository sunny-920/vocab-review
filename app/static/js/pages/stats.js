// 統計：練習日曆、燈號分布、接下來的複習量、頑固字
import { api, h, lightDot, LIGHT_NAMES } from '../util.js';
import { openWordModal } from '../wordmodal.js';

const WEEKS = 26;
const BINS = [[0, 0], [1, 5], [6, 15], [16, 30], [31, Infinity]]; // 練習字數分級
const binOf = n => BINS.findIndex(([lo, hi]) => n >= lo && n <= hi);
const binLabel = ([lo, hi]) => hi === Infinity ? `${lo}+` : lo === hi ? `${lo}` : `${lo}–${hi}`;
const WD = ['日', '一', '二', '三', '四', '五', '六'];

const iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const md = s => `${Number(s.slice(5, 7))}/${Number(s.slice(8, 10))}`;
const parse = s => new Date(Number(s.slice(0, 4)), Number(s.slice(5, 7)) - 1, Number(s.slice(8, 10)));

// 共用提示框：滑過有 data-tip 的元素就顯示
function tooltipLayer(root) {
  const tip = h('div', { class: 'viz-tip hidden' });
  document.body.append(tip);
  const move = e => {
    const t = e.target.closest('[data-tip]');
    if (!t || !root.contains(t)) { tip.classList.add('hidden'); return; }
    tip.textContent = t.dataset.tip;
    tip.classList.remove('hidden');
    const pad = 14;
    let x = e.clientX + pad, y = e.clientY + pad;
    const r = tip.getBoundingClientRect();
    if (x + r.width > innerWidth - 8) x = e.clientX - r.width - pad;
    if (y + r.height > innerHeight - 8) y = e.clientY - r.height - pad;
    tip.style.left = x + 'px';
    tip.style.top = y + 'px';
  };
  root.addEventListener('mousemove', move);
  root.addEventListener('mouseleave', () => tip.classList.add('hidden'));
  return () => tip.remove();
}

function heatmap(daily, today) {
  const byDay = new Map(daily.map(d => [d.day, d]));
  const end = parse(today);
  // 每欄一週（週日～週六），最後一欄是今天所在的那一週
  const first = new Date(end);
  first.setDate(end.getDate() - end.getDay() - (WEEKS - 1) * 7);

  const cols = [];
  const months = [];
  let lastMonth = -1;
  for (let w = 0; w < WEEKS; w++) {
    const cells = [];
    for (let d = 0; d < 7; d++) {
      const day = new Date(first);
      day.setDate(first.getDate() + w * 7 + d);
      const key = iso(day);
      if (day > end) { cells.push(h('div', { class: 'hm-cell future' })); continue; }
      const x = byDay.get(key);
      const n = x ? x.words : 0;
      const tip = `${key}（週${WD[day.getDay()]}）\n` + (x
        ? `練習 ${x.words} 個字・第一次作答 ${x.answers} 次・答對 ${x.correct}` + (x.added ? `\n新增 ${x.added} 個字` : '') + (x.reinput ? `・重複輸入 ${x.reinput}` : '')
        : '沒有練習');
      cells.push(h('div', { class: `hm-cell b${binOf(n)}` + (key === today ? ' today' : ''), 'data-tip': tip }));
      if (d === 0 && day.getMonth() !== lastMonth) {
        const prev = months[months.length - 1];
        if (prev && w - prev[0] < 3) months.pop(); // 太近會重疊，留新的月份
        months.push([w, `${day.getMonth() + 1}月`]);
        lastMonth = day.getMonth();
      }
    }
    cols.push(h('div', { class: 'hm-col' }, cells));
  }
  const monthRow = h('div', { class: 'hm-months', style: { gridTemplateColumns: `repeat(${WEEKS}, var(--hm-cell))` } },
    ...months.map(([w, label]) => h('span', { style: { gridColumn: `${w + 1} / span 3` } }, label)));
  const legend = h('div', { class: 'hm-legend' },
    h('span', {}, '少'),
    ...BINS.map((b, i) => h('span', { class: `hm-cell b${i}`, title: `${binLabel(b)} 個字` })),
    h('span', {}, '多'),
    h('span', { class: 'muted' }, `（每格＝當天練習的字數：${BINS.map(binLabel).join('、')}）`));

  return h('div', { class: 'heatmap' },
    h('div', { class: 'hm-body' },
      h('div', { class: 'hm-wd' }, h('span'), ...WD.map((w, i) => h('span', {}, i % 2 ? w : ''))),
      h('div', {}, monthRow, h('div', { class: 'hm-grid' }, cols))),
    legend);
}

function dailyTable(daily) {
  const rows = [...daily].filter(d => d.words || d.added || d.reinput).reverse();
  return h('details', { class: 'table-view' },
    h('summary', {}, '表格檢視'),
    rows.length ? h('div', { class: 'table-wrap', style: { maxHeight: '280px', overflowY: 'auto', marginTop: '8px' } },
      h('table', { class: 'data static' },
        h('thead', {}, h('tr', {}, ...['日期', '練習字數', '第一次作答', '答對', '新增', '重複輸入'].map(t => h('th', {}, t)))),
        h('tbody', {}, ...rows.map(d => h('tr', {},
          h('td', {}, d.day), h('td', { class: 'num' }, d.words), h('td', { class: 'num' }, d.answers),
          h('td', { class: 'num' }, d.correct), h('td', { class: 'num' }, d.added), h('td', { class: 'num' }, d.reinput))))))
      : h('div', { class: 'muted small', style: { marginTop: '6px' } }, '還沒有紀錄'));
}

function lightBars(cats, overall) {
  const max = Math.max(1, ...cats.map(c => c.total));
  const legend = h('div', { class: 'viz-legend' }, ...['red', 'yellow', 'green'].map(l =>
    h('span', { class: 'row', style: { gap: '6px' } }, h('span', { class: 'swatch ' + l }), LIGHT_NAMES[l])));
  const row = (label, c, scale) => h('div', { class: 'lb-row' },
    h('div', { class: 'lb-label', title: label }, label),
    h('div', { class: 'lb-track' },
      h('div', { class: 'lb-bar', style: { width: (c.total / scale * 100) + '%' } },
        ...['red', 'yellow', 'green'].filter(l => c[l]).map(l => h('div', {
          class: 'lb-seg ' + l, style: { flexGrow: c[l] },
          'data-tip': `${label}\n${LIGHT_NAMES[l]}：${c[l]} 個（${Math.round(c[l] / c.total * 100)}%）`,
        })))),
    h('div', { class: 'lb-nums' }, `紅 ${c.red}・黃 ${c.yellow}・綠 ${c.green}`));
  return h('div', {},
    legend,
    h('div', { class: 'lb-list' },
      row('全部', { ...overall, total: overall.red + overall.yellow + overall.green }, overall.red + overall.yellow + overall.green || 1),
      h('div', { class: 'lb-sep' }),
      ...cats.map(c => row(c.path.replace('/', ' › '), c, max))));
}

function upcomingChart(up) {
  const max = Math.max(1, ...up.map(u => u.count));
  return h('div', {},
    h('div', { class: 'up-chart' }, ...up.map(u => {
      const d = parse(u.day);
      const label = u.today ? '今天' : md(u.day);
      return h('div', {
        class: 'up-col' + (u.today ? ' today' : ''),
        'data-tip': `${u.today ? '今天（含過期、今天的新字）' : `${u.day}（週${WD[d.getDay()]}）`}\n要複習 ${u.count} 個字`,
      },
        h('div', { class: 'up-plot' }, u.count ? h('div', { class: 'up-bar', style: { height: (u.count / max * 100) + '%' } }) : null),
        h('div', { class: 'up-num' }, u.count),
        h('div', { class: 'up-day' }, label),
        h('div', { class: 'up-wd' }, u.today ? '' : WD[d.getDay()]));
    })),
    h('div', { class: 'muted small', style: { marginTop: '6px' } }, '每欄下方的數字是當天要複習的字數；今天包含過期和今天的新字。'));
}

function stubbornTable(list, reload) {
  if (!list.length) return h('div', { class: 'muted small' }, '還沒有頑固字。忘記過或答錯過的字會出現在這裡。');
  return h('div', { class: 'table-wrap' }, h('table', { class: 'data', style: { minWidth: '620px' } },
    h('thead', {}, h('tr', {}, ...['', '英文', '中文', '燈號', '遺忘', '答錯／作答', '答錯率'].map(t => h('th', { style: { cursor: 'default' } }, t)))),
    h('tbody', {}, ...list.map((w, i) => h('tr', { onclick: () => openWordModal(w.id, { onChange: reload }) },
      h('td', { class: 'num muted' }, i + 1),
      h('td', { class: 'w' }, w.word),
      h('td', { class: 'zh' }, w.zh),
      h('td', { style: { whiteSpace: 'nowrap' } }, h('span', { class: 'row', style: { gap: '6px', flexWrap: 'nowrap' } }, lightDot(w.light), LIGHT_NAMES[w.light].split('・')[0])),
      h('td', { class: 'num' }, w.forget_count ? h('span', { class: 'badge red' }, w.forget_count) : ''),
      h('td', { class: 'num' }, `${w.wrong_answers} / ${w.answers}`),
      h('td', { class: 'num' }, w.rate === null ? '—' : w.rate + '%'))))));
}

export async function render(el) {
  const s = await api('/stats');
  const S = s.summary;
  const reload = () => { el.replaceChildren(); render(el); };

  const stat = (num, label, sub) => h('div', { class: 'stat' },
    h('div', { class: 'num' }, num), h('div', { class: 'label' }, label), sub ? h('div', { class: 'stat-sub' }, sub) : null);

  const page = h('div', { class: 'stats-page' },
    h('h1', {}, '統計'),
    h('div', { class: 'stats' },
      stat(S.total, '單字總數', `綠燈 ${S.lights.green}・黃燈 ${S.lights.yellow}・紅燈 ${S.lights.red}`),
      stat(`${S.streak} 天`, '連續練習', `最長 ${S.best_streak} 天・共練習 ${S.practice_days} 天`),
      stat(S.correct_rate === null ? '—' : `${S.correct_rate}%`, '第一次就答對', `共作答 ${S.answers} 次（不含再練）`),
      stat(S.today_words, '今天練習的字'),
    ),
    h('div', { class: 'panel', style: { marginTop: '16px' } },
      h('h2', {}, `練習日曆（最近 ${WEEKS} 週）`),
      heatmap(s.daily, s.today),
      dailyTable(s.daily)),
    h('div', { class: 'panel' },
      h('h2', {}, '接下來 14 天的複習量'),
      upcomingChart(s.upcoming)),
    h('div', { class: 'panel' },
      h('h2', {}, '各分類的燈號'),
      s.categories.length ? lightBars(s.categories, S.lights) : h('div', { class: 'muted small' }, '還沒有單字')),
    h('div', { class: 'panel' },
      h('h2', {}, '頑固字排行'),
      h('div', { class: 'muted small', style: { marginBottom: '10px' } }, '依「忘記次數 ×3 ＋ 答錯次數」排序，點一下可以看詳細資料。'),
      stubbornTable(s.stubborn, reload)),
  );
  el.append(page);
  const hm = page.querySelector('.heatmap');
  if (hm) hm.scrollLeft = hm.scrollWidth; // 窄螢幕時先顯示最近幾週
  return tooltipLayer(page);
}
