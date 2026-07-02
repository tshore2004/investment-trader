// Trade History widget factory — one instance per (widget, symbol).
export function createOrdersWidget(container, config) {
  let orders = [];

  container.innerHTML = `
    <div class="right-panel" style="height:100%">
      <div class="panel-header"><span class="w-orders-label">Trade History — ${config.symbol}</span></div>
      <table>
        <thead><tr><th>Time</th><th>Side</th><th>Qty</th><th>Status</th></tr></thead>
        <tbody class="w-orders-body"></tbody>
      </table>
      <div class="w-no-orders" style="color:#a39c8f;padding:20px;text-align:center;font-size:12px">No orders yet</div>
    </div>`;

  const tbody = container.querySelector('.w-orders-body');
  const none = container.querySelector('.w-no-orders');

  function render() {
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

  async function load() {
    try {
      const r = await fetch('/api/orders/' + encodeURIComponent(config.symbol));
      orders = await r.json();
    } catch (e) {
      orders = [];
    }
    render();
  }

  load();

  return {
    addOrder(order) {
      if (order.symbol === config.symbol) { orders.push(order); render(); }
    },
    getConfig() { return { symbol: config.symbol }; },
    destroy() {},
  };
}
