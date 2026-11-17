// 配對題（自由複習）：左邊英文、下面打亂的中文卡片，把中文拖到對應的英文。
// - 每個字只出一個意思：選了出處文章就用那篇的意思，否則用主要意思的前 1～2 個說法
// - 同一組不放中文很像的字（兩張「足夠的」會分不出來）
// - 一組電腦 8 個、手機 6 個；放對變綠、放錯彈回去
// - 練習用：完全不寫進複習紀錄（答對不算、答錯也不算）
import { h, speak, stopSpeaking, lightDot } from './util.js';

const isPhone = () => matchMedia('(max-width: 700px)').matches;

function meaningOf(q) {
  const src = (q.context_meaning || (q.prompt_meanings[0] || q.meanings[0] || {}).zh || '').trim();
  return src.split(/[、，,；;]/).map(t => t.trim()).filter(Boolean).slice(0, 2).join('、') || src;
}
const chars = s => new Set([...s].filter(c => c >= '一' && c <= '鿿'));
function similar(a, b) {
  const ta = a.split('、'), tb = b.split('、');
  if (ta.some(x => tb.includes(x))) return true;
  const ca = chars(a), cb = chars(b);
  let n = 0;
  for (const c of ca) if (cb.has(c)) n++;
  return n >= 2 || (n >= 1 && Math.min(ca.size, cb.size) <= 2);
}

// 分組：依序放進第一個「沒有意思很像的字」的組；放不進去就開新組
function makeGroups(items, size) {
  const groups = [];
  for (const it of items) {
    const g = groups.find(g => g.length < size && !g.some(o => similar(o.zh, it.zh)));
    if (g) g.push(it); else groups.push([it]);
  }
  return groups;
}

const shuffle = a => { const b = [...a]; for (let i = b.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [b[i], b[j]] = [b[j], b[i]]; } return b; };

export function runMatch(el, questions) {
  const items = questions.map(q => ({ id: q.id, word: q.word, zh: meaningOf(q), light: q.stats.light })).filter(x => x.zh);
  const size = isPhone() ? 6 : 8;
  let groups = makeGroups(items, size);
  let gi = 0;
  const missed = new Map();  // 這一輪配錯過的字（只在畫面上列出，不寫進紀錄）
  const root = h('div', { class: 'session match' });
  el.replaceChildren(root);

  function showGroup() {
    const g = groups[gi];
    let selected = null;   // 點選模式：先點中文卡片
    let wrongs = 0;
    const done = new Set();
    const rows = new Map();  // id → {row, slot}
    const chips = new Map(); // id → chip

    const status = h('span', { class: 'small muted' });
    const drawStatus = () => { status.textContent = `第 ${gi + 1} / ${groups.length} 組　配對 ${done.size} / ${g.length}　錯 ${wrongs} 次`; };

    const list = h('div', { class: 'match-rows' }, ...g.map(it => {
      const slot = h('div', { class: 'match-slot', 'data-id': it.id }, '拖到這裡');
      const row = h('div', { class: 'match-row', 'data-id': it.id },
        h('button', { type: 'button', class: 'match-word', title: '點一下聽發音', onclick: () => speak(it.word) },
          lightDot(it.light), h('span', {}, it.word), h('span', { class: 'match-spk' }, '🔊')),
        slot);
      row.addEventListener('click', e => { if (selected && !e.target.closest('.match-word')) tryPlace(selected, it.id); });
      rows.set(it.id, { row, slot });
      return row;
    }));
    const pool = h('div', { class: 'match-pool' }, ...shuffle(g).map(it => {
      const chip = h('div', { class: 'match-chip', 'data-id': it.id, title: it.zh }, h('span', {}, it.zh));
      chips.set(it.id, chip);
      setupDrag(chip, it.id);
      return chip;
    }));

    function select(id) {
      selected = selected === id ? null : id;
      chips.forEach((c, k) => c.classList.toggle('selected', k === selected));
      root.classList.toggle('picking', selected != null);
    }
    function tryPlace(chipId, rowId) {
      const chip = chips.get(chipId);
      const { row, slot } = rows.get(rowId);
      if (done.has(rowId)) return;
      select(null);
      if (chipId === rowId) {
        done.add(rowId);
        slot.textContent = chip.textContent;
        slot.classList.add('ok');
        row.classList.add('ok');
        chip.remove();
        drawStatus();
        if (done.size === g.length) finishGroup();
      } else {
        wrongs++;
        const it = g.find(x => x.id === rowId);
        missed.set(rowId, it);
        row.classList.remove('bad'); void row.offsetWidth; row.classList.add('bad');
        chip.classList.remove('shake'); void chip.offsetWidth; chip.classList.add('shake');
        drawStatus();
      }
    }

    // 拖曳：用 pointer 事件自己做（iPhone Safari 不支援網頁原生的拖放）；沒拖動就當成「點選」
    function setupDrag(chip, id) {
      chip.addEventListener('pointerdown', e => {
        if (e.button !== 0) return;
        e.preventDefault();
        const start = { x: e.clientX, y: e.clientY };
        const rect = chip.getBoundingClientRect();
        let ghost = null;
        const move = ev => {
          if (!ghost && Math.hypot(ev.clientX - start.x, ev.clientY - start.y) < 6) return;
          if (!ghost) {
            ghost = chip.cloneNode(true);
            ghost.classList.add('ghost');
            ghost.style.width = rect.width + 'px';
            document.body.append(ghost);
            chip.classList.add('dragging');
          }
          ghost.style.left = ev.clientX - rect.width / 2 + 'px';
          ghost.style.top = ev.clientY - rect.height / 2 + 'px';
          const over = document.elementFromPoint(ev.clientX, ev.clientY);
          rows.forEach(r => r.row.classList.toggle('over', !!over && r.row.contains(over)));
        };
        const up = ev => {
          document.removeEventListener('pointermove', move);
          document.removeEventListener('pointerup', up);
          document.removeEventListener('pointercancel', up);
          rows.forEach(r => r.row.classList.remove('over'));
          if (!ghost) { select(id); return; }  // 沒拖動：點選
          ghost.remove();
          chip.classList.remove('dragging');
          const over = document.elementFromPoint(ev.clientX, ev.clientY);
          const row = over && over.closest('.match-row');
          if (row) tryPlace(id, Number(row.dataset.id));
        };
        document.addEventListener('pointermove', move);
        document.addEventListener('pointerup', up);
        document.addEventListener('pointercancel', up);
      });
    }

    function finishGroup() {
      const last = gi === groups.length - 1;
      foot.replaceChildren(
        h('div', { class: 'match-done' }, wrongs ? `這組完成，錯 ${wrongs} 次` : '這組全對！'),
        h('button', { class: 'primary', onclick: () => (last ? showEnd() : (gi++, showGroup())) }, last ? '看結果' : '下一組 →'));
    }

    const foot = h('div', { class: 'match-foot' },
      h('span', { class: 'small muted' }, isPhone() ? '拖曳中文卡片，或先點卡片再點英文' : '把中文卡片拖到對應的英文；也可以先點卡片再點英文'));
    root.replaceChildren(
      h('div', { class: 'session-head row' }, status, h('span', { class: 'spacer' }), h('span', { class: 'badge' }, '配對練習・不算進紀錄')),
      h('div', { class: 'panel match-board' }, list, pool, foot));
    drawStatus();
  }

  function showEnd() {
    stopSpeaking();
    const wrong = [...missed.values()];
    root.replaceChildren(h('div', { class: 'panel' },
      h('h2', {}, '配對完成'),
      h('div', { class: 'stats', style: { marginBottom: '14px' } },
        h('div', { class: 'stat' }, h('div', { class: 'num' }, items.length), h('div', { class: 'label' }, '個字')),
        h('div', { class: 'stat' }, h('div', { class: 'num ok-text' }, items.length - wrong.length), h('div', { class: 'label' }, '一次就配對')),
        h('div', { class: 'stat' }, h('div', { class: 'num warn' }, wrong.length), h('div', { class: 'label' }, '配錯過'))),
      wrong.length ? h('div', {},
        h('div', { class: 'small muted', style: { marginBottom: '6px' } }, '配錯過的字（只是練習，沒有改燈號）'),
        h('div', { class: 'chips' }, ...wrong.map(it => h('span', { class: 'chip static' }, lightDot(it.light), it.word, h('span', { class: 'muted small' }, it.zh))))) : null,
      h('div', { class: 'row', style: { marginTop: '16px' } },
        h('span', { class: 'spacer' }),
        h('a', { class: 'btn', href: '#/' }, '回首頁'),
        wrong.length ? h('button', {
          onclick: () => { const again = items.filter(it => missed.has(it.id)); missed.clear(); groups = makeGroups(shuffle(again), size); gi = 0; showGroup(); },
        }, `配錯的 ${wrong.length} 個再練一次`) : null,
        h('button', { class: 'primary', onclick: () => { missed.clear(); groups = makeGroups(shuffle(items), size); gi = 0; showGroup(); } }, '全部再來一次')),
    ));
  }

  if (!items.length) {
    root.replaceChildren(h('div', { class: 'panel empty' }, '這些字沒有中文意思可以配對。'));
  } else {
    showGroup();
  }
  return () => stopSpeaking();
}
