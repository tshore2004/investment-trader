import { state, resampleBars, PORTFOLIO_SYMBOL } from './state.js';
import { createChartWidget } from './chart.js';
import { createOrdersWidget } from './orders.js';
import { createHoldingsWidget } from './holdings.js';
import { createCompareWidget } from './compare.js';

export { PORTFOLIO_SYMBOL };

// Metrics widget factory — per-instance symbol summary tiles.
function createMetricsWidget(container, config) {
  container.innerHTML = `
    <div class="right-panel" style="height:100%;display:flex;flex-direction:column">
      <div class="panel-header">Metrics — ${config.symbol}</div>
      <div class="metrics" style="flex:1 1 auto">
        <div class="metric"><div class="metric-label">Last Price</div><div class="metric-value w-m-close">—</div></div>
        <div class="metric"><div class="metric-label">Volume</div><div class="metric-value w-m-vol">—</div></div>
        <div class="metric"><div class="metric-label">Position (USD)</div><div class="metric-value w-m-pos">—</div></div>
        <div class="metric"><div class="metric-label">Bar Count</div><div class="metric-value w-m-bars">0</div></div>
      </div>
    </div>`;

  function render() {
    const rawBars = state.bars[config.symbol] || [];
    const displayed = resampleBars(rawBars, 60);
    const last = rawBars[rawBars.length - 1];
    if (last) {
      const cl = last.close;
      const prev = rawBars.length > 1 ? rawBars[rawBars.length - 2].close : cl;
      const pct = ((cl - prev) / prev * 100).toFixed(2);
      const color = cl >= prev ? 'green' : 'red';
      const closeEl = container.querySelector('.w-m-close');
      closeEl.textContent = `$${cl.toFixed(2)} (${pct}%)`;
      closeEl.className = `metric-value w-m-close ${color}`;
      container.querySelector('.w-m-vol').textContent = last.volume.toLocaleString();
      container.querySelector('.w-m-bars').textContent = displayed.length;
    }
    const pos = state.positions[config.symbol];
    container.querySelector('.w-m-pos').textContent =
      pos !== undefined ? `$${pos.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : '—';
  }

  (async () => {
    try { await fetch('/api/subscribe/' + encodeURIComponent(config.symbol), { method: 'POST' }); } catch (e) { /* best effort */ }
    render();
  })();

  return {
    update(sym) { if (sym === config.symbol) render(); },
    render,
    getConfig() { return { symbol: config.symbol }; },
    destroy() {},
  };
}

export const WIDGET_TYPES = {
  chart:    { label: 'Chart',         defaultSize: { w: 6, h: 6 }, needsSymbol: true,  allowsPortfolio: true },
  metrics:  { label: 'Metrics',       defaultSize: { w: 4, h: 3 }, needsSymbol: true,  allowsPortfolio: false },
  orders:   { label: 'Trade History', defaultSize: { w: 4, h: 3 }, needsSymbol: true,  allowsPortfolio: false },
  holdings: { label: 'Holdings',      defaultSize: { w: 6, h: 3 }, needsSymbol: false, allowsPortfolio: false },
  compare:  { label: 'Compare',       defaultSize: { w: 8, h: 4 }, needsSymbol: true,  allowsPortfolio: false },
};

// id -> { id, type, config, handle }
export const instances = new Map();

let _idCounter = 0;
export function newWidgetId(type) {
  _idCounter += 1;
  return `${type}-${Date.now().toString(36)}-${_idCounter}`;
}

// Renders a widget of `type` into `container`, registers it, and returns the
// instance record. `hooks.onConfigChange` is forwarded to factories that
// mutate their own config (chart timeframe/indicators, compare symbols).
export function createWidget(id, type, config, container, hooks = {}) {
  let handle;
  if (type === 'chart') handle = createChartWidget(container, config, hooks);
  else if (type === 'metrics') handle = createMetricsWidget(container, config);
  else if (type === 'orders') handle = createOrdersWidget(container, config);
  else if (type === 'holdings') handle = createHoldingsWidget(container);
  else if (type === 'compare') handle = createCompareWidget(container, config, hooks);
  else throw new Error(`unknown widget type: ${type}`);

  const instance = { id, type, config, handle };
  instances.set(id, instance);
  return instance;
}

export function destroyWidget(id) {
  const instance = instances.get(id);
  if (!instance) return;
  try { instance.handle.destroy(); } catch (e) { console.error(e); }
  instances.delete(id);
}

export function allInstances() {
  return Array.from(instances.values());
}

// --- WS message fan-out -----------------------------------------------

export function dispatchBar(sym) {
  for (const inst of instances.values()) {
    if (inst.handle.update) inst.handle.update(sym);
  }
}

export function dispatchPortfolioValue(point) {
  for (const inst of instances.values()) {
    if (inst.type === 'chart' && inst.config.symbol === PORTFOLIO_SYMBOL) {
      inst.handle.appendPortfolioPoint(point);
    }
  }
}

export function dispatchOrder(order) {
  for (const inst of instances.values()) {
    if (inst.type === 'orders') inst.handle.addOrder(order);
  }
}

export function dispatchHoldings() {
  for (const inst of instances.values()) {
    if (inst.type === 'holdings') inst.handle.render();
  }
}

export function dispatchPosition(sym) {
  for (const inst of instances.values()) {
    if (inst.type === 'metrics' && inst.config.symbol === sym) inst.handle.render();
  }
}
