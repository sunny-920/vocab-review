// 設定
import {
  api, h, openModal, toast, rankedVoices, setVoice, currentVoiceName, speak,
  ttsEngine, setTtsEngine, ttsVoice, setTtsVoice,
} from '../util.js';

// ---------- 發音聲音（每台電腦各自記住）----------
const SAMPLE = 'This is how I sound. The results were consistent, reliable, and accurate.';
function voicePanel() {
  const engineSel = h('select', { style: { maxWidth: '360px' } },
    h('option', { value: 'kokoro', selected: ttsEngine() === 'kokoro' }, '自然語音（本機 Kokoro，推薦）'),
    h('option', { value: 'browser', selected: ttsEngine() === 'browser' }, '瀏覽器內建語音'));
  const kokoroSel = h('select', { style: { maxWidth: '360px' } });
  const browserSel = h('select', { style: { maxWidth: '360px' } });
  const kokoroRow = h('label', { class: 'field' }, h('span', {}, '自然語音的聲音'), kokoroSel);
  const browserRow = h('label', { class: 'field' }, h('span', {}, '瀏覽器語音的聲音（自然語音不能用時也會用它）'), browserSel);
  const info = h('div', { class: 'small' });

  api('/tts/status').then(s => {
    const cur = ttsVoice() || s.default;
    kokoroSel.replaceChildren(...s.voices.map(v => h('option', { value: v.id, selected: v.id === cur }, v.label)));
    info.replaceChildren(s.available ? '' : h('span', { class: 'warn' }, '自然語音目前不能用（' + (s.error || '還沒下載模型') + '），會改用瀏覽器語音。'));
  }).catch(() => {});
  const fillBrowser = () => {
    const vs = rankedVoices();
    const cur = currentVoiceName();
    browserSel.replaceChildren(...(vs.length ? vs : [{ name: '', lang: '' }]).map(v =>
      h('option', { value: v.name, selected: v.name === cur }, v.name ? `${v.name}（${v.lang}）` : '找不到英文聲音')));
  };
  fillBrowser();
  if ('speechSynthesis' in window) speechSynthesis.addEventListener('voiceschanged', fillBrowser);
  const showRows = () => kokoroRow.classList.toggle('hidden', engineSel.value !== 'kokoro');
  showRows();

  engineSel.addEventListener('change', () => { setTtsEngine(engineSel.value); showRows(); speak(SAMPLE); });
  kokoroSel.addEventListener('change', () => { setTtsVoice(kokoroSel.value); speak(SAMPLE); });
  browserSel.addEventListener('change', () => { setVoice(browserSel.value); if (engineSel.value === 'browser') speak(SAMPLE); });

  return h('div', { class: 'panel' },
    h('h2', {}, '發音聲音'),
    h('div', { class: 'muted small', style: { marginBottom: '10px' } },
      '自然語音在跑程式的那台電腦產生（只用 CPU 的 2 個執行緒，不佔 GPU），所以 Mac、Windows 聽到的都一樣。',
      '這裡的選擇只存在這台電腦。單字的聲音念過一次就會存起來；文章是即時產生，不會存。'),
    h('div', { class: 'settings-grid' },
      h('label', { class: 'field' }, h('span', {}, '發音方式'), engineSel),
      kokoroRow, browserRow),
    info,
    h('div', { class: 'row', style: { marginTop: '12px' } }, h('span', { class: 'spacer' }),
      h('button', { onclick: () => speak(SAMPLE) }, '🔊 試聽')));
}

// ---------- 分類說明 ----------
function openDescription(c, done) {
  const box = h('textarea', {
    rows: 5, value: c.description || '',
    placeholder: '例如：論文裡通用的學術寫作用字，像是論文結構（abstract、introduction、conclusion）、轉折連接詞（moreover、more specifically）、描述研究的動詞（propose、demonstrate）。不包含特定領域的專業用詞，例如資料庫、神經網路。',
  });
  const save = async () => {
    try {
      await api(`/categories/${c.id}/description`, { method: 'PUT', body: { description: box.value } });
      toast(box.value.trim() ? '已儲存說明' : '已清除說明');
      close();
      done();
    } catch (e) { toast(e.message, 'error'); }
  };
  const close = openModal(h('div', {},
    h('div', { class: 'modal-head' }, h('h2', {}, `「${c.path.replace('/', ' › ')}」的說明`)),
    h('div', { class: 'small muted', style: { marginBottom: '10px' } },
      '選填。寫給 AI 看的，說明這個分類要放什麼字、不放什麼字。新增單字和「✨ AI 分類」時都會參考。留空就只看分類名稱。'),
    box,
    h('div', { class: 'row', style: { marginTop: '12px' } },
      h('span', { class: 'small muted' }, '最多 500 字'),
      h('span', { class: 'spacer' }),
      h('button', { class: 'ghost', onclick: () => close() }, '取消'),
      h('button', { class: 'primary', onclick: save }, '儲存')),
  ));
  box.focus();
}

// ---------- 刪除分類 ----------
async function openDelete(c, cats, done) {
  let pre;
  try { pre = await api(`/categories/${c.id}/delete-preview`); } catch (e) { toast(e.message, 'error'); return; }
  const doomed = new Set(pre.ids);
  const moveSel = h('select', {}, ...cats.filter(x => !doomed.has(x.id)).sort((a, b) => b.system - a.system)
    .map(x => h('option', { value: x.id }, (x.depth ? '　' : '') + x.name + (x.system ? '（預設）' : ''))));
  const body = h('div', {},
    h('div', { class: 'modal-head' }, h('h2', {}, `刪除「${c.path.replace('/', ' › ')}」？`)),
    pre.paths.length > 1 ? h('div', { class: 'small muted', style: { marginBottom: '8px' } },
      `底下的小類也會一起刪除：${pre.paths.slice(1).map(p => p.split('/')[1]).join('、')}`) : null,
    pre.words
      ? h('div', { class: 'delete-info' },
        h('div', {}, `有 ${pre.words} 個字用到這個分類：`),
        h('ul', {},
          h('li', {}, `${pre.keep} 個字還有其他分類 → 只拿掉這個分類`),
          h('li', {}, `${pre.orphan} 個字只有這個分類 → 移到 `, moveSel)))
      : h('div', { class: 'muted' }, '沒有單字用到這個分類。'),
    h('div', { class: 'small muted', style: { margin: '10px 0' } }, '單字本身不會被刪除。'),
    h('div', { class: 'row' }, h('span', { class: 'spacer' }),
      h('button', { class: 'ghost', onclick: () => close() }, '取消'),
      h('button', {
        class: 'danger-solid', onclick: async () => {
          try {
            await api(`/categories/${c.id}` + (pre.orphan ? `?move_to=${moveSel.value}` : ''), { method: 'DELETE' });
            toast(`已刪除分類「${c.name}」`);
            close();
            done();
          } catch (e) { toast(e.message, 'error'); }
        },
      }, '刪除分類')),
  );
  const close = openModal(body);
}

// ---------- AI 分類 ----------
function openClassify(c, done) {
  const title = c.system ? '✨ AI 重新分類「未分類」' : `✨ AI 分類「${c.path.replace('/', ' › ')}」`;
  const status = h('div', { class: 'small muted' }, '準備中…');
  const bar = h('div', { class: 'progress' }, h('div', { style: { width: '0%' } }));
  const list = h('div', { class: 'classify-list' });
  const footer = h('div', { class: 'row', style: { marginTop: '14px' } });
  let alive = true;
  const close = openModal(h('div', {},
    h('div', { class: 'modal-head' }, h('h2', {}, title), h('button', { class: 'ghost', onclick: () => close() }, '關閉')),
    h('div', { class: 'small muted', style: { marginBottom: '10px' } }, c.system
      ? '把只在「未分類」的字放進現有分類（設成主分類）。都不適合的，AI 會建議新分類，勾選套用時才會建立。'
      : '找出屬於這個分類的字。原本已有分類的字會加成「其他分類」，不動原本的主分類；在「未分類」的字會直接設成主分類。'),
    status, bar, list, footer,
  ), { onClose: () => { alive = false; } });

  function showResult(job) {
    const sug = job.suggestions;
    status.textContent = sug.length
      ? `掃描了 ${job.total} 個字，AI 建議 ${sug.length} 個。確認後按「套用」，取消勾選的不會變動。`
      : `掃描了 ${job.total} 個字，沒有找到適合的字。`;
    bar.classList.add('hidden');
    const checks = sug.map(() => h('input', { type: 'checkbox', checked: true }));
    list.replaceChildren(...sug.map((s, i) => h('label', { class: 'classify-row' },
      checks[i],
      h('span', { class: 'w' }, s.word),
      h('span', { class: 'muted zh' }, s.zh),
      h('span', { class: 'spacer' }),
      h('span', { class: 'muted small' }, s.current ? `${s.current} →` : ''),
      h('span', { class: 'badge accent' }, s.path.replace('/', ' › ')),
      s.is_new ? h('span', { class: 'badge yellow' }, '新分類') : null,
      h('span', { class: 'badge' }, s.role === 'primary' ? '主分類' : '其他分類'),
    )));
    if (!sug.length) { footer.replaceChildren(h('span', { class: 'spacer' }), h('button', { onclick: () => close() }, '關閉')); return; }
    const applyBtn = h('button', {
      class: 'primary', onclick: async () => {
        const items = sug.filter((_, i) => checks[i].checked).map(s => ({ word_id: s.word_id, path: s.path }));
        if (!items.length) { toast('沒有勾選任何字', 'error'); return; }
        applyBtn.disabled = true;
        try {
          const r = await api('/classify/apply', { method: 'POST', body: { items } });
          toast(`已套用 ${r.applied} 個字`);
          close();
          done();
        } catch (e) { toast(e.message, 'error'); applyBtn.disabled = false; }
      },
    }, '套用勾選的字');
    footer.replaceChildren(
      h('button', { class: 'small ghost', onclick: () => checks.forEach(x => { x.checked = true; }) }, '全選'),
      h('button', { class: 'small ghost', onclick: () => checks.forEach(x => { x.checked = false; }) }, '全不選'),
      h('span', { class: 'spacer' }),
      applyBtn);
  }

  (async () => {
    let jobId;
    try { ({ job_id: jobId } = await api(`/categories/${c.id}/classify`, { method: 'POST' })); }
    catch (e) { status.textContent = '無法開始：' + e.message; return; }
    while (alive) {
      let job;
      try { job = await api('/classify/' + jobId); } catch (e) { status.textContent = e.message; return; }
      if (job.status === 'running') {
        status.replaceChildren(h('span', { class: 'spinner' }), ` AI 掃描中… ${job.done} / ${job.total} 個字`);
        bar.firstChild.style.width = (job.total ? job.done / job.total * 100 : 0) + '%';
        await new Promise(r => setTimeout(r, 800));
        continue;
      }
      if (job.status === 'error') { status.textContent = '發生錯誤：' + job.error; return; }
      showResult(job);
      return;
    }
  })();
}

export async function render(el) {
  const { settings: s, models, paths } = await api('/settings');
  let cats = await api('/categories');

  const modelList = models.includes(s.model) ? models : [s.model, ...models];
  const model = h('select', {}, ...modelList.map(m => {
    const o = h('option', { value: m }, m);
    if (m === s.model) o.selected = true;
    return o;
  }));
  const num = (v, min, max) => h('input', { type: 'number', value: v, min, max });
  const dailyLimit = num(s.daily_limit, 5, 500);
  const dayStart = num(s.day_start_hour, 0, 12);
  const backupKeep = num(s.backup_keep, 1, 60);

  const save = async () => {
    try {
      await api('/settings', {
        method: 'PUT',
        body: { model: model.value, daily_limit: dailyLimit.value, day_start_hour: dayStart.value, backup_keep: backupKeep.value },
      });
      toast('設定已儲存');
    } catch (e) { toast(e.message, 'error'); }
  };

  // ---- 分類管理 ----
  const tree = h('div', { class: 'cat-tree' });
  const parentSel = h('select');
  const newName = h('input', { placeholder: '新分類名稱' });

  const reloadCats = async () => { cats = await api('/categories'); drawCats(); };

  function drawCats() {
    tree.replaceChildren(...cats.map(c => h('div', { class: 'item' + (c.depth ? ' child' : '') + (c.system ? ' system' : '') },
      h('div', { class: 'cat-name' },
        h('div', { class: 'row', style: { gap: '8px' } },
          h('span', {}, c.name),
          c.system ? h('span', { class: 'badge' }, '系統') : null,
          h('span', { class: 'n' }, c.count ? `${c.count} 個字` : '')),
        c.description ? h('div', { class: 'cat-desc', title: c.description }, c.description) : null),
      h('span', { class: 'spacer' }),
      c.system
        ? h('button', { class: 'small', disabled: !c.count, title: '把未分類的字放進現有分類；都不適合的，AI 會建議新分類',
          onclick: () => openClassify(c, reloadCats) }, '✨ AI 重新分類')
        : [
          h('button', { class: 'small', title: '讓 AI 掃描所有單字，找出屬於這個分類的字',
            onclick: () => openClassify(c, reloadCats) }, '✨ AI 分類'),
          h('button', { class: 'link small', title: '寫給 AI 看的分類說明（選填）',
            onclick: () => openDescription(c, reloadCats) }, c.description ? '說明 ✎' : '說明'),
          h('button', {
            class: 'link small', onclick: async () => {
              const name = prompt('新的名稱', c.name);
              if (!name || name === c.name) return;
              try {
                await api('/categories/' + c.id, { method: 'PUT', body: { name } });
                await reloadCats();
              } catch (e) { toast(e.message, 'error'); }
            },
          }, '改名'),
          h('button', { class: 'link small danger-link', onclick: () => openDelete(c, cats, reloadCats) }, '刪除'),
        ],
    )));
    parentSel.replaceChildren(h('option', { value: '' }, '（新的大類）'),
      ...cats.filter(c => !c.depth && !c.system).map(c => h('option', { value: c.name }, `放在「${c.name}」底下`)));
  }
  drawCats();

  const addCat = async () => {
    const name = newName.value.trim().replace(/\//g, '／');
    if (!name) return;
    try {
      await api('/categories', { method: 'POST', body: { path: parentSel.value ? `${parentSel.value}/${name}` : name } });
      newName.value = '';
      cats = await api('/categories'); drawCats();
      toast('已新增分類');
    } catch (e) { toast(e.message, 'error'); }
  };

  el.append(
    h('h1', {}, '設定'),
    h('div', { class: 'panel' },
      h('h2', {}, '一般'),
      h('div', { class: 'settings-grid' },
        h('label', { class: 'field' }, h('span', {}, 'AI 模型（Ollama）'), model),
        h('label', { class: 'field' }, h('span', {}, '每日複習一輪幾個字'), dailyLimit),
        h('label', { class: 'field' }, h('span', {}, '幾點換日（0～12，預設凌晨 4 點）'), dayStart),
        h('label', { class: 'field' }, h('span', {}, '保留幾份每日備份'), backupKeep),
      ),
      h('div', { class: 'row', style: { marginTop: '14px' } }, h('span', { class: 'spacer' }), h('button', { class: 'primary', onclick: save }, '儲存設定')),
    ),
    voicePanel(),
    h('div', { class: 'panel' },
      h('h2', {}, '分類'),
      h('div', { class: 'muted small', style: { marginBottom: '10px' } }, 'AI 會優先從這些分類裡挑。'),
      tree,
      h('div', { class: 'row', style: { marginTop: '12px' } },
        h('div', { style: { width: '200px' } }, parentSel),
        h('div', { style: { flex: 1, minWidth: '160px' } }, newName),
        h('button', { onclick: addCat }, '新增分類')),
    ),
    h('div', { class: 'panel' },
      h('h2', {}, '資料位置'),
      h('div', { class: 'small' },
        h('div', {}, '資料庫：', h('span', { class: 'path' }, paths.database)),
        h('div', {}, '備份：', h('span', { class: 'path' }, paths.backups)),
        h('div', { class: 'muted', style: { marginTop: '6px' } }, '想看最原始的資料表，可以用免費的 DB Browser for SQLite 開啟資料庫檔案（建議先關閉本程式）。'),
      ),
    ),
  );
}
