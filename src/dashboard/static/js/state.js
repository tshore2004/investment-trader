// Reserved sentinel for the Chart widget's portfolio mode — not a valid
// ticker, so it can never collide with a real subscription.
export const PORTFOLIO_SYMBOL = '__PORTFOLIO__';

export const state = {
  bars: {}, positions: {}, portfolio: [], watchlist: [],
  tradingEnabled: false,
};

export const COMPARE_PALETTE = ['#F5C518', '#79c0ff', '#3fb950', '#f85149', '#c586ff', '#ff9d5c', '#5ce1e6', '#eaeaea'];

// Aggregates raw 1-minute bars into `seconds`-wide candles (open=first, high=max,
// low=min, close=last, volume=sum). Bars must already be in ascending time order.
export function resampleBars(bars, seconds) {
  const buckets = new Map();
  for (const b of bars) {
    const bucketTime = Math.floor(b.time / seconds) * seconds;
    const agg = buckets.get(bucketTime);
    if (!agg) {
      buckets.set(bucketTime, { time: bucketTime, open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume });
    } else {
      agg.high = Math.max(agg.high, b.high);
      agg.low = Math.min(agg.low, b.low);
      agg.close = b.close;
      agg.volume += b.volume;
    }
  }
  return Array.from(buckets.values()).sort((a, b) => a.time - b.time);
}
