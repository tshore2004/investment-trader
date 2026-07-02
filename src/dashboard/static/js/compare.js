import { state, resampleBars, colorForCompareSymbol } from './state.js';
import { candleSeries, volSeries, ensureTab, renderChart } from './chart.js';

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

export function renderCompareMetrics() {
  const panel = document.getElementById('compare-panel');
  if (!panel) return;

  const symbols = [];
  if (state.activeSymbol) symbols.push(state.activeSymbol);
  for (const s of state.compareSymbols) if (!symbols.includes(s)) symbols.push(s);

  const activeRaw = state.activeSymbol ? (state.bars[state.activeSymbol] || []) : [];

  const rowsHtml = symbols.map(sym => {
    const raw = state.bars[sym] || [];
    const displayed = resampleBars(raw, state.timeframeSeconds);
    const last = raw[raw.length - 1];
    const prev = raw.length > 1 ? raw[raw.length - 2].close : null;
    const changePct = (last && prev) ? ((last.close - prev) / prev * 100) : null;
    const volRatio = volVsAvg(displayed);
    const closes = displayed.map(b => b.close);
    const volatility = stdev(returnsFromCloses(closes));
    let corr = sym === state.activeSymbol ? 1 : null;
    if (corr === null && state.activeSymbol) {
      const [a, b] = alignedReturnPairs(raw, activeRaw);
      corr = pearsonCorrelation(a, b);
    }
    const removable = state.compareSymbols.includes(sym);
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
    <div id="compare-legend" style="display:flex">
      ${state.compareSymbols.map(sym => `
        <span class="legend-chip" data-sym="${sym}">
          <span class="legend-dot" style="background:${colorForCompareSymbol(sym)}"></span>${sym}
          <span class="legend-remove" data-remove="${sym}">&times;</span>
        </span>`).join('')}
      <input id="compare-add-input" class="legend-add-input" placeholder="+ Add symbol" maxlength="8" />
    </div>
    <table id="compare-table">
      <thead><tr><th>Symbol</th><th>Last</th><th>Chg %</th><th>Vol/Avg</th><th>Volatility (stdev ret)</th><th>Corr</th><th>Trend</th></tr></thead>
      <tbody>${rowsHtml || '<tr class="placeholder-row"><td colspan="7">No symbols in compare view</td></tr>'}</tbody>
    </table>`;

  panel.querySelectorAll('.legend-remove').forEach(x => {
    x.onclick = () => removeCompareSymbol(x.dataset.remove);
  });
  const input = document.getElementById('compare-add-input');
  if (input) {
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        const sym = input.value.toUpperCase().trim();
        if (sym) addCompareSymbol(sym);
        input.value = '';
      }
    });
  }
}

export async function addCompareSymbol(sym) {
  sym = sym.toUpperCase().trim();
  if (!sym || state.compareSymbols.includes(sym)) return;
  state.compareSymbols.push(sym);
  colorForCompareSymbol(sym);
  ensureTab(sym);
  try {
    await fetch('/api/subscribe/' + sym, { method: 'POST' });
  } catch (e) {
    // best effort — table shows "—" until data arrives
  }
  if (!state.bars[sym] || state.bars[sym].length === 0) {
    try {
      const r = await fetch('/api/bars/' + encodeURIComponent(sym));
      const rows = await r.json();
      state.bars[sym] = rows.map(row => ({
        time: Math.floor(new Date(row.timestamp).getTime() / 1000),
        open: row.open, high: row.high, low: row.low, close: row.close, volume: row.volume,
      }));
    } catch (e) {
      // keep whatever we have
    }
  }
  renderCompareMetrics();
}

export function removeCompareSymbol(sym) {
  state.compareSymbols = state.compareSymbols.filter(s => s !== sym);
  renderCompareMetrics();
}

export function setMode(mode) {
  state.mode = mode;
  const isCompare = mode === 'compare';
  document.querySelectorAll('#mode-toggle .sym-tab').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
  document.getElementById('symbol-tabs').style.display = isCompare ? 'none' : 'flex';
  document.getElementById('compare-panel').style.display = isCompare ? 'block' : 'none';
  document.getElementById('chart').style.display = isCompare ? 'none' : 'block';
  candleSeries.applyOptions({ visible: !isCompare });
  volSeries.applyOptions({ visible: !isCompare });
  if (isCompare) {
    if (state.compareSymbols.length === 0 && state.activeSymbol) {
      addCompareSymbol(state.activeSymbol);
    } else {
      renderCompareMetrics();
    }
  } else {
    renderChart();
  }
}

window.__renderCompareMetrics = renderCompareMetrics;
