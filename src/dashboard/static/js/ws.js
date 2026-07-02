import { state } from './state.js';

function handleMessage(msg) {
  if (msg.type === 'snapshot') {
    state.positions = msg.positions || {};
    state.portfolio = msg.portfolio || [];
    state.watchlist = msg.watchlist || [];
    state.tradingEnabled = !!msg.trading_enabled;
    for (const [sym, bars] of Object.entries(msg.bars || {})) {
      state.bars[sym] = bars;
      window.__ensureTab(sym);
    }
    if (state.activeSymbol) window.__switchSymbol(state.activeSymbol);
    window.__renderHoldings();
    window.__setModeBadge(state.tradingEnabled);
  } else if (msg.type === 'bar') {
    const sym = msg.symbol;
    if (!state.bars[sym]) state.bars[sym] = [];
    const last = state.bars[sym][state.bars[sym].length - 1];
    if (last && last.time === msg.data.time) {
      state.bars[sym][state.bars[sym].length - 1] = msg.data;
    } else {
      state.bars[sym].push(msg.data);
    }
    window.__ensureTab(sym);
    if (state.mode === 'chart' && state.activeSymbol === sym) {
      window.__renderChart(sym);
    } else if (state.mode === 'compare') {
      window.__renderCompareMetrics();
    }
  } else if (msg.type === 'order') {
    if (msg.data.symbol === state.activeSymbol) {
      state.orders.push(msg.data);
      window.__renderOrders();
    }
  } else if (msg.type === 'position') {
    state.positions[msg.symbol] = msg.value;
    if (state.activeSymbol === msg.symbol) window.__updateMetrics(msg.symbol);
  } else if (msg.type === 'portfolio') {
    state.portfolio = msg.data || [];
    window.__renderHoldings();
  }
}

export function connect() {
  const badge = document.getElementById('conn-badge');
  const ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onopen = () => { badge.textContent = 'LIVE'; badge.className = 'badge live'; };
  ws.onclose = () => { badge.textContent = 'DISCONNECTED'; badge.className = 'badge disconnected'; setTimeout(connect, 3000); };
  ws.onerror = () => ws.close();
  ws.onmessage = e => { try { handleMessage(JSON.parse(e.data)); } catch(err) { console.error(err); } };
}
