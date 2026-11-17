// 單字卡：依分類瀏覽、翻卡
import { api, h, lightDot, openModal, speak, stopSpeaking, isTyping, toast } from '../util.js';
import { renderDetail, applyStatus, statusToast, copyButton } from '../detail.js';
import { openWordModal } from '../wordmodal.js';

export async function render(el) {
  cache.clear();
  const groups = await api('/browse');
  // 在翻卡視窗裡改了進度，關掉後重畫卡片清單的燈號
  let dirty = false;
  const openViewer = (list, start) => openViewerModal(list, start, () => { dirty = true; }, () => {
    if (dirty && location.hash.startsWith('#/cards')) {  // 換到別頁時就不重畫
      dirty = false; const y = scrollY; el.replaceChildren(); render(el).then(() => scrollTo(0, y));
    }
  });
  if (!groups.length) {
    el.append(h('h1', {}, '單字卡'), h('div', { class: 'panel empty' }, '還沒有單字。', h('a', { href: '#/add' }, '去新增單字 →')));
    return;
  }
  const all = groups.flatMap(g => g.words);
  const anchor = i => 'cat-' + i;

  const nav = h('div', { class: 'cat-nav' },
    h('div', { class: 'muted small', style: { padding: '0 10px 6px' } }, `共 ${new Set(all.map(w => w.id)).size} 個字`),
    ...groups.map((g, i) => h('a', {
      href: '#', class: g.path.includes('/') ? 'child' : '',
      onclick: e => { e.preventDefault(); document.getElementById(anchor(i)).scrollIntoView({ behavior: 'smooth' }); },
    }, h('span', {}, g.path), h('span', { class: 'n' }, g.words.length))),
  );

  const content = h('div', {}, ...groups.map((g, i) => h('section', { class: 'cat-group', id: anchor(i) },
    h('div', { class: 'row' },
      h('h2', {}, g.path),
      h('span', { class: 'muted small' }, `${g.words.length} 個`),
      h('span', { class: 'spacer' }),
      h('button', { class: 'small', onclick: () => openViewer(g.words, 0) }, '翻卡這一類'),
    ),
    h('div', { class: 'card-grid' }, ...g.words.map(w => h('div', {
      class: 'wcard ' + w.light, onclick: () => openViewer(all, all.indexOf(w)),
    },
      h('div', { class: 'w' }, w.word),
      h('div', { class: 'meta' },
        w.secondary
          ? h('span', { class: 'badge', title: `主分類：${w.category}` }, '其他分類')
          : h('span', {}, w.pos),
        h('span', { class: 'row', style: { gap: '4px' } },
          w.forget_count ? h('span', { class: 'badge red' }, `忘×${w.forget_count}`) : null,
          lightDot(w.light)),
      ),
    ))),
  )));

  el.append(h('h1', {}, '單字卡'), h('div', { class: 'cards-layout' }, nav, content));
}

const cache = new Map();

function openViewerModal(list, start, onChanged, onClosed) {
  let i = start;
  let flipped = false;
  const flip = h('div', { class: 'flip' });
  const counter = h('span', { class: 'pos' });
  const prevBtn = h('button', { onclick: () => go(-1) }, '← 上一張');
  const nextBtn = h('button', { onclick: () => go(1) }, '下一張 →');

  const box = h('div', { class: 'viewer' },
    flip,
    h('div', { class: 'viewer-bar' },
      prevBtn, counter, nextBtn,
      h('button', { class: 'ghost', style: { color: '#fff' }, onclick: () => close() }, '✕'),
    ),
    h('div', { style: { color: '#fff', opacity: .7, fontSize: '12px', textAlign: 'center', marginTop: '6px' } },
      matchMedia('(hover: none)').matches ? '點卡片翻面　左右滑動換卡' : '空白鍵翻面　← → 換卡　P 發音　Esc 關閉'),
  );

  async function draw() {
    const s = list[i];
    flipped = false;
    flip.classList.remove('flipped');
    counter.textContent = `${i + 1} / ${list.length}　${s.category || ''}`;
    prevBtn.disabled = i === 0;
    nextBtn.disabled = i === list.length - 1;
    const frontStatus = h('div', { class: 'row' });
    const drawFrontStatus = () => frontStatus.replaceChildren(...[lightDot(s.light),
      s.forget_count ? h('span', { class: 'badge red' }, `忘記過 ×${s.forget_count}`) : null].filter(Boolean));
    drawFrontStatus();
    const front = h('div', { class: 'face front', onclick: toggle },
      frontStatus,
      h('div', { class: 'w' }, s.word),
      h('div', { class: 'row' },
        h('button', { class: 'speak', title: '發音 (P)', onclick: e => { e.stopPropagation(); speak(s.word); } }, '🔊'),
        copyButton(s.word)),
      h('div', { class: 'muted small' }, '點一下翻面'),
    );
    const back = h('div', { class: 'face back' }, h('div', { class: 'muted' }, '載入中…'));
    const inner = h('div', { class: 'flip-inner' }, front, back);
    flip.replaceChildren(inner);
    speak(s.word, { auto: true });  // 打開、換卡就念一次
    let w = cache.get(s.id);
    if (!w) { w = await api('/words/' + s.id); cache.set(s.id, w); }
    if (list[i] !== s) return;
    const fillBack = () => back.replaceChildren(
      h('div', { class: 'row', style: { justifyContent: 'flex-end', marginBottom: '-8px' } },
        h('button', { class: 'small', onclick: () => { close(); openWordModal(s.id); } }, '編輯'),
        h('button', { class: 'small ghost', onclick: toggle }, '翻回正面')),
      renderDetail(w, {
        onOpenWord: id => { close(); openWordModal(id); },
        onStatus: async (kind, value) => {
          try {
            w = await applyStatus(s.id, kind, value);
            cache.set(s.id, w);
            s.light = w.stats.light;           // 正面和卡片清單的燈號一起更新
            s.correct_count = w.stats.correct_count;
            drawFrontStatus();
            onChanged && onChanged();
            fillBack();
            toast(statusToast(w, kind, value));
          } catch (e) { toast(e.message, 'error'); }
        },
      }),
    );
    fillBack();
  }

  let turning = false;
  function toggle() {
    const inner = flip.querySelector('.flip-inner');
    if (turning || !inner) return;
    turning = true;
    inner.classList.add('turning');      // 先壓扁
    setTimeout(() => {
      turning = false;
      if (!inner.isConnected) return;    // 動畫中換了下一張卡
      flipped = !flipped;
      flip.classList.toggle('flipped', flipped);
      inner.classList.remove('turning'); // 換面後展開
    }, 160);
  }
  function go(d) {
    const n = i + d;
    if (n < 0 || n >= list.length) return;
    i = n;
    draw();
  }
  // 手機：左右滑動換卡
  let touchX = null, touchY = null;
  flip.addEventListener('touchstart', e => { const t = e.changedTouches[0]; touchX = t.clientX; touchY = t.clientY; }, { passive: true });
  flip.addEventListener('touchend', e => {
    if (touchX == null) return;
    const t = e.changedTouches[0];
    const dx = t.clientX - touchX, dy = t.clientY - touchY;
    touchX = null;
    if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5) go(dx < 0 ? 1 : -1);
  }, { passive: true });
  const onKey = e => {
    if (isTyping(e)) return;
    if (e.key === ' ') { e.preventDefault(); toggle(); }
    else if (e.key === 'ArrowRight') go(1);
    else if (e.key === 'ArrowLeft') go(-1);
    else if (e.key === 'p' || e.key === 'P') speak(list[i].word);
  };
  document.addEventListener('keydown', onKey);
  const close = openModal(box, { bare: true, onClose: () => { document.removeEventListener('keydown', onKey); stopSpeaking(); onClosed && onClosed(); } });
  draw();
}
