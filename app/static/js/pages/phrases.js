// 所有文章的片語與文法（手填筆記，不進複習）
import { api, h, toast } from '../util.js';

export async function render(el) {
  let list = await api('/phrases');
  let q = '';
  const tbody = h('tbody');
  const count = h('span', { class: 'muted small' });
  const search = h('input', { placeholder: '搜尋片語、中文、說明、原句或文章…', oninput: e => { q = e.target.value.trim().toLowerCase(); draw(); } });

  function draw() {
    const shown = list.filter(p => !q || [p.text, p.zh, p.note, p.sentence, p.article_title].some(x => (x || '').toLowerCase().includes(q)));
    count.textContent = `顯示 ${shown.length} / ${list.length} 筆`;
    tbody.replaceChildren(...shown.map(p => h('tr', {},
      h('td', { class: 'pt' }, p.text),
      h('td', {}, p.zh || h('span', { class: 'muted' }, '—')),
      h('td', { class: 'phrase-note small' }, p.note || h('span', { class: 'muted' }, '—')),
      h('td', { class: 'small muted aw-sent' }, p.sentence),
      h('td', { class: 'small' }, h('a', { href: '#/article?id=' + p.article_id }, p.article_title)),
      h('td', {}, h('button', {
        class: 'ghost icon', title: '刪除', onclick: async () => {
          if (!confirm(`刪除「${p.text}」這筆片語／文法筆記？`)) return;
          try { await api('/phrases/' + p.id, { method: 'DELETE' }); list = list.filter(x => x.id !== p.id); draw(); toast('已刪除'); }
          catch (e) { toast(e.message, 'error'); }
        },
      }, '✕')),
    )));
    if (!shown.length) tbody.append(h('tr', {}, h('td', { colspan: 6, class: 'empty' },
      list.length ? '沒有符合的片語' : '還沒有片語或文法筆記。在文章裡選取文字，按「存成片語／文法」就會出現在這裡。')));
  }

  el.append(
    h('div', { class: 'row', style: { marginBottom: '12px' } },
      h('h1', { style: { margin: 0 } }, '片語與文法'),
      h('span', { class: 'spacer' }),
      h('a', { href: '#/articles', class: 'small' }, '← 文章清單')),
    h('div', { class: 'muted small', style: { marginBottom: '10px' } }, '各篇文章裡存的片語和文法筆記（不進複習）。要修改，點文章名稱回到那篇文章。'),
    h('div', { class: 'row', style: { marginBottom: '8px' } }, h('div', { style: { flex: 1 } }, search), count),
    h('div', { class: 'table-wrap' }, h('table', { class: 'data static phrase-table' },
      h('thead', {}, h('tr', {}, ...['片語／文法', '中文', '說明', '原句', '文章', ''].map(t => h('th', {}, t)))),
      tbody)),
  );
  draw();
}
