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
  updateIndicators(displayed);
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

export const SUPPORTED_INDICATORS = ['SMA20', 'EMA9', 'VWAP', 'RSI14'];
const activeIndicators = new Set();
const indicatorSeries = {};

function computeSMA(displayed, period) {
  const out = [];
  for (let i = period - 1; i < displayed.length; i++) {
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) sum += displayed[j].close;
    out.push({ time: displayed[i].time, value: sum / period });
  }
  return out;
}

function computeEMA(displayed, period) {
  if (displayed.length < period) return [];
  const k = 2 / (period + 1);
  let seedSum = 0;
  for (let i = 0; i < period; i++) seedSum += displayed[i].close;
  let ema = seedSum / period;
  const out = [{ time: displayed[period - 1].time, value: ema }];
  for (let i = period; i < displayed.length; i++) {
    ema = displayed[i].close * k + ema * (1 - k);
    out.push({ time: displayed[i].time, value: ema });
  }
  return out;
}

// Resets the cumulative price*volume/volume sums whenever the bar's local
// calendar date changes — bars carry no explicit session marker.
function computeVWAP(displayed) {
  const out = [];
  let cumPV = 0, cumVol = 0, lastDateKey = null;
  for (const b of displayed) {
    const d = new Date(b.time * 1000);
    const dateKey = `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
    if (dateKey !== lastDateKey) { cumPV = 0; cumVol = 0; lastDateKey = dateKey; }
    cumPV += b.close * b.volume;
    cumVol += b.volume;
    out.push({ time: b.time, value: cumVol ? cumPV / cumVol : b.close });
  }
  return out;
}

function computeRSI(displayed, period) {
  if (displayed.length <= period) return [];
  const closes = displayed.map(b => b.close);
  let gainSum = 0, lossSum = 0;
  for (let i = 1; i <= period; i++) {
    const diff = closes[i] - closes[i - 1];
    if (diff >= 0) gainSum += diff; else lossSum -= diff;
  }
  let avgGain = gainSum / period, avgLoss = lossSum / period;
  const out = [{ time: displayed[period].time, value: avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss) }];
  for (let i = period + 1; i < closes.length; i++) {
    const diff = closes[i] - closes[i - 1];
    const gain = diff >= 0 ? diff : 0;
    const loss = diff < 0 ? -diff : 0;
    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;
    out.push({ time: displayed[i].time, value: avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss) });
  }
  return out;
}

function updateIndicators(displayed) {
  for (const name of activeIndicators) {
    const series = indicatorSeries[name];
    if (!series) continue;
    let data;
    if (name === 'SMA20') data = computeSMA(displayed, 20);
    else if (name === 'EMA9') data = computeEMA(displayed, 9);
    else if (name === 'VWAP') data = computeVWAP(displayed);
    else if (name === 'RSI14') data = computeRSI(displayed, 14);
    series.setData(data || []);
  }
}

const INDICATOR_COLORS = { SMA20: '#F5C518', EMA9: '#79c0ff', VWAP: '#5ce1e6', RSI14: '#c586ff' };

export function toggleIndicator(name, enabled) {
  if (enabled) {
    if (indicatorSeries[name]) return;
    activeIndicators.add(name);
    if (name === 'RSI14') {
      // v4.1.3 has no stacked-pane API — fall back to a secondary price scale,
      // the same technique already used for the volume histogram above.
      indicatorSeries[name] = chart.addLineSeries({
        color: INDICATOR_COLORS.RSI14, lineWidth: 1, priceScaleId: 'rsi',
      });
      chart.priceScale('rsi').applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });
    } else {
      indicatorSeries[name] = chart.addLineSeries({ color: INDICATOR_COLORS[name], lineWidth: 1 });
    }
  } else {
    activeIndicators.delete(name);
    const series = indicatorSeries[name];
    if (series) { chart.removeSeries(series); delete indicatorSeries[name]; }
  }
  const raw = state.bars[state.activeSymbol] || [];
  updateIndicators(resampleBars(raw, state.timeframeSeconds));
}

window.__renderChart = renderChart;
window.__updateMetrics = updateMetrics;
window.__ensureTab = ensureTab;
window.__switchSymbol = switchSymbol;
window.__setModeBadge = setModeBadge;

window.addEventListener('resize', () => {
  chart.applyOptions({ width: chartEl.offsetWidth, height: chartEl.offsetHeight });
});

document.getElementById('ind-toggle').onclick = (e) => {
  e.stopPropagation();
  document.getElementById('ind-menu').classList.toggle('hidden');
};
document.querySelectorAll('#ind-menu .tf-option').forEach(btn => {
  btn.onclick = () => {
    const enabled = !btn.classList.contains('active');
    btn.classList.toggle('active', enabled);
    toggleIndicator(btn.dataset.ind, enabled);
  };
});
document.addEventListener('click', (e) => {
  const dd = document.getElementById('ind-dropdown');
  if (dd && !dd.contains(e.target)) document.getElementById('ind-menu').classList.add('hidden');
});
