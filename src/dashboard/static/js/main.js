import { connect } from './ws.js';
import { initLayout, addWidgetInstance, saveWorkspace } from './layout.js';

// Header search: subscribe to a symbol and open a chart widget for it.
document.getElementById('sym-btn').onclick = async () => {
  const sym = document.getElementById('sym-input').value.toUpperCase().trim();
  const status = document.getElementById('search-status');
  if (!sym) return;
  status.textContent = 'subscribing...';
  try {
    const r = await fetch('/api/subscribe/' + encodeURIComponent(sym), { method: 'POST' });
    const j = await r.json();
    if (j.status === 'subscribed' || j.status === 'already_subscribed') {
      addWidgetInstance('chart', { symbol: sym });
      saveWorkspace();
      status.textContent = sym + ' chart added';
      document.getElementById('sym-input').value = '';
    } else {
      status.textContent = j.detail || 'error';
    }
  } catch(e) { status.textContent = 'request failed'; }
  setTimeout(() => document.getElementById('search-status').textContent = '', 3000);
};
document.getElementById('sym-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('sym-btn').click();
});

initLayout();
connect();
