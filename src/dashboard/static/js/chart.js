import { state, resampleBars, PORTFOLIO_SYMBOL } from './state.js';

// Below 1h, bars within a day are the common case — time-of-day alone is
// unambiguous. At 1h and above, a chart routinely spans multiple days, so a
// time-only label ("08:00 PM") repeats for every day shown and looks broken;
// switch to a date (plus time for 1h/4h, where same-day bars still need it).
function formatTickTime(time, timeframeSeconds) {
  const d = new Date(time * 1000);
  if (timeframeSeconds >= 86400) {
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
  }
  if (timeframeSeconds >= 3600) {
    return d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  }
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export const SUPPORTED_INDICATORS = ['SMA20', 'EMA9', 'VWAP', 'RSI14'];
const INDICATOR_COLORS = { SMA20: '#F5C518', EMA9: '#79c0ff', VWAP: '#5ce1e6', RSI14: '#c586ff' };

export function computeSMA(displayed, period) {
  const out = [];
  for (let i = period - 1; i < displayed.length; i++) {
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) sum += displayed[j].close;
    out.push({ time: displayed[i].time, value: sum / period });
  }
  return out;
}

export function computeEMA(displayed, period) {
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
export function computeVWAP(displayed) {
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

export function computeRSI(displayed, period) {
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
}

const TIMEFRAMES = [
  { label: '1m', seconds: 60 }, { label: '5m', seconds: 300 }, { label: '10m', seconds: 600 },
  { label: '30m', seconds: 1800 }, { label: '1h', seconds: 3600 }, { label: '4h', seconds: 14400 },
  { label: '1d', seconds: 86400 },
];

function tfLabel(seconds) {
  const tf = TIMEFRAMES.find(t => t.seconds === seconds);
  return tf ? tf.label : `${seconds}s`;
}

// Creates one independent chart widget instance inside `container`.
// config: { symbol, timeframeSeconds?, indicators? }  symbol may be PORTFOLIO_SYMBOL.
// hooks: { onConfigChange() } — called whenever timeframe/indicators change so
// the layout can persist the new config.
export function createChartWidget(container, config, hooks = {}) {
  const isPortfolio = config.symbol === PORTFOLIO_SYMBOL;
  config.timeframeSeconds = config.timeframeSeconds || 60;
  config.indicators = Array.isArray(config.indicators) ? config.indicators : [];

  const title = isPortfolio ? 'My Portfolio' : config.symbol;
  container.innerHTML = `
    <div class="panel">
      <div class="panel-header">
        <div style="display:flex;gap:12px;align-items:center">
          <div class="tf-dropdown w-tf-dropdown" ${isPortfolio ? 'hidden' : ''}>
            <button class="tf-toggle-btn w-tf-toggle">&#9776; <span class="w-tf-current">${tfLabel(config.timeframeSeconds)}</span></button>
            <div class="tf-menu hidden w-tf-menu">
              ${TIMEFRAMES.map(t => `<button class="tf-option${t.seconds === config.timeframeSeconds ? ' active' : ''}" data-tf="${t.seconds}">${t.label}</button>`).join('')}
            </div>
          </div>
          <span class="w-chart-label">${title}${isPortfolio ? ' — value' : ' (delayed)'}</span>
          <div class="tf-dropdown w-ind-dropdown" ${isPortfolio ? 'hidden' : ''}>
            <button class="tf-toggle-btn w-ind-toggle">&#8801; Indicators</button>
            <div class="tf-menu hidden w-ind-menu">
              ${SUPPORTED_INDICATORS.map(name => `<button class="tf-option${config.indicators.includes(name) ? ' active' : ''}" data-ind="${name}">${name}</button>`).join('')}
            </div>
          </div>
        </div>
        <span class="w-chart-status" style="color:#a39c8f;font-size:11px"></span>
      </div>
      <div class="w-chart-el" style="width:100%;flex:1 1 auto;min-height:0"></div>
    </div>`;

  const chartEl = container.querySelector('.w-chart-el');
  const statusEl = container.querySelector('.w-chart-status');
  const chart = LightweightCharts.createChart(chartEl, {
    layout: { background: { color: '#0a0a0a' }, textColor: '#a39c8f' },
    grid: { vertLines: { color: '#1a1a1a' }, horzLines: { color: '#1a1a1a' } },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    rightPriceScale: { borderColor: '#262626' },
    timeScale: {
      borderColor: '#262626', timeVisible: true, secondsVisible: true,
      tickMarkFormatter: (time) => formatTickTime(time, config.timeframeSeconds),
    },
    localization: { timeFormatter: (time) => formatTickTime(time, config.timeframeSeconds) },
    width: chartEl.offsetWidth || 300,
    height: chartEl.offsetHeight || 200,
  });

  let candleSeries = null, volSeries = null, lineSeries = null;
  const indicatorSeries = {};
  let portfolioPoints = [];

  if (isPortfolio) {
    lineSeries = chart.addLineSeries({ color: '#F5C518', lineWidth: 2 });
  } else {
    candleSeries = chart.addCandlestickSeries({
      upColor: '#3fb950', downColor: '#f85149',
      borderUpColor: '#3fb950', borderDownColor: '#f85149',
      wickUpColor: '#3fb950', wickDownColor: '#f85149',
    });
    volSeries = chart.addHistogramSeries({
      priceFormat: { type: 'volume' }, priceScaleId: 'vol', color: '#F5C51833',
    });
    chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
  }

  function updateIndicators(displayed) {
    for (const name of config.indicators) {
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

  function ensureIndicatorSeries(name) {
    if (indicatorSeries[name]) return;
    if (name === 'RSI14') {
      // v4.1.3 has no stacked-pane API — fall back to a secondary price scale,
      // the same technique used for the volume histogram.
      indicatorSeries[name] = chart.addLineSeries({ color: INDICATOR_COLORS.RSI14, lineWidth: 1, priceScaleId: 'rsi' });
      chart.priceScale('rsi').applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });
    } else {
      indicatorSeries[name] = chart.addLineSeries({ color: INDICATOR_COLORS[name], lineWidth: 1 });
    }
  }

  function render() {
    if (isPortfolio) {
      // Empty portfolio renders a flat 0-line rather than a blank chart.
      const points = portfolioPoints.length ? portfolioPoints
        : [{ time: Math.floor(Date.now() / 1000), value: 0 }];
      lineSeries.setData(points);
      const last = portfolioPoints[portfolioPoints.length - 1];
      statusEl.textContent = last ? `$${last.value.toLocaleString(undefined, { maximumFractionDigits: 2 })}` : '$0.00';
      return;
    }
    const raw = state.bars[config.symbol] || [];
    if (raw.length === 0) { statusEl.textContent = 'waiting for data...'; return; }
    statusEl.textContent = '';
    const displayed = resampleBars(raw, config.timeframeSeconds);
    candleSeries.setData(displayed);
    volSeries.setData(displayed.map(b => ({ time: b.time, value: b.volume, color: b.close >= b.open ? '#3fb95044' : '#f8514944' })));
    updateIndicators(displayed);
  }

  function appendPortfolioPoint(point) {
    const last = portfolioPoints[portfolioPoints.length - 1];
    if (last && last.time === point.time) {
      portfolioPoints[portfolioPoints.length - 1] = point;
    } else if (!last || point.time > last.time) {
      portfolioPoints.push(point);
    }
    render();
  }

  async function backfill() {
    if (isPortfolio) {
      try {
        const r = await fetch('/api/portfolio/history');
        const rows = await r.json();
        portfolioPoints = rows.map(row => ({
          time: Math.floor(new Date(row.timestamp).getTime() / 1000),
          value: row.value,
        })).sort((a, b) => a.time - b.time)
          // dedupe identical timestamps (lightweight-charts rejects them)
          .filter((p, i, arr) => i === 0 || p.time > arr[i - 1].time);
      } catch (e) {
        portfolioPoints = [];
      }
    } else {
      statusEl.textContent = 'loading...';
      try { await fetch('/api/subscribe/' + encodeURIComponent(config.symbol), { method: 'POST' }); } catch (e) { /* best effort */ }
      await loadBarHistory(config.symbol);
    }
    render();
    chart.timeScale().fitContent();
  }

  // --- header controls -------------------------------------------------
  const tfToggle = container.querySelector('.w-tf-toggle');
  const tfMenu = container.querySelector('.w-tf-menu');
  const indToggle = container.querySelector('.w-ind-toggle');
  const indMenu = container.querySelector('.w-ind-menu');

  if (!isPortfolio) {
    tfToggle.onclick = (e) => { e.stopPropagation(); tfMenu.classList.toggle('hidden'); indMenu.classList.add('hidden'); };
    indToggle.onclick = (e) => { e.stopPropagation(); indMenu.classList.toggle('hidden'); tfMenu.classList.add('hidden'); };
    tfMenu.querySelectorAll('.tf-option').forEach(btn => {
      btn.onclick = () => {
        tfMenu.querySelectorAll('.tf-option').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        config.timeframeSeconds = parseInt(btn.dataset.tf, 10);
        container.querySelector('.w-tf-current').textContent = btn.textContent;
        tfMenu.classList.add('hidden');
        render();
        // A differently-sized dataset keeps the old zoom window otherwise.
        chart.timeScale().fitContent();
        if (hooks.onConfigChange) hooks.onConfigChange();
      };
    });
    indMenu.querySelectorAll('.tf-option').forEach(btn => {
      btn.onclick = () => {
        const name = btn.dataset.ind;
        const enabled = !btn.classList.contains('active');
        btn.classList.toggle('active', enabled);
        if (enabled) {
          if (!config.indicators.includes(name)) config.indicators.push(name);
          ensureIndicatorSeries(name);
        } else {
          config.indicators = config.indicators.filter(n => n !== name);
          const series = indicatorSeries[name];
          if (series) { chart.removeSeries(series); delete indicatorSeries[name]; }
        }
        render();
        if (hooks.onConfigChange) hooks.onConfigChange();
      };
    });
    for (const name of config.indicators) ensureIndicatorSeries(name);
  }

  const closeMenus = (e) => {
    if (isPortfolio) return;
    if (!container.contains(e.target)) { tfMenu.classList.add('hidden'); indMenu.classList.add('hidden'); }
  };
  document.addEventListener('click', closeMenus);

  const resizeObserver = new ResizeObserver(() => {
    if (chartEl.offsetWidth > 0 && chartEl.offsetHeight > 0) {
      chart.applyOptions({ width: chartEl.offsetWidth, height: chartEl.offsetHeight });
    }
  });
  resizeObserver.observe(chartEl);

  backfill();

  return {
    update(sym) { if (!isPortfolio && sym === config.symbol) render(); },
    appendPortfolioPoint,
    render,
    getConfig() { return { symbol: config.symbol, timeframeSeconds: config.timeframeSeconds, indicators: [...config.indicators] }; },
    destroy() {
      resizeObserver.disconnect();
      document.removeEventListener('click', closeMenus);
      chart.remove();
    },
  };
}
