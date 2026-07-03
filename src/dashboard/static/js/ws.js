import { state } from './state.js';
import {
  dispatchBar, dispatchPortfolioValue, dispatchOrder,
  dispatchHoldings, dispatchPosition, dispatchMlTraining,
} from './widgets.js';

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

function handleMessage(msg) {
  if (msg.type === 'snapshot') {
    state.positions = msg.positions || {};
    state.portfolio = msg.portfolio || [];
    state.watchlist = msg.watchlist || [];
    state.tradingEnabled = !!msg.trading_enabled;
    for (const [sym, bars] of Object.entries(msg.bars || {})) {
      // In-memory server bars are the freshest; widgets backfill deeper
      // history from /api/bars themselves.
      const merged = new Map();
      for (const b of (state.bars[sym] || [])) merged.set(b.time, b);
      for (const b of bars) merged.set(b.time, b);
      state.bars[sym] = Array.from(merged.values()).sort((a, b) => a.time - b.time);
      dispatchBar(sym);
    }
    dispatchHoldings();
    setModeBadge(state.tradingEnabled);
  } else if (msg.type === 'bar') {
    const sym = msg.symbol;
    if (!state.bars[sym]) state.bars[sym] = [];
    const last = state.bars[sym][state.bars[sym].length - 1];
    if (last && last.time === msg.data.time) {
      state.bars[sym][state.bars[sym].length - 1] = msg.data;
    } else {
      state.bars[sym].push(msg.data);
    }
    const tsEl = document.getElementById('last-ts');
    if (tsEl) tsEl.textContent = new Date(msg.data.time * 1000).toLocaleTimeString();
    dispatchBar(sym);
  } else if (msg.type === 'order') {
    dispatchOrder(msg.data);
  } else if (msg.type === 'position') {
    state.positions[msg.symbol] = msg.value;
    dispatchPosition(msg.symbol);
  } else if (msg.type === 'portfolio') {
    state.portfolio = msg.data || [];
    dispatchHoldings();
  } else if (msg.type === 'portfolio_value') {
    dispatchPortfolioValue({
      time: Math.floor(new Date(msg.timestamp).getTime() / 1000),
      value: msg.value,
    });
  } else if (msg.type === 'ml_training') {
    dispatchMlTraining(msg);
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
