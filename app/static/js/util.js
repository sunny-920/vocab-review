// 共用小工具

// replaceChildren／append／prepend 遇到 null 會在畫面印出「null」：全站統一把 null、undefined、false 濾掉
for (const proto of [Element.prototype, DocumentFragment.prototype]) {
  for (const fn of ['replaceChildren', 'append', 'prepend']) {
    const orig = proto[fn];
    proto[fn] = function (...args) { return orig.apply(this, args.filter(x => x !== null && x !== undefined && x !== false)); };
  }
}

export async function api(path, opts = {}) {
  const init = { method: opts.method || 'GET', headers: {} };
  if (opts.body !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(opts.body);
  }
  const res = await fetch('/api' + path, init);
  let data = null;
  try { data = await res.json(); } catch { /* 沒有內容 */ }
  if (!res.ok) {
    let msg = data && data.detail;
    if (Array.isArray(msg)) msg = msg.map(d => d.msg).join('；');
    throw new Error(msg || `錯誤 ${res.status}`);
  }
  return data;
}

// h('div', {class: 'x', onclick: fn}, child1, 'text', ...)
export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else if (k === 'class') el.className = v;
    else if (k === 'value') el.value = v;
    else if (k === 'checked') el.checked = !!v;
    else if (k === 'html') el.innerHTML = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else el.setAttribute(k, v === true ? '' : v);
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const c of children) {
    if (c === null || c === undefined || c === false) continue;
    if (Array.isArray(c)) append(el, c);
    else el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

export function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

export function toast(msg, type = '') {
  const t = h('div', { class: 'toast ' + type }, msg);
  document.getElementById('toast-root').append(t);
  setTimeout(() => t.remove(), type === 'error' ? 6000 : 3500);
}

const openModals = new Set();

// 換頁時關掉所有彈出視窗（也會停掉視窗裡的輪詢、快捷鍵）
export function closeAllModals() {
  [...openModals].forEach(close => close());
}

// 開彈出視窗，回傳 close()
export function openModal(content, { bare = false, onClose } = {}) {
  const root = document.getElementById('modal-root');
  const box = h('div', { class: 'modal' + (bare ? ' bare' : '') }, content);
  const backdrop = h('div', { class: 'modal-backdrop' }, box);
  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    openModals.delete(close);
    backdrop.remove();
    document.removeEventListener('keydown', onKey, true);
    onClose && onClose();
  };
  const onKey = e => {
    if (e.key === 'Escape' && root.lastElementChild === backdrop) { e.stopPropagation(); close(); }
  };
  backdrop.addEventListener('mousedown', e => { if (e.target === backdrop) close(); });
  document.addEventListener('keydown', onKey, true);
  root.append(backdrop);
  openModals.add(close);
  return close;
}

export const LIGHT_NAMES = { red: '紅燈・不熟', yellow: '黃燈・學習中', green: '綠燈・精熟' };

export function lightDot(light) {
  return h('span', { class: 'light ' + light, title: LIGHT_NAMES[light] || '' });
}

export function progressDots(n, total = 3) {
  const k = Math.min(n, total);
  return h('span', { class: 'progress-dots', title: `不同天答對 ${k}/${total}` }, '●'.repeat(k) + '○'.repeat(total - k));
}

// ---------- 發音 ----------
// Mac 的聲音清單裡有很多搞笑或很機械的聲音（Albert、Bubbles、Zarvox…），照順序挑會挑到它們，所以要評分挑好聽的。
// 每台電腦的聲音不一樣，選的聲音存在這台電腦的瀏覽器裡（設定頁可以換）。
const BAD_VOICES = /Albert|Bad News|Bahh|Bells|Boing|Bubbles|Cellos|Good News|Jester|Organ|Superstar|Trinoids|Whisper|Wobble|Zarvox|Fred|Junior|Kathy|Ralph|Grandma|Grandpa|Eddy|Flo|Reed|Rocko|Sandy|Shelley/i;
const GOOD_VOICES = /Samantha|Alex|Ava|Allison|Susan|Zoe|Tom|Nathan|Evan|Joelle|Noelle|Aria|Jenny|Guy|Zira|David|Mark|Google US English/i;
const lang = v => (v.lang || '').replace('_', '-');
export const englishVoices = () => ('speechSynthesis' in window ? speechSynthesis.getVoices() : [])
  .filter(v => lang(v).startsWith('en'));
function voiceScore(v) {
  let s = 0;
  if (BAD_VOICES.test(v.name)) s -= 100;
  if (lang(v) === 'en-US') s += 20;
  if (/Premium/i.test(v.name)) s += 40;
  if (/Enhanced|Natural|Neural|Online/i.test(v.name)) s += 30;
  if (GOOD_VOICES.test(v.name)) s += 15;
  return s;
}
export const rankedVoices = () => englishVoices().sort((a, b) => voiceScore(b) - voiceScore(a));
let voice = null;
function pickVoice() {
  const vs = englishVoices();
  const saved = storageGet('voice', '');
  return vs.find(v => v.name === saved) || rankedVoices()[0] || null;
}
export function setVoice(name) { storageSet('voice', name); voice = null; }
export const currentVoiceName = () => (voice || pickVoice() || {}).name || '';
if ('speechSynthesis' in window) {
  speechSynthesis.getVoices();
  speechSynthesis.addEventListener('voiceschanged', () => { voice = null; });  // 聲音清單晚一點才載入
}

function browserSpeak(text, opts) {
  if (!('speechSynthesis' in window)) { if (opts.onend) opts.onend({ type: 'error' }); return; }
  const u = new SpeechSynthesisUtterance(text);
  if (!voice) voice = pickVoice();
  if (voice) u.voice = voice;
  u.lang = voice ? voice.lang : 'en-US';
  u.rate = opts.rate || 0.9;
  if (opts.onend) { u.onend = opts.onend; u.onerror = opts.onend; }
  speechSynthesis.speak(u);
}

// ---------- 本機自然語音（Kokoro，在跑程式的那台電腦產生）----------
// 引擎和聲音存在這台電腦的瀏覽器；Kokoro 不能用時自動改回瀏覽器發音。
export const ttsEngine = () => storageGet('tts-engine', 'kokoro');
export function setTtsEngine(v) { storageSet('tts-engine', v); }
export const ttsVoice = () => storageGet('tts-voice', '');
export function setTtsVoice(v) { storageSet('tts-voice', v); }
let kokoroOk = true;          // 伺服器說不能用就改回瀏覽器發音（重新整理會再試）
const player = new Audio();   // 一直用同一個播放器：Safari 要「點過」的播放器才肯自己播
let unlocked = false;
const SILENT = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQAAAAA=';
function unlock() {
  if (unlocked) return;
  unlocked = true;
  player.src = SILENT;
  player.play().catch(() => { unlocked = false; });
}
['pointerdown', 'keydown'].forEach(t => document.addEventListener(t, unlock, { capture: true }));

let current = null;           // 正在念（或正在產生）的那一句：{ onend }
const prefetched = new Map(); // 文章：先產生好的下一句
const ttsKey = (text, opts) => `${opts.kind || 'word'}|${opts.rate || 0.9}|${text}`;
function ttsFetch(text, opts) {
  const speed = ((opts.rate || 0.9) / 0.9).toFixed(2);  // 瀏覽器 0.9 的速度 ≈ Kokoro 1.0
  const q = new URLSearchParams({ text, speed, kind: opts.kind || 'word' });
  if (ttsVoice()) q.set('voice', ttsVoice());
  return fetch('/api/tts?' + q).then(async r => {
    if (!r.ok) { const e = new Error('tts'); e.status = r.status; throw e; }
    return URL.createObjectURL(await r.blob());
  });
}
const useKokoro = () => kokoroOk && ttsEngine() === 'kokoro';
export function prefetchSpeech(text, opts = {}) {
  if (!useKokoro()) return;
  const k = ttsKey(text, opts);
  if (!prefetched.has(k)) prefetched.set(k, ttsFetch(text, opts).catch(() => null));
}

// ---------- 全站靜音（記在這台電腦）----------
export const isMuted = () => storageGet('muted', false);
export function setMuted(v) {
  storageSet('muted', !!v);
  if (v) stopSpeaking();
  window.dispatchEvent(new CustomEvent('mutechange'));
}

// opts: { rate, onend, keep, kind, auto }；keep=true 不打斷正在念的；kind='sentence' 是即時產生、不存檔；
// auto=true 是自動念的（靜音時不提示）
// onend(e)：念完 e.type='end'；被打斷或失敗 e.type='error'
export function speak(text, opts = {}) {
  if (!opts.keep) stopSpeaking();
  if (isMuted()) {  // 全站靜音：自動念的就安靜跳過，自己按的提示一下
    if (!opts.auto) toast('目前靜音中，按右上角的 🔇 可以開聲音');
    if (opts.onend) opts.onend({ type: 'error' });
    return;
  }
  if (!useKokoro()) { browserSpeak(text, opts); return; }
  const me = current = { onend: opts.onend };
  const k = ttsKey(text, opts);
  const p = prefetched.get(k) || ttsFetch(text, opts);
  prefetched.delete(k);
  p.then(url => {
    if (!url) throw new Error('tts');
    if (current !== me) { URL.revokeObjectURL(url); return; }
    const done = type => {
      URL.revokeObjectURL(url);
      if (current !== me) return;
      current = null;
      if (me.onend) me.onend({ type });
    };
    player.onended = () => done('end');
    player.onerror = () => done('error');
    player.src = url;
    player.play().catch(() => done('error'));
  }).catch(e => {
    if (current !== me) return;
    current = null;
    if (e && e.status === 503) kokoroOk = false;  // 模型沒裝好 → 這次開始用瀏覽器發音
    browserSpeak(text, opts);                      // 這一句改用瀏覽器念，不要沒聲音
  });
}
export function stopSpeaking() {
  if ('speechSynthesis' in window) speechSynthesis.cancel();
  for (const p of prefetched.values()) p.then(u => u && URL.revokeObjectURL(u));
  prefetched.clear();
  if (current) {
    const c = current;
    current = null;
    player.pause();
    if (c.onend) c.onend({ type: 'error' });
  }
}

// 拼字比對：用編輯距離對齊，標出你的答案哪裡錯、正確答案哪裡漏
export function spellDiff(given, expected) {
  const a = given, b = expected;
  const n = a.length, m = b.length;
  const d = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = 0; i <= n; i++) d[i][0] = i;
  for (let j = 0; j <= m; j++) d[0][j] = j;
  for (let i = 1; i <= n; i++) {
    for (let j = 1; j <= m; j++) {
      const same = a[i - 1].toLowerCase() === b[j - 1].toLowerCase();
      d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (same ? 0 : 1));
    }
  }
  const mine = [], right = [];
  let i = n, j = m;
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && d[i][j] === d[i - 1][j - 1] + (a[i - 1].toLowerCase() === b[j - 1].toLowerCase() ? 0 : 1)) {
      const ok = a[i - 1].toLowerCase() === b[j - 1].toLowerCase();
      mine.unshift([a[i - 1], ok]); right.unshift([b[j - 1], ok]); i--; j--;
    } else if (i > 0 && d[i][j] === d[i - 1][j] + 1) {
      mine.unshift([a[i - 1], false]); i--;       // 多打的字母
    } else {
      right.unshift([b[j - 1], false]); j--;      // 漏掉的字母
    }
  }
  const render = (parts, cls) => h('span', { class: 'spell' }, ...parts.map(([c, ok]) => ok ? c : h('span', { class: cls }, c)));
  return { mine: render(mine, 'bad'), right: render(right, 'miss') };
}

export function storageGet(key, fallback) {
  try { const v = localStorage.getItem(key); return v === null ? fallback : JSON.parse(v); } catch { return fallback; }
}
export function storageSet(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* 無法儲存就算了 */ }
}

export function isTyping(e) {
  const t = e.target;
  return t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable);
}
