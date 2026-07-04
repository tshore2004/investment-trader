// Live training visualizer: shows loss curves and predicted-vs-actual return
// as a background /api/ml/train run progresses. The loss-curve x-axis uses
// epoch number (not wall-clock time) fed into lightweight-charts' numeric
// time field, so tick labels are not meaningful dates — only the shape of
// the curve matters here.
export function createMlWidget(container, config) {
  config.epochs = config.epochs || 50;
  config.lr = config.lr || 0.001;
  config.hiddenSize = config.hiddenSize || 64;

  container.innerHTML = `
    <div class="panel">
      <div class="panel-header" style="flex-wrap:wrap;gap:6px">
        <span class="w-chart-label">NN Predictor — ${config.symbol}</span>
        <div style="display:flex;gap:8px;align-items:center;font-size:11px">
          <label>Epochs <input class="w-ml-epochs" type="number" min="1" value="${config.epochs}" style="width:56px" /></label>
          <label>LR <input class="w-ml-lr" type="number" step="0.0001" value="${config.lr}" style="width:70px" /></label>
          <label>Hidden <input class="w-ml-hidden" type="number" min="2" value="${config.hiddenSize}" style="width:56px" /></label>
          <button class="w-ml-start">Start</button>
          <button class="w-ml-stop">Stop</button>
        </div>
        <span class="w-ml-status" style="color:#a39c8f;font-size:11px;width:100%"></span>
      </div>
      <div style="display:flex;flex:1 1 auto;min-height:0">
        <div class="w-ml-loss" style="width:50%;height:100%"></div>
        <div class="w-ml-pred" style="width:50%;height:100%"></div>
      </div>
    </div>`;

  const statusEl = container.querySelector('.w-ml-status');
  const lossEl = container.querySelector('.w-ml-loss');
  const predEl = container.querySelector('.w-ml-pred');

  const chartOpts = {
    layout: { background: { color: '#0a0a0a' }, textColor: '#a39c8f' },
    grid: { vertLines: { color: '#1a1a1a' }, horzLines: { color: '#1a1a1a' } },
  };

  const lossChart = LightweightCharts.createChart(lossEl, {
    ...chartOpts, width: lossEl.offsetWidth || 200, height: lossEl.offsetHeight || 200,
  });
  const trainLossSeries = lossChart.addLineSeries({ color: '#F5C518', lineWidth: 2 });
  const valLossSeries = lossChart.addLineSeries({ color: '#f85149', lineWidth: 2 });

  const predChart = LightweightCharts.createChart(predEl, {
    ...chartOpts, width: predEl.offsetWidth || 200, height: predEl.offsetHeight || 200,
  });
  const actualSeries = predChart.addLineSeries({ color: '#3fb950', lineWidth: 2 });
  const predictedSeries = predChart.addLineSeries({ color: '#79c0ff', lineWidth: 2 });

  let lossPoints = [];

  function handleProgress(msg) {
    if (msg.symbol !== config.symbol) return;

    if (msg.status === 'error') {
      statusEl.textContent = `error: ${msg.detail}`;
      return;
    }
    if (msg.epoch === undefined) return;

    lossPoints.push({ time: msg.epoch, trainLoss: msg.train_loss, valLoss: msg.val_loss });
    trainLossSeries.setData(lossPoints.map(p => ({ time: p.time, value: p.trainLoss })));
    valLossSeries.setData(lossPoints.map(p => ({ time: p.time, value: p.valLoss })));

    const preds = msg.sample_preds || [];
    actualSeries.setData(preds.map((p, i) => ({ time: i + 1, value: p.actual })));
    predictedSeries.setData(preds.map((p, i) => ({ time: i + 1, value: p.predicted })));

    statusEl.textContent =
      `epoch ${msg.epoch}/${msg.total_epochs} — train loss ${msg.train_loss.toFixed(6)}, val loss ${msg.val_loss.toFixed(6)}`;
    if (msg.epoch >= msg.total_epochs) statusEl.textContent += ' — done';
  }

  container.querySelector('.w-ml-start').onclick = async () => {
    config.epochs = parseInt(container.querySelector('.w-ml-epochs').value, 10) || config.epochs;
    config.lr = parseFloat(container.querySelector('.w-ml-lr').value) || config.lr;
    config.hiddenSize = parseInt(container.querySelector('.w-ml-hidden').value, 10) || config.hiddenSize;
    lossPoints = [];
    trainLossSeries.setData([]);
    valLossSeries.setData([]);
    statusEl.textContent = 'starting...';
    try {
      const r = await fetch('/api/ml/train', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: config.symbol, epochs: config.epochs, lr: config.lr, hidden_size: config.hiddenSize,
        }),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        statusEl.textContent = `could not start: ${body.status || r.status}`;
      }
    } catch (e) {
      statusEl.textContent = 'failed to start';
    }
  };

  container.querySelector('.w-ml-stop').onclick = async () => {
    try {
      await fetch('/api/ml/stop', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: config.symbol }),
      });
      statusEl.textContent = 'stopping...';
    } catch (e) { /* best effort */ }
  };

  const resizeObserver = new ResizeObserver(() => {
    if (lossEl.offsetWidth > 0) lossChart.applyOptions({ width: lossEl.offsetWidth, height: lossEl.offsetHeight });
    if (predEl.offsetWidth > 0) predChart.applyOptions({ width: predEl.offsetWidth, height: predEl.offsetHeight });
  });
  resizeObserver.observe(lossEl);
  resizeObserver.observe(predEl);

  return {
    handleProgress,
    getConfig() {
      return { symbol: config.symbol, epochs: config.epochs, lr: config.lr, hiddenSize: config.hiddenSize };
    },
    destroy() {
      resizeObserver.disconnect();
      lossChart.remove();
      predChart.remove();
    },
  };
}
