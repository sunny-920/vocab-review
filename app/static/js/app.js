// 頁面切換
import { api, closeAllModals, isMuted, setMuted, toast } from './util.js';
import * as home from './pages/home.js';
import * as add from './pages/add.js';
import * as cards from './pages/cards.js';
import * as library from './pages/library.js';
import * as settings from './pages/settings.js';
import * as review from './pages/review.js';
import * as free from './pages/free.js';
import * as stats from './pages/stats.js';
import * as articles from './pages/articles.js';
import * as article from './pages/article.js';
import * as phrases from './pages/phrases.js';

const routes = { '': home, add, review, free, cards, library, articles, article, phrases, stats, settings };
const view = document.getElementById('view');
let cleanup = null;

// 手機的「更多」選單
const moreSheet = document.getElementById('more-sheet');
document.getElementById('tab-more').addEventListener('click', () => moreSheet.classList.toggle('hidden'));
moreSheet.addEventListener('click', e => { if (e.target === moreSheet || e.target.closest('a')) moreSheet.classList.add('hidden'); });

async function route() {
  const name = location.hash.replace(/^#\/?/, '').split('?')[0];
  const page = routes[name] || home;
  closeAllModals();
  if (cleanup) { try { cleanup(); } catch { /* ignore */ } cleanup = null; }
  document.querySelectorAll('#nav a').forEach(a => {
    const target = a.getAttribute('href').replace(/^#\/?/, '');
    a.classList.toggle('active', target === name || (target === 'articles' && (name === 'article' || name === 'phrases')));
  });
  // 手機下方分頁列：不在前四個分頁的頁面算「更多」
  const tabOf = { '': '', review: 'review', articles: 'articles', article: 'articles', cards: 'cards' };
  const tab = name in tabOf ? tabOf[name] : 'more';
  document.querySelectorAll('#tabbar [data-tab]').forEach(a => a.classList.toggle('active', a.dataset.tab === tab));
  moreSheet.classList.add('hidden');
  document.body.dataset.page = name || 'home';
  view.replaceChildren();
  try {
    cleanup = (await page.render(view)) || null;
  } catch (e) {
    view.textContent = '載入失敗：' + e.message;
  }
}

async function refreshStatus() {
  const el = document.getElementById('ai-status');
  try {
    const s = await api('/status');
    el.className = 'ai-status ' + (s.ai.ok ? 'ok' : 'bad');
    el.textContent = s.ai.ok ? `AI：${s.ai.model}` : `AI 無法使用：${s.ai.error}`;
  } catch {
    el.className = 'ai-status bad';
    el.textContent = '程式沒有回應';
  }
}

// 右上角的全站靜音
const muteBtn = document.getElementById('mute-btn');
function drawMute() {
  const m = isMuted();
  muteBtn.textContent = m ? '🔇' : '🔊';
  muteBtn.title = m ? '目前靜音，按一下開聲音' : '按一下全站靜音';
  muteBtn.classList.toggle('on', m);
}
muteBtn.addEventListener('click', () => { setMuted(!isMuted()); drawMute(); toast(isMuted() ? '已靜音' : '已開聲音'); });
window.addEventListener('mutechange', drawMute);
drawMute();

window.addEventListener('hashchange', route);
route();
refreshStatus();
setInterval(refreshStatus, 20000);
