import { chart } from './chart.js';

const STORAGE_KEY = 'hedge-dashboard-layout';

// Only 4 widgets exist (w-chart, w-metrics, w-orders, w-holdings) — the
// compare view toggles inside w-chart's own content (see compare.js's
// setMode), it isn't a separate draggable widget.
const PRESETS = {
  trading: [
    { id: 'w-chart', x: 0, y: 0, w: 8, h: 8 },
    { id: 'w-metrics', x: 8, y: 0, w: 4, h: 3 },
    { id: 'w-orders', x: 8, y: 3, w: 4, h: 3 },
    { id: 'w-holdings', x: 8, y: 6, w: 4, h: 2 },
  ],
  compare: [
    { id: 'w-chart', x: 0, y: 0, w: 8, h: 6 },
    { id: 'w-metrics', x: 0, y: 6, w: 4, h: 2 },
    { id: 'w-orders', x: 4, y: 6, w: 4, h: 2 },
    { id: 'w-holdings', x: 8, y: 0, w: 4, h: 8 },
  ],
  monitor: [
    { id: 'w-metrics', x: 0, y: 0, w: 6, h: 4 },
    { id: 'w-holdings', x: 6, y: 0, w: 6, h: 4 },
    { id: 'w-chart', x: 0, y: 4, w: 8, h: 4 },
    { id: 'w-orders', x: 8, y: 4, w: 4, h: 4 },
  ],
};

let grid = null;

function applyPreset(name) {
  if (!grid) return;
  grid.load(PRESETS[name] || PRESETS.trading);
}

function saveLayout() {
  if (!grid) return;
  localStorage.setItem(STORAGE_KEY, JSON.stringify(grid.save(false)));
}

export function initLayout() {
  grid = GridStack.init({ cellHeight: 60, margin: 4, float: false });

  const saved = localStorage.getItem(STORAGE_KEY);
  let restored = false;
  if (saved) {
    try {
      grid.load(JSON.parse(saved));
      restored = true;
    } catch (e) {
      restored = false;
    }
  }
  if (!restored) applyPreset('trading');

  let debounceTimer;
  grid.on('change', () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(saveLayout, 500);
  });

  grid.on('resizestop', () => {
    const chartEl = document.getElementById('chart');
    if (chartEl) chart.applyOptions({ width: chartEl.offsetWidth, height: chartEl.offsetHeight });
  });

  const presetSelect = document.getElementById('layout-preset');
  if (presetSelect) {
    presetSelect.addEventListener('change', () => {
      applyPreset(presetSelect.value);
      saveLayout();
    });
  }
}
