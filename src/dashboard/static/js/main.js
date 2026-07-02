import { state, colorForCompareSymbol, resampleBars } from './state.js';
import { connect } from './ws.js';
import { chart, candleSeries, volSeries, renderChart, switchSymbol, ensureTab } from './chart.js';

const lineSeriesBySymbol = {};

function renderCompare() {
  for (const sym of state.compareSymbols) {
    const raw = state.bars[sym] || [];
    const displayed = resampleBars(raw, state.timeframeSeconds);
    const series = lineSeriesBySymbol[sym];
    if (!series || displayed.length === 0) continue;
    const base = displayed[0].close;
    series.setData(displayed.map(b => ({ time: b.time, value: base ? (b.close - base) / base * 100 : 0 })));
  }
}

function renderLegend() {
  const el = document.getElementById('compare-legend');
  el.innerHTML = state.compareSymbols.map(sym => `
    <span class="legend-chip" data-sym="${sym}">
      <span class="legend-dot" style="background:${state.compareColors[sym]}"></span>${sym}
      <span class="legend-remove" data-remove="${sym}">&times;</span>
    </span>`).join('') + `<input id="compare-add-input" class="legend-add-input" placeholder="+ Add symbol" maxlength="8" />`;

  el.querySelectorAll('.legend-remove').forEach(x => {
    x.onclick = () => removeCompareSymbol(x.dataset.remove);
  });
  const input = document.getElementById('compare-add-input');
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      const sym = input.value.toUpperCase().trim();
      if (sym) addCompareSymbol(sym);
      input.value = '';
    }
  });
}

async function addCompareSymbol(sym) {
  sym = sym.toUpperCase().trim();
  if (!sym || state.compareSymbols.includes(sym)) return;
  state.compareSymbols.push(sym);
  colorForCompareSymbol(sym);
  ensureTab(sym);
  try {
    await fetch('/api/subscribe/' + sym, { method: 'POST' });
  } catch (e) {
    // best effort — chart will just stay flat until data arrives
  }
  lineSeriesBySymbol[sym] = chart.addLineSeries({
    color: state.compareColors[sym], lineWidth: 2, priceFormat: { type: 'percent' },
  });
  renderLegend();
  renderCompare();
}

function removeCompareSymbol(sym) {
  state.compareSymbols = state.compareSymbols.filter(s => s !== sym);
  const series = lineSeriesBySymbol[sym];
  if (series) { chart.removeSeries(series); delete lineSeriesBySymbol[sym]; }
  renderLegend();
}

function setMode(mode) {
  state.mode = mode;
  const isCompare = mode === 'compare';
  document.querySelectorAll('#mode-toggle .sym-tab').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
  document.getElementById('compare-legend').style.display = isCompare ? 'flex' : 'none';
  document.getElementById('symbol-tabs').style.display = isCompare ? 'none' : 'flex';
  candleSeries.applyOptions({ visible: !isCompare });
  volSeries.applyOptions({ visible: !isCompare });
  if (isCompare) {
    renderLegend();
    if (state.compareSymbols.length === 0 && state.activeSymbol) {
      addCompareSymbol(state.activeSymbol);
    } else {
      renderCompare();
    }
  } else {
    renderChart();
  }
}

document.getElementById('sym-btn').onclick = async () => {
  const sym = document.getElementById('sym-input').value.toUpperCase().trim();
  const status = document.getElementById('search-status');
  if (!sym) return;
  status.textContent = 'subscribing...';
  try {
    const r = await fetch('/api/subscribe/' + sym, { method: 'POST' });
    const j = await r.json();
    if (j.status === 'subscribed' || j.status === 'already_subscribed') {
      if (!state.bars[sym]) state.bars[sym] = [];
      ensureTab(sym);
      switchSymbol(sym);
      status.textContent = j.status === 'subscribed' ? sym + ' subscribed — loading data...' : sym + ' already active';
    } else {
      status.textContent = j.detail || 'error';
    }
  } catch(e) { status.textContent = 'request failed'; }
  setTimeout(() => document.getElementById('search-status').textContent = '', 3000);
};
document.getElementById('sym-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('sym-btn').click();
});

document.getElementById('tf-toggle').onclick = (e) => {
  e.stopPropagation();
  document.getElementById('tf-menu').classList.toggle('hidden');
};
document.querySelectorAll('#tf-menu .tf-option').forEach(btn => {
  btn.onclick = () => {
    document.querySelectorAll('#tf-menu .tf-option').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    state.timeframeSeconds = parseInt(btn.dataset.tf, 10);
    document.getElementById('tf-current').textContent = btn.textContent;
    document.getElementById('chart-label').textContent = `${btn.textContent} Bars (delayed)`;
    document.getElementById('tf-menu').classList.add('hidden');
    if (state.mode === 'compare') renderCompare(); else renderChart();
  };
});
document.addEventListener('click', (e) => {
  const dd = document.getElementById('tf-dropdown');
  if (dd && !dd.contains(e.target)) document.getElementById('tf-menu').classList.add('hidden');
});

document.querySelectorAll('#mode-toggle .sym-tab').forEach(btn => {
  btn.onclick = () => setMode(btn.dataset.mode);
});

connect();
