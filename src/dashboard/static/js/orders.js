import { state } from './state.js';

export function renderOrders() {
  const tbody = document.getElementById('orders-body');
  const none = document.getElementById('no-orders');
  const orders = state.orders || [];
  if (orders.length === 0) { tbody.innerHTML = ''; none.style.display = 'block'; return; }
  none.style.display = 'none';
  tbody.innerHTML = orders.slice().reverse().map(o => {
    const rawTs = o.submitted_at || o.timestamp;
    const ts = rawTs ? new Date(rawTs).toLocaleString() : '—';
    return `
    <tr>
      <td>${ts}</td>
      <td class="side-${(o.side || '').toLowerCase()}">${o.side}</td>
      <td>${o.quantity}</td>
      <td class="status-${(o.status || '').toLowerCase()}">${o.status}</td>
    </tr>`;
  }).join('');
}

export async function loadOrderHistory(sym) {
  document.getElementById('orders-header-label').textContent = `Trade History — ${sym}`;
  try {
    const r = await fetch('/api/orders/' + encodeURIComponent(sym));
    state.orders = await r.json();
  } catch (e) {
    state.orders = [];
  }
  renderOrders();
}

window.__renderOrders = renderOrders;
