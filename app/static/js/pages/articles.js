// 文章：貼上新文章、文章清單
import { api, h, toast } from '../util.js';

export async function render(el) {
  const list = await api('/articles');

  const title = h('input', { placeholder: '標題（留空就用第一行）' });
  const source = h('input', { placeholder: '來源網址或書名（選填）' });
  const text = h('textarea', { class: 'paste-box', rows: 12, spellcheck: 'false', placeholder: '把文章貼在這裡。從網頁或 PDF 複製都可以，斷行、頁碼等雜訊會自動整理。' });
  const submitBtn = h('button', {
    class: 'primary', onclick: async () => {
      if (!text.value.trim()) { toast('請先貼上文章', 'error'); return; }
      submitBtn.disabled = true;
      try {
        const { id } = await api('/articles', { method: 'POST', body: { title: title.value, source: source.value, text: text.value } });
        location.hash = '#/article?id=' + id;
      } catch (e) { toast(e.message, 'error'); submitBtn.disabled = false; }
    },
  }, '開始閱讀');

  const rows = list.map(a => h('div', { class: 'article-item', 'data-q': (a.title + ' ' + a.source).toLowerCase() },
    h('a', { href: '#/article?id=' + a.id, class: 'a-title' }, a.title),
    h('div', { class: 'muted small' }, [
      a.source || null,
      `${a.words} 個生字`,
      a.phrases ? `${a.phrases} 個片語／文法` : null,
      a.has_note ? '有備註' : null,
      `約 ${Math.max(1, Math.round(a.chars / 1000))}k 字元`,
      (a.opened_at ? '上次閱讀 ' + a.opened_at.slice(0, 16) : '新增於 ' + a.created_at.slice(0, 10)),
    ].filter(Boolean).join('　·　')),
    h('button', {
      class: 'ghost small danger-text', title: '刪除這篇文章（單字不會被刪）', onclick: async () => {
        if (!confirm(`刪除文章「${a.title}」？\n從這篇加入的單字和例句會保留。`)) return;
        await api('/articles/' + a.id, { method: 'DELETE' });
        toast('已刪除');
        el.replaceChildren(); render(el);
      },
    }, '刪除'),
  ));

  const noHit = h('div', { class: 'muted small hidden', style: { padding: '10px 0' } }, '找不到符合的文章');
  const search = h('input', {
    placeholder: '搜尋標題或來源…', style: { marginBottom: '6px' }, oninput: e => {
      const q = e.target.value.trim().toLowerCase();
      let n = 0;
      rows.forEach(r => { const ok = !q || r.dataset.q.includes(q); r.classList.toggle('hidden', !ok); n += ok; });
      noHit.classList.toggle('hidden', n > 0);
    },
  });

  el.append(
    h('h1', {}, '文章'),
    h('div', { class: 'panel' },
      h('h2', {}, '新增文章'),
      h('div', { class: 'two', style: { marginBottom: '10px' } },
        h('label', { class: 'field' }, h('span', {}, '標題'), title),
        h('label', { class: 'field' }, h('span', {}, '來源'), source)),
      text,
      h('div', { class: 'row', style: { marginTop: '10px' } },
        h('span', { class: 'muted small' }, '貼上後馬上可以讀；AI 會在背景重新排版，好了再問你要不要套用。'),
        h('span', { class: 'spacer' }), submitBtn),
    ),
    h('div', { class: 'panel' },
      h('div', { class: 'row', style: { marginBottom: '8px' } },
        h('h2', { style: { margin: 0 } }, `我的文章（${list.length}）`),
        h('span', { class: 'spacer' }),
        h('a', { href: '#/phrases', class: 'small' }, '📒 所有片語與文法 →')),
      list.length > 3 ? search : null,
      list.length ? h('div', { class: 'article-list' }, rows, noHit) : h('div', { class: 'empty' }, '還沒有文章。'),
    ),
  );
}
