// 單字詳細資料視窗（可編輯、刪除、改燈號和進度）
import { api, h, openModal, toast } from './util.js';
import { renderDetail, statusControl, applyStatus, statusToast } from './detail.js';
import { createEditor } from './editor.js';

/**
 * opts.onChange: 單字有改動時呼叫，參數是更新後的單字（刪除時是 null）
 * opts.edit:     直接打開編輯畫面
 */
export async function openWordModal(id, { onChange, edit = false } = {}) {
  let w = await api('/words/' + id);
  const body = h('div', {});
  const head = h('div', { class: 'modal-head' });
  const close = openModal(h('div', {}, head, body));
  const changed = () => onChange && onChange(w);

  // 燈號和進度：按了立刻生效（不用按儲存）
  async function setStatus(kind, value, redraw) {
    try {
      w = await applyStatus(id, kind, value);
      toast(statusToast(w, kind, value));
      changed();
      redraw();
    } catch (e) { toast(e.message, 'error'); }
  }

  const showDetail = () => {
    head.replaceChildren(
      h('h2', {}, '單字'),
      h('button', { onclick: showEditor }, '編輯'),
      h('button', { class: 'danger', onclick: remove }, '刪除'),
      h('button', { class: 'ghost', onclick: close }, '關閉'),
    );
    body.replaceChildren(renderDetail(w, {
      onOpenWord: other => { close(); openWordModal(other, { onChange }); },
      onStatus: (kind, value) => setStatus(kind, value, showDetail),
    }));
  };

  const showEditor = async () => {
    const cats = await api('/categories');
    const ed = createEditor(w, cats);
    const statusBox = h('div', { style: { marginBottom: '14px' } });
    const drawStatus = () => statusBox.replaceChildren(
      ...(w.status === 'active' ? [statusControl(w, (kind, value) => setStatus(kind, value, drawStatus))] : []));
    drawStatus();
    const save = async () => {
      try {
        w = await api('/words/' + id, { method: 'PUT', body: ed.getValue() });
        toast(`已儲存 ${w.word}`);
        changed();
        showDetail();
      } catch (e) { toast(e.message, 'error'); }
    };
    head.replaceChildren(
      h('h2', {}, `編輯：${w.word}`),
      h('button', { class: 'primary', onclick: save }, '儲存'),
      h('button', { class: 'ghost', onclick: showDetail }, '取消'),
    );
    body.replaceChildren(statusBox, ed.el);
  };

  const remove = async () => {
    if (!confirm(`確定要刪除「${w.word}」嗎？刪除後無法復原（每日備份裡還找得到）。`)) return;
    await api('/words/' + id, { method: 'DELETE' });
    toast(`已刪除 ${w.word}`);
    close();
    w = null;
    changed();
  };

  if (edit) showEditor(); else showDetail();
}
