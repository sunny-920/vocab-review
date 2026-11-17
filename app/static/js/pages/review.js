// 每日複習
import { api, h } from '../util.js';
import { modePicker, runSession } from '../session.js';

export async function render(el) {
  const s = await api('/status');
  const r = s.review;
  const pending = r.due + r.new;
  let cleanup = null;

  const stat = (num, label, cls = '') => h('div', { class: 'stat' },
    h('div', { class: 'num ' + cls }, num), h('div', { class: 'label' }, label));

  if (!pending) {
    el.append(
      h('h1', {}, '每日複習'),
      h('div', { class: 'panel empty' },
        h('div', { style: { fontSize: '20px', marginBottom: '6px' } }, r.done ? '🎉 今天的複習都完成了' : '今天沒有要複習的字'),
        h('div', { class: 'muted', style: { marginBottom: '14px' } }, r.done ? `今天完成了 ${r.done} 個字。` : '新增單字後，隔天就會開始出現在這裡。'),
        h('div', { class: 'row', style: { justifyContent: 'center' } },
          h('a', { class: 'btn', href: '#/free' }, '去自由複習'),
          h('a', { class: 'btn', href: '#/add' }, '新增單字'))),
    );
    return;
  }

  const picker = modePicker();
  const start = () => {
    if (picker.mode === 'en2zh' || picker.mode === 'mixed') api('/warmup', { method: 'POST' }).catch(() => {});
    cleanup = runSession(el, {
      session: 'daily',
      mode: picker.mode,
      loadRound: async () => {
        const d = await api('/review/daily?shuffle=' + picker.shuffle);
        return { questions: d.questions, hasMore: d.remaining > 0, moreCount: Math.min(d.remaining, d.limit) };
      },
    });
  };

  el.append(
    h('h1', {}, '每日複習'),
    h('div', { class: 'stats' },
      stat(r.due, `今天到期${r.due_red ? `（紅燈 ${r.due_red}）` : ''}`, r.due_red ? 'warn' : ''),
      stat(r.new, '今天的新字（練習不計分）'),
      stat(r.done, '今天已完成'),
    ),
    h('div', { class: 'panel', style: { marginTop: '16px' } },
      h('h2', {}, '測驗方式'),
      picker.el,
      h('div', { class: 'row', style: { marginTop: '16px' } },
        h('span', { class: 'muted small' }, '一輪最多出題數可在設定裡調整；紅燈和過期最久的字優先。'),
        h('span', { class: 'spacer' }),
        h('button', { class: 'primary big', onclick: start }, `開始複習（${pending} 個）`)),
    ),
  );
  return () => cleanup && cleanup();
}
