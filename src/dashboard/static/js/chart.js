import { state, resampleBars } from './state.js';
import { loadOrderHistory } from './orders.js';

const chartEl = document.getElementById('chart');
export const chart = LightweightCharts.createChart(chartEl, {
  layout: { background: { color: '#0a0a0a' }, textColor: '#a39c8f' },
  grid: { vertLines: { color: '#1a1a1a' }, horzLines: { color: '#1a1a1a' } },
  crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
  rightPriceScale: { borderColor: '#262626' },
  timeScale: {
    borderColor: '#262626',
    timeVisible: true,
    secondsVisible: true,
    tickMarkFormatter: (time) => new Date(time * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
  },
  localization: {
    timeFormatter: (time) => new Date(time * 1000).toLocaleTimeString(),
  },
  width: chartEl.offsetWidth,
  height: chartEl.offsetHeight,
});

export const candleSeries = chart.addCandlestickSeries({
  upColor: '#3fb950', downColor: '#f85149',
  borderUpColor: '#3fb950', borderDownColor: '#f85149',
  wickUpColor: '#3fb950', wickDownColor: '#f85149',
});

export const volSeries = chart.addHistogramSeries({
  priceFormat: { type: 'volume' },
  priceScaleId: 'vol',
  color: '#F5C51833',
});
chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });

export function renderChart(sym) {
  sym = sym || state.activeSymbol;
  if (!sym) return;
  const raw = state.bars[sym] || [];
  const displayed = resampleBars(raw, state.timeframeSeconds);
  candleSeries.setData(displayed);
  volSeries.setData(displayed.map(b => ({ time: b.time, value: b.volume, color: b.close >= b.open ? '#3fb95044' : '#f8514944' })));
  updateMetrics(sym, raw, displayed);
}

export function updateMetrics(sym, rawBars, displayedBars) {
  rawBars = rawBars || state.bars[sym] || [];
  displayedBars = displayedBars || resampleBars(rawBars, state.timeframeSeconds);
  const last = rawBars[rawBars.length - 1];
  if (last) {
    const cl = last.close;
    const prev = rawBars.length > 1 ? rawBars[rawBars.length - 2].close : cl;
    const pct = ((cl - prev) / prev * 100).toFixed(2);
    const color = cl >= prev ? 'green' : 'red';
    document.getElementById('m-close').textContent = `$${cl.toFixed(2)} (${pct}%)`;
    document.getElementById('m-close').className = `metric-value ${color}`;
    document.getElementById('m-vol').textContent = last.volume.toLocaleString();
    document.getElementById('m-bars').textContent = displayedBars.length;
    document.getElementById('last-ts').textContent = new Date(last.time * 1000).toLocaleTimeString();
  }
  const pos = state.positions[sym];
  document.getElementById('m-pos').textContent = pos !== undefined ? `$${pos.toLocaleString(undefined, {maximumFractionDigits: 0})}` : '—';
}

export async function loadBarHistory(sym) {
  try {
    const r = await fetch('/api/bars/' + encodeURIComponent(sym));
    const rows = await r.json();
    const fetched = rows.map(row => ({
      time: Math.floor(new Date(row.timestamp).getTime() / 1000),
      open: row.open, high: row.high, low: row.low, close: row.close, volume: row.volume,
    }));
    const merged = new Map();
    for (const b of fetched) merged.set(b.time, b);
    for (const b of (state.bars[sym] || [])) merged.set(b.time, b);
    state.bars[sym] = Array.from(merged.values()).sort((a, b) => a.time - b.time);
  } catch (e) {
    // keep whatever bars we already have in memory
  }
  if (state.activeSymbol === sym) renderChart(sym);
}

export function switchSymbol(sym) {
  state.activeSymbol = sym;
  document.querySelectorAll('#symbol-tabs .sym-tab').forEach(t => t.classList.toggle('active', t.dataset.sym === sym));
  renderChart(sym);
  loadOrderHistory(sym);
  loadBarHistory(sym);
}

export function ensureTab(sym) {
  const tabs = document.getElementById('symbol-tabs');
  if (!tabs.querySelector(`[data-sym="${sym}"]`)) {
    const btn = document.createElement('button');
    btn.className = 'sym-tab';
    btn.dataset.sym = sym;
    btn.textContent = sym;
    btn.onclick = () => switchSymbol(sym);
    tabs.appendChild(btn);
  }
  if (!state.activeSymbol) switchSymbol(sym);
}

export function setModeBadge(enabled) {
  const el = document.getElementById('mode-badge');
  if (enabled) {
    el.textContent = 'LIVE PAPER TRADING';
    el.className = 'badge live-trading';
  } else {
    el.textContent = 'DRY RUN';
    el.className = 'badge dryrun';
  }
}

window.__renderChart = renderChart;
window.__updateMetrics = updateMetrics;
window.__ensureTab = ensureTab;
window.__switchSymbol = switchSymbol;
window.__setModeBadge = setModeBadge;

window.addEventListener('resize', () => {
  chart.applyOptions({ width: chartEl.offsetWidth, height: chartEl.offsetHeight });
});
