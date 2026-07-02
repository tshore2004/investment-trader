import { state } from './state.js';
import { connect } from './ws.js';
import { chart, renderChart, switchSymbol, ensureTab } from './chart.js';
import { setMode } from './compare.js';
import { initLayout } from './layout.js';
import './holdings.js';

document.getElementById('sym-btn').onclick = async () => {
  const sym = document.getElementById('sym-input').value.toUpperCase().trim();
  const status = document.getElementById('search-status');
  if (!sym) return;
  status.textContent = 'subscribing...';
  try {
    const r = await fetch('/api/subscribe/' + sym, { method: 'POST' });
    const j = await r.json();
    if (j.status === 'subscribed' || j.status === 'already_subscribed') {
      if (!state.bars[sym]) state.bars[sym] = [];
      ensureTab(sym);
      switchSymbol(sym);
      status.textContent = j.status === 'subscribed' ? sym + ' subscribed — loading data...' : sym + ' already active';
    } else {
      status.textContent = j.detail || 'error';
    }
  } catch(e) { status.textContent = 'request failed'; }
  setTimeout(() => document.getElementById('search-status').textContent = '', 3000);
};
document.getElementById('sym-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('sym-btn').click();
});

document.getElementById('tf-toggle').onclick = (e) => {
  e.stopPropagation();
  document.getElementById('tf-menu').classList.toggle('hidden');
};
document.querySelectorAll('#tf-menu .tf-option').forEach(btn => {
  btn.onclick = () => {
    document.querySelectorAll('#tf-menu .tf-option').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    state.timeframeSeconds = parseInt(btn.dataset.tf, 10);
    document.getElementById('tf-current').textContent = btn.textContent;
    document.getElementById('chart-label').textContent = `${btn.textContent} Bars (delayed)`;
    document.getElementById('tf-menu').classList.add('hidden');
    if (state.mode === 'compare') {
      window.__renderCompareMetrics();
    } else {
      renderChart();
      // Switching granularity swaps in a differently-sized dataset; without
      // this the chart keeps its old zoom/pan window (sized for the previous
      // timeframe's bar count) and the new bars render squeezed into a
      // corner of a mostly-empty chart.
      chart.timeScale().fitContent();
    }
  };
});
document.addEventListener('click', (e) => {
  const dd = document.getElementById('tf-dropdown');
  if (dd && !dd.contains(e.target)) document.getElementById('tf-menu').classList.add('hidden');
});

document.querySelectorAll('#mode-toggle .sym-tab').forEach(btn => {
  btn.onclick = () => setMode(btn.dataset.mode);
});

connect();
initLayout();
