// Stock screener widget: pick a universe, run a scan, show a sortable ranked table. Mirrors
// ml.js's Start/Stop + WS-progress pattern, but has no per-symbol subscription (needsSymbol: false).
export function createScreenerWidget(container, config) {
  config.universe = config.universe || 'sp500';

  container.innerHTML = `
    <div class="panel">
      <div class="panel-header" style="flex-wrap:wrap;gap:6px">
        <span class="w-chart-label">Screener</span>
        <div style="display:flex;gap:8px;align-items:center;font-size:11px">
          <label>Universe
            <select class="w-scr-universe">
              <option value="sp500">S&amp;P 500</option>
              <option value="broad">Broad Market</option>
            </select>
          </label>
          <button class="w-scr-run">Run</button>
          <button class="w-scr-stop">Stop</button>
        </div>
        <span class="w-scr-status" style="color:#a39c8f;font-size:11px;width:100%"></span>
      </div>
      <div class="w-scr-table-wrap" style="flex:1 1 auto;overflow:auto">
        <table class="w-scr-table" style="width:100%;border-collapse:collapse;font-size:12px">
          <thead>
            <tr>
              <th data-col="symbol">Symbol</th>
              <th data-col="score">Score</th>
              <th data-col="momentum_12m">Mom 12m</th>
              <th data-col="rel_strength_12m">RelStr 12m</th>
              <th data-col="rsi14">RSI14</th>
              <th data-col="rel_volume">RelVol</th>
              <th data-col="volatility">Vol</th>
            </tr>
          </thead>
          <tbody></tbody>
        </table>
      </div>
    </div>`;

  const universeSelect = container.querySelector('.w-scr-universe');
  universeSelect.value = config.universe;
  const statusEl = container.querySelector('.w-scr-status');
  const tbody = container.querySelector('tbody');
  let rows = [];
  let sortCol = 'score';
  let sortAsc = false;

  function render() {
    const sorted = [...rows].sort((a, b) => {
      const av = a[sortCol] ?? 0, bv = b[sortCol] ?? 0;
      if (sortCol === 'symbol') {
        return sortAsc ? String(av).localeCompare(String(bv)) : String(bv).localeCompare(String(av));
      }
      return sortAsc ? av - bv : bv - av;
    });
    tbody.innerHTML = sorted.map(r => `
      <tr>
        <td>${r.symbol}</td>
        <td>${(r.score ?? 0).toFixed(1)}</td>
        <td>${((r.momentum_12m ?? 0) * 100).toFixed(1)}%</td>
        <td>${((r.rel_strength_12m ?? 0) * 100).toFixed(1)}%</td>
        <td>${(r.rsi14 ?? 0).toFixed(0)}</td>
        <td>${(r.rel_volume ?? 0).toFixed(2)}x</td>
        <td>${((r.volatility ?? 0) * 100).toFixed(1)}%</td>
      </tr>`).join('');
  }

  container.querySelectorAll('[data-col]').forEach(th => {
    th.style.cursor = 'pointer';
    th.onclick = () => {
      const col = th.dataset.col;
      sortAsc = sortCol === col ? !sortAsc : false;
      sortCol = col;
      render();
    };
  });

  function handleScreenerResult(msg) {
    if (msg.status === 'progress') {
      statusEl.textContent = `running — ${msg.stage}${msg.detail ? ': ' + msg.detail : ''}`;
    } else if (msg.status === 'done') {
      rows = msg.results || [];
      statusEl.textContent = `done — ${rows.length} symbols`;
      render();
    } else if (msg.status === 'error') {
      statusEl.textContent = `error: ${msg.detail}`;
    }
  }

  container.querySelector('.w-scr-run').onclick = async () => {
    config.universe = universeSelect.value;
    statusEl.textContent = 'starting...';
    try {
      const r = await fetch('/api/screener/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ universe: config.universe }),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        statusEl.textContent = `could not start: ${body.status || r.status}`;
      }
    } catch (e) {
      statusEl.textContent = 'failed to start';
    }
  };

  container.querySelector('.w-scr-stop').onclick = async () => {
    try {
      await fetch('/api/screener/stop', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      statusEl.textContent = 'stopping...';
    } catch (e) { /* best effort */ }
  };

  return {
    handleScreenerResult,
    getConfig() { return { universe: config.universe }; },
    destroy() {},
  };
}
