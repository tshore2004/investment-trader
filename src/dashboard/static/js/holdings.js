import { state } from './state.js';

// Holdings widget factory — portfolio-wide, no per-instance symbol.
export function createHoldingsWidget(container) {
  container.innerHTML = `
    <div class="right-panel" style="height:100%">
      <div class="panel-header">Holdings</div>
      <table>
        <thead>
          <tr>
            <th>Symbol</th><th>Qty</th><th>Avg Cost</th><th>Live Price</th><th>P&amp;L $</th><th>P&amp;L %</th>
          </tr>
        </thead>
        <tbody class="w-holdings-body"></tbody>
      </table>
      <div class="w-no-holdings" style="color:#a39c8f;padding:12px;text-align:center;font-size:12px">No holdings</div>
    </div>`;

  const tbody = container.querySelector('.w-holdings-body');
  const none = container.querySelector('.w-no-holdings');

  function render() {
    const portfolio = Array.isArray(state.portfolio) ? state.portfolio : [];
    const watchlist = Array.isArray(state.watchlist) ? state.watchlist : [];
    const seen = new Set(portfolio.map(p => p.symbol));
    const placeholders = watchlist
      .filter(sym => !seen.has(sym))
      .map(sym => ({ symbol: sym, qty: 0, avg_cost: null, price: null, unrealized_pnl: null, unrealized_pnl_pct: null }));
    const rows = portfolio.concat(placeholders);

    if (rows.length === 0) { tbody.innerHTML = ''; none.style.display = 'block'; return; }
    none.style.display = 'none';

    tbody.innerHTML = rows.map(r => {
      const isPlaceholder = r.avg_cost === null || r.avg_cost === undefined;
      const hasPnl = typeof r.unrealized_pnl === 'number';
      const pnlClass = hasPnl ? (r.unrealized_pnl >= 0 ? 'pnl-green' : 'pnl-red') : '';
      const pnlStr = hasPnl ? `$${r.unrealized_pnl.toFixed(2)}` : '—';
      const pnlPctStr = typeof r.unrealized_pnl_pct === 'number' ? `${r.unrealized_pnl_pct.toFixed(2)}%` : '—';
      const avgCostStr = typeof r.avg_cost === 'number' ? `$${r.avg_cost.toFixed(2)}` : '—';
      const priceStr = typeof r.price === 'number' ? `$${r.price.toFixed(2)}` : '—';
      return `<tr${isPlaceholder ? ' class="placeholder-row"' : ''}>
        <td>${r.symbol}</td>
        <td>${r.qty ?? 0}</td>
        <td>${avgCostStr}</td>
        <td>${priceStr}</td>
        <td class="${pnlClass}">${pnlStr}</td>
        <td class="${pnlClass}">${pnlPctStr}</td>
      </tr>`;
    }).join('');
  }

  render();

  return {
    render,
    getConfig() { return {}; },
    destroy() {},
  };
}
