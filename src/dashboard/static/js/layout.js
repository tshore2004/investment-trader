import { state, PORTFOLIO_SYMBOL } from './state.js';
import {
  WIDGET_TYPES, createWidget, destroyWidget, allInstances, newWidgetId,
} from './widgets.js';

const STORAGE_KEY = 'hedge-dashboard-layout';

// Starting templates ("presets" in the header select). Unlike the old fixed
// 4-widget presets these fully replace the current widget set.
function templates(defaultSymbol) {
  return {
    trading: [
      { type: 'chart', config: { symbol: defaultSymbol, timeframeSeconds: 60, indicators: [] }, x: 0, y: 0, w: 8, h: 8 },
      { type: 'metrics', config: { symbol: defaultSymbol }, x: 8, y: 0, w: 4, h: 3 },
      { type: 'orders', config: { symbol: defaultSymbol }, x: 8, y: 3, w: 4, h: 3 },
      { type: 'holdings', config: {}, x: 8, y: 6, w: 4, h: 2 },
    ],
    compare: [
      { type: 'chart', config: { symbol: defaultSymbol, timeframeSeconds: 60, indicators: [] }, x: 0, y: 0, w: 8, h: 6 },
      { type: 'compare', config: { baseSymbol: defaultSymbol, compareSymbols: [] }, x: 0, y: 6, w: 8, h: 3 },
      { type: 'holdings', config: {}, x: 8, y: 0, w: 4, h: 8 },
    ],
    monitor: [
      { type: 'metrics', config: { symbol: defaultSymbol }, x: 0, y: 0, w: 6, h: 4 },
      { type: 'holdings', config: {}, x: 6, y: 0, w: 6, h: 4 },
      { type: 'chart', config: { symbol: PORTFOLIO_SYMBOL }, x: 0, y: 4, w: 8, h: 4 },
      { type: 'orders', config: { symbol: defaultSymbol }, x: 8, y: 4, w: 4, h: 4 },
    ],
  };
}

let grid = null;
let saveTimer = null;

function defaultSymbol() {
  return state.watchlist[0] || 'AAPL';
}

export function saveWorkspace() {
  if (!grid) return;
  const geometry = new Map();
  for (const node of grid.engine.nodes) {
    geometry.set(node.el.getAttribute('gs-id'), { x: node.x, y: node.y, w: node.w, h: node.h });
  }
  const widgets = allInstances().map(inst => ({
    id: inst.id,
    type: inst.type,
    ...inst.handle.getConfig(),
    ...(geometry.get(inst.id) || {}),
  }));
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ widgets }));
}

function scheduleSave() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveWorkspace, 500);
}

// Adds one widget: a GridStack item plus the registry-rendered content.
export function addWidgetInstance(type, config, geo = {}) {
  const spec = WIDGET_TYPES[type];
  if (!spec) return null;
  const id = geo.id || newWidgetId(type);
  const el = grid.addWidget({
    id,
    x: geo.x, y: geo.y,
    w: geo.w || spec.defaultSize.w,
    h: geo.h || spec.defaultSize.h,
  });
  el.setAttribute('gs-id', id);
  const content = el.querySelector('.grid-stack-item-content');
  content.innerHTML = '<div class="w-body" style="height:100%"></div><button class="w-remove" title="Remove widget">&times;</button>';
  const body = content.querySelector('.w-body');
  try {
    createWidget(id, type, config, body, { onConfigChange: scheduleSave });
  } catch (e) {
    console.error('widget create failed', type, e);
    grid.removeWidget(el, true);
    return null;
  }
  content.querySelector('.w-remove').onclick = () => {
    destroyWidget(id);
    grid.removeWidget(el, true);
    saveWorkspace();
  };
  return id;
}

function clearAllWidgets() {
  for (const inst of allInstances()) destroyWidget(inst.id);
  grid.removeAll(true);
}

function applyTemplate(name) {
  clearAllWidgets();
  const tpl = templates(defaultSymbol())[name] || templates(defaultSymbol()).trading;
  for (const item of tpl) {
    addWidgetInstance(item.type, { ...item.config }, { x: item.x, y: item.y, w: item.w, h: item.h });
  }
  saveWorkspace();
}

function restoreWorkspace() {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (!saved) return false;
  let parsed;
  try {
    parsed = JSON.parse(saved);
  } catch (e) {
    return false;
  }
  const widgets = parsed && Array.isArray(parsed.widgets) ? parsed.widgets : null;
  if (!widgets || widgets.length === 0) return false;
  let restoredAny = false;
  for (const w of widgets) {
    if (!WIDGET_TYPES[w.type]) continue;
    const config = {
      symbol: w.symbol,
      timeframeSeconds: w.timeframeSeconds,
      indicators: w.indicators,
      baseSymbol: w.baseSymbol,
      compareSymbols: w.compareSymbols,
      epochs: w.epochs,
      lr: w.lr,
      hiddenSize: w.hiddenSize,
      universe: w.universe,
    };
    if (addWidgetInstance(w.type, config, { id: w.id, x: w.x, y: w.y, w: w.w, h: w.h })) {
      restoredAny = true;
    }
  }
  return restoredAny;
}

// --- Add View menu ------------------------------------------------------

function initAddViewMenu() {
  const btn = document.getElementById('add-view-btn');
  const menu = document.getElementById('add-view-menu');
  if (!btn || !menu) return;

  function buildTypeList() {
    menu.innerHTML = Object.entries(WIDGET_TYPES)
      .map(([type, spec]) => `<button class="tf-option" data-type="${type}">${spec.label}</button>`)
      .join('');
    menu.querySelectorAll('[data-type]').forEach(b => {
      b.onclick = (e) => {
        e.stopPropagation();
        const type = b.dataset.type;
        const spec = WIDGET_TYPES[type];
        if (!spec.needsSymbol) {
          addWidgetInstance(type, {});
          saveWorkspace();
          menu.classList.add('hidden');
          return;
        }
        buildSymbolPrompt(type, spec);
      };
    });
  }

  function buildSymbolPrompt(type, spec) {
    const portfolioOption = spec.allowsPortfolio
      ? '<button class="tf-option" data-portfolio="1">&#9733; My Portfolio</button>' : '';
    menu.innerHTML = `
      ${portfolioOption}
      <div style="padding:7px 10px;display:flex;gap:6px;align-items:center">
        <input class="legend-add-input" id="add-view-symbol" placeholder="Symbol" maxlength="8" style="width:80px" />
      </div>`;
    const input = menu.querySelector('#add-view-symbol');
    input.focus();
    const confirm = (symbol) => {
      const config = type === 'compare'
        ? { baseSymbol: symbol, compareSymbols: [] }
        : { symbol };
      addWidgetInstance(type, config);
      saveWorkspace();
      menu.classList.add('hidden');
    };
    const portfolioBtn = menu.querySelector('[data-portfolio]');
    if (portfolioBtn) portfolioBtn.onclick = (e) => { e.stopPropagation(); confirm(PORTFOLIO_SYMBOL); };
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        const sym = input.value.toUpperCase().trim();
        if (sym) confirm(sym);
      }
    });
    input.addEventListener('click', (e) => e.stopPropagation());
  }

  btn.onclick = (e) => {
    e.stopPropagation();
    if (menu.classList.contains('hidden')) {
      buildTypeList();
      menu.classList.remove('hidden');
    } else {
      menu.classList.add('hidden');
    }
  };
  document.addEventListener('click', (e) => {
    if (!menu.contains(e.target) && e.target !== btn) menu.classList.add('hidden');
  });
}

export function initLayout() {
  grid = GridStack.init({ cellHeight: 60, margin: 4, float: false });

  if (!restoreWorkspace()) applyTemplate('trading');

  grid.on('change', scheduleSave);

  const presetSelect = document.getElementById('layout-preset');
  if (presetSelect) {
    presetSelect.addEventListener('change', () => applyTemplate(presetSelect.value));
  }

  initAddViewMenu();
}
