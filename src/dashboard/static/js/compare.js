import { state, resampleBars, COMPARE_PALETTE } from './state.js';
import { loadBarHistory } from './chart.js';

function stdev(values) {
  const n = values.length;
  if (n < 2) return null;
  const mean = values.reduce((a, b) => a + b, 0) / n;
  const variance = values.reduce((a, b) => a + (b - mean) ** 2, 0) / (n - 1);
  return Math.sqrt(variance);
}

function returnsFromCloses(closes) {
  const out = [];
  for (let i = 1; i < closes.length; i++) {
    if (closes[i - 1]) out.push((closes[i] - closes[i - 1]) / closes[i - 1]);
  }
  return out;
}

// Correlation is computed on raw (unresampled) 1-min bars, inner-joined by
// timestamp — two symbols only correlate over the minutes both have data for.
function alignedReturnPairs(barsA, barsB) {
  const retA = new Map();
  for (let i = 1; i < barsA.length; i++) {
    const prev = barsA[i - 1].close;
    if (prev) retA.set(barsA[i].time, (barsA[i].close - prev) / prev);
  }
  const a = [], b = [];
  for (let i = 1; i < barsB.length; i++) {
    const prev = barsB[i - 1].close;
    if (!prev) continue;
    const t = barsB[i].time;
    if (retA.has(t)) {
      a.push(retA.get(t));
      b.push((barsB[i].close - prev) / prev);
    }
  }
  return [a, b];
}

function pearsonCorrelation(a, b) {
  const n = a.length;
  if (n < 2) return null;
  const meanA = a.reduce((x, y) => x + y, 0) / n;
  const meanB = b.reduce((x, y) => x + y, 0) / n;
  let num = 0, denA = 0, denB = 0;
  for (let i = 0; i < n; i++) {
    const da = a[i] - meanA, db = b[i] - meanB;
    num += da * db;
    denA += da * da;
    denB += db * db;
  }
  if (denA === 0 || denB === 0) return null;
  return num / Math.sqrt(denA * denB);
}

function volVsAvg(displayed) {
  if (displayed.length === 0) return null;
  const last = displayed[displayed.length - 1].volume;
  const avg = displayed.reduce((a, b) => a + b.volume, 0) / displayed.length;
  return avg ? last / avg : null;
}

function sparklineSVG(closes) {
  if (closes.length < 2) return '<span style="color:#6b6b6b">—</span>';
  const w = 80, h = 24;
  const min = Math.min(...closes), max = Math.max(...closes);
  const range = max - min || 1;
  const points = closes.map((c, i) => {
    const x = (i / (closes.length - 1)) * w;
    const y = h - ((c - min) / range) * h;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  const up = closes[closes.length - 1] >= closes[0];
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><polyline points="${points}" fill="none" stroke="${up ? '#3fb950' : '#f85149'}" stroke-width="1.5" /></svg>`;
}

// Compare widget factory. config: { baseSymbol, compareSymbols: [] }
// hooks: { onConfigChange() } for persistence.
export function createCompareWidget(container, config, hooks = {}) {
  config.compareSymbols = Array.isArray(config.compareSymbols) ? config.compareSymbols : [];
  const colors = {};

  function colorFor(sym) {
    if (!colors[sym]) {
      const used = new Set(Object.values(colors));
      colors[sym] = COMPARE_PALETTE.find(c => !used.has(c)) || COMPARE_PALETTE[config.compareSymbols.length % COMPARE_PALETTE.length];
    }
    return colors[sym];
  }

  container.innerHTML = `
    <div class="right-panel" style="height:100%;display:flex;flex-direction:column">
      <div class="panel-header">Compare — ${config.baseSymbol}</div>
      <div class="w-compare-panel" style="overflow:auto;flex:1 1 auto"></div>
    </div>`;
  const panel = container.querySelector('.w-compare-panel');

  function render() {
    const symbols = [config.baseSymbol];
    for (const s of config.compareSymbols) if (!symbols.includes(s)) symbols.push(s);

    const baseRaw = state.bars[config.baseSymbol] || [];

    const rowsHtml = symbols.map(sym => {
      const raw = state.bars[sym] || [];
      const displayed = resampleBars(raw, 60);
      const last = raw[raw.length - 1];
      const prev = raw.length > 1 ? raw[raw.length - 2].close : null;
      const changePct = (last && prev) ? ((last.close - prev) / prev * 100) : null;
      const volRatio = volVsAvg(displayed);
      const closes = displayed.map(b => b.close);
      const volatility = stdev(returnsFromCloses(closes));
      let corr = sym === config.baseSymbol ? 1 : null;
      if (corr === null) {
        const [a, b] = alignedReturnPairs(raw, baseRaw);
        corr = pearsonCorrelation(a, b);
      }
      const removable = config.compareSymbols.includes(sym);
      return `<tr>
        <td>${sym}${removable ? ` <span class="legend-remove" data-remove="${sym}">&times;</span>` : ''}</td>
        <td>${last ? '$' + last.close.toFixed(2) : '—'}</td>
        <td class="${changePct !== null ? (changePct >= 0 ? 'pnl-green' : 'pnl-red') : ''}">${changePct !== null ? changePct.toFixed(2) + '%' : '—'}</td>
        <td>${volRatio !== null ? volRatio.toFixed(2) + 'x' : '—'}</td>
        <td>${volatility !== null ? (volatility * 100).toFixed(3) + '%' : '—'}</td>
        <td>${corr !== null ? corr.toFixed(2) : '—'}</td>
        <td>${sparklineSVG(closes.slice(-30))}</td>
      </tr>`;
    }).join('');

    panel.innerHTML = `
      <div class="w-compare-legend" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:8px 16px;border-bottom:1px solid #262626">
        ${config.compareSymbols.map(sym => `
          <span class="legend-chip" data-sym="${sym}">
            <span class="legend-dot" style="background:${colorFor(sym)}"></span>${sym}
            <span class="legend-remove" data-remove="${sym}">&times;</span>
          </span>`).join('')}
        <input class="legend-add-input w-compare-add" placeholder="+ Add symbol" maxlength="8" />
      </div>
      <table>
        <thead><tr><th>Symbol</th><th>Last</th><th>Chg %</th><th>Vol/Avg</th><th>Volatility (stdev ret)</th><th>Corr</th><th>Trend</th></tr></thead>
        <tbody>${rowsHtml || '<tr class="placeholder-row"><td colspan="7">No symbols in compare view</td></tr>'}</tbody>
      </table>`;

    panel.querySelectorAll('.legend-remove').forEach(x => {
      x.onclick = () => removeSymbol(x.dataset.remove);
    });
    const input = panel.querySelector('.w-compare-add');
    if (input) {
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          const sym = input.value.toUpperCase().trim();
          if (sym) addSymbol(sym);
          input.value = '';
        }
      });
    }
  }

  async function addSymbol(sym) {
    sym = sym.toUpperCase().trim();
    if (!sym || config.compareSymbols.includes(sym)) return;
    config.compareSymbols.push(sym);
    colorFor(sym);
    try {
      await fetch('/api/subscribe/' + encodeURIComponent(sym), { method: 'POST' });
    } catch (e) {
      // best effort — table shows "—" until data arrives
    }
    if (!state.bars[sym] || state.bars[sym].length === 0) {
      await loadBarHistory(sym);
    }
    render();
    if (hooks.onConfigChange) hooks.onConfigChange();
  }

  function removeSymbol(sym) {
    config.compareSymbols = config.compareSymbols.filter(s => s !== sym);
    render();
    if (hooks.onConfigChange) hooks.onConfigChange();
  }

  // Make sure every configured symbol has data on startup.
  (async () => {
    for (const sym of [config.baseSymbol, ...config.compareSymbols]) {
      if (!state.bars[sym] || state.bars[sym].length === 0) {
        try { await fetch('/api/subscribe/' + encodeURIComponent(sym), { method: 'POST' }); } catch (e) { /* best effort */ }
        await loadBarHistory(sym);
      }
    }
    render();
  })();

  return {
    update(sym) {
      if (sym === config.baseSymbol || config.compareSymbols.includes(sym)) render();
    },
    render,
    getConfig() { return { baseSymbol: config.baseSymbol, compareSymbols: [...config.compareSymbols] }; },
    destroy() {},
  };
}
