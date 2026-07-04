# Stock Screener Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Delegation model for this plan (per user instruction):** Tasks 1–6 (module design: universe/metrics/scorer/service, and the dashboard wiring) involve non-obvious numerical/concurrency decisions and should be assigned to a **strong model** (Opus-tier) both to implement and to review. Tasks 7–8 (ticker-list data files, CLI script, JS widget wiring that mirrors `ml.js` almost verbatim) are mechanical/pattern-following and are suitable for a **cheaper model** (Sonnet/Haiku-tier) to implement, still gated by the strong-model code review below. Task 9 is a final full-repo review and must run on the strong model regardless of who wrote the code.
>
> **Review gate:** Every task's code changes get an independent code review (via the `code-review` skill or a dispatched `ecc:python-reviewer` / `ecc:security-reviewer` agent as appropriate) before being marked complete, per the user's explicit request for "code reviews to ensure this gets done correctly." Do not skip the review step even for mechanical tasks — a reviewer catches wrong ticker formatting, off-by-one windows, and unsafe defaults that "obviously correct" code still gets wrong.

**Goal:** Add a quant stock screener that scans the S&P 500 or a broader market universe, scores
each symbol on momentum / relative strength / RSI / volume / volatility, and surfaces a ranked
table via a dashboard widget (background job + WS progress) and a standalone CLI script.

**Architecture:** A new `src/screener/` package: `universe.py` loads bundled ticker lists,
`data.py` batch-fetches + disk-caches OHLCV via yfinance, `metrics.py` computes per-symbol
factors, `scorer.py` percentile-ranks and weights them into a composite score, and `service.py`
orchestrates the pipeline synchronously with progress callbacks. The FastAPI dashboard runs
`run_screen` via `asyncio.to_thread` (mirroring the existing NN-trainer pattern in
`src/dashboard/app.py`) and bridges the worker thread's sync progress callback back into the
event loop with `asyncio.run_coroutine_threadsafe`, broadcasting a new `screener_result` WS
message. `scripts/run_screener.py` calls the same service synchronously for CLI use, following
`scripts/backfill_history.py`'s precedent.

**Tech Stack:** Python 3.11, pandas/numpy, yfinance, FastAPI, existing vanilla-JS ES-module
dashboard (GridStack + lightweight-charts, no bundler).

## Global Constraints

- Python 3.11, mypy `strict` mode, ruff line-length 100, lint rules `E, F, I, UP, B, SIM`.
- All I/O methods in `src/` are `async def`; use `get_logger(__name__)` with kwargs, never
  f-string logs. `src/screener/*.py` (except `service.py`'s async wrapper, which doesn't exist —
  see below) is synchronous by design per the spec (`run_screen` has no internal async).
- Settings via `get_settings()` (`lru_cache`'d) — never instantiate `Settings()` directly. This
  plan does not need new settings; no `.env` changes required.
- pytest `asyncio_mode = "auto"` — async test functions need no `@pytest.mark.asyncio` decorator.
- yfinance calls are mocked in all tests (`monkeypatch.setattr(..., "yf.download", ...)` or
  equivalent) — no live network calls in CI, matching `tests/scripts/test_backfill_history.py`'s
  convention of monkeypatching `yf.Ticker`/`yf.download` at the module level.
- New WS message type: `screener_result`.
- Universe fetch window: ~14 months of **daily** bars (`period="14mo", interval="1d"`) — enough
  for a trailing 12-month momentum window plus warm-up for 20/50-day rolling metrics.
- Cache path: `.cache/screener/{universe}_{YYYY-MM-DD}.parquet` (date = UTC calendar day). A
  cache hit for the current day skips the network entirely; stale (prior-day) caches are ignored,
  not deleted. Add `.cache/` to `.gitignore`.
- Batch chunk size for `yf.download()`: **100 tickers per call** (documented, tunable constant
  `_CHUNK_SIZE` in `data.py`) — small enough to avoid observed Yahoo rate-limiting on broad-market
  scans, large enough to keep call count low for the ~500-symbol S&P 500 universe.
- `_rsi` is **duplicated** (not shared) between `src/ml/features.py` and `src/screener/metrics.py`:
  the two packages have no existing import relationship, the function is 9 lines, and introducing
  a cross-package dependency for a single formula is not worth the coupling. `src/screener/metrics.py`
  carries a comment pointing at `src/ml/features.py`'s `_rsi` as the twin implementation.
- Default composite weights: momentum 30%, relative strength 30%, RSI 15%, relative volume 10%,
  volatility 15% (must sum to 1.0 — enforced by `scorer.score()`, see Task 4).
- Only one screener run may be in flight at a time (subsequent `POST /api/screener/run` calls
  return 409), mirroring `_active_trainers` in `src/dashboard/app.py`.
- Out of scope (per spec): Cramer-pick tracking, 13F consensus, intraday screening, automatic
  order submission from screener results, an automated JS test harness (manual browser pass +
  `node --input-type=module --check` only, per project convention).

---

### Task 1: Universe loader — `src/screener/universe.py`

**Files:**
- Create: `src/screener/__init__.py` (empty)
- Create: `src/screener/data/sp500.txt`
- Create: `src/screener/data/broad_market.txt`
- Create: `src/screener/universe.py`
- Test: `tests/screener/__init__.py` (empty)
- Test: `tests/screener/test_universe.py`

**Interfaces:**
- Produces: `load_universe(name: str) -> list[str]` where `name` is `"sp500"` or `"broad"`.
  Raises `ValueError` for any other name. Returns a deduplicated, uppercased, sorted list of
  ticker strings, non-empty for both valid names. `"broad"` returns the union of `sp500.txt` and
  `broad_market.txt` (deduplicated) — `broad_market.txt` itself holds only the *supplemental*
  tickers not already in the S&P 500 list, so the two files stay non-redundant.

- [ ] **Step 1: Create package/test dirs**

```bash
mkdir -p src/screener/data tests/screener
```

Create `src/screener/__init__.py` and `tests/screener/__init__.py`, both empty.

- [ ] **Step 2: Create `src/screener/data/sp500.txt`**

One ticker per line, uppercase, no header. This is a point-in-time snapshot (per the design spec,
refreshing it is a manual, infrequent maintenance task, not a runtime concern):

```text
A
AAL
AAPL
ABBV
ABNB
ABT
ACGL
ACN
ADBE
ADI
ADM
ADP
ADSK
AEE
AEP
AES
AFL
AIG
AIZ
AJG
AKAM
ALB
ALGN
ALL
ALLE
AMAT
AMCR
AMD
AME
AMGN
AMP
AMT
AMZN
ANET
ANSS
AON
AOS
APA
APD
APH
APTV
ARE
ATO
AVB
AVGO
AVY
AWK
AXP
AZO
BA
BAC
BALL
BAX
BBWI
BBY
BDX
BEN
BF-B
BG
BIIB
BIO
BK
BKNG
BKR
BLK
BMY
BR
BRK-B
BRO
BSX
BWA
BX
BXP
C
CAG
CAH
CARR
CAT
CB
CBOE
CBRE
CCI
CCL
CDNS
CDW
CE
CEG
CF
CFG
CHD
CHRW
CHTR
CI
CINF
CL
CLX
CMA
CMCSA
CME
CMG
CMI
CMS
CNC
CNP
COF
COO
COP
COR
COST
CPB
CPRT
CPT
CRL
CRM
CSCO
CSGP
CSX
CTAS
CTLT
CTRA
CTSH
CTVA
CVS
CVX
CZR
D
DAL
DAY
DD
DE
DECK
DFS
DG
DGX
DHI
DHR
DIS
DLR
DLTR
DOC
DOV
DOW
DPZ
DRI
DTE
DUK
DVA
DVN
DXCM
EA
EBAY
ECL
ED
EFX
EG
EIX
EL
ELV
EMN
EMR
ENPH
EOG
EPAM
EQIX
EQR
EQT
ES
ESS
ETN
ETR
ETSY
EVRG
EW
EXC
EXPD
EXPE
EXR
F
FANG
FAST
FCX
FDS
FDX
FE
FFIV
FI
FICO
FIS
FITB
FMC
FOX
FOXA
FRT
FSLR
FTNT
FTV
GD
GDDY
GE
GEHC
GEN
GEV
GILD
GIS
GL
GLW
GM
GNRC
GOOG
GOOGL
GPC
GPN
GRMN
GS
GWW
HAL
HAS
HBAN
HCA
HD
HES
HIG
HII
HLT
HOLX
HON
HPE
HPQ
HRL
HSIC
HST
HSY
HUBB
HUM
HWM
IBM
ICE
IDXX
IEX
IFF
INCY
INTC
INTU
INVH
IP
IPG
IQV
IR
IRM
ISRG
IT
ITW
IVZ
J
JBHT
JBL
JCI
JKHY
JNJ
JNPR
JPM
K
KDP
KEY
KEYS
KHC
KIM
KLAC
KMB
KMI
KMX
KO
KR
KVUE
L
LDOS
LEN
LH
LHX
LIN
LKQ
LLY
LMT
LNT
LOW
LRCX
LULU
LUV
LVS
LW
LYB
LYV
MA
MAA
MAR
MAS
MCD
MCHP
MCK
MCO
MDLZ
MDT
MET
META
MGM
MHK
MKC
MKTX
MLM
MMC
MMM
MNST
MO
MOH
MOS
MPC
MPWR
MRK
MRNA
MRO
MS
MSCI
MSFT
MSI
MTB
MTCH
MTD
MU
NCLH
NDAQ
NDSN
NEE
NEM
NFLX
NI
NKE
NOC
NOW
NRG
NSC
NTAP
NTRS
NUE
NVDA
NVR
NWS
NWSA
NXPI
O
ODFL
OKE
OMC
ON
ORCL
ORLY
OTIS
OXY
PANW
PARA
PAYC
PAYX
PCAR
PCG
PEG
PEP
PFE
PFG
PG
PGR
PH
PHM
PKG
PLD
PM
PNC
PNR
PNW
PODD
POOL
PPG
PPL
PRU
PSA
PSX
PTC
PWR
PXD
PYPL
QCOM
QRVO
RCL
REG
REGN
RF
RHI
RJF
RL
RMD
ROK
ROL
ROP
ROST
RSG
RTX
RVTY
SBAC
SBUX
SCHW
SHW
SJM
SLB
SMCI
SNA
SNPS
SO
SOLV
SPG
SPGI
SRE
STE
STLD
STT
STX
STZ
SWK
SWKS
SYF
SYK
SYY
T
TAP
TDG
TDY
TECH
TEL
TER
TFC
TFX
TGT
TJX
TMO
TMUS
TPR
TRGP
TRMB
TROW
TRV
TSCO
TSLA
TSN
TT
TTWO
TXN
TXT
TYL
UAL
UDR
UHS
ULTA
UNH
UNP
UPS
URI
USB
V
VFC
VICI
VLO
VLTO
VMC
VRSK
VRSN
VRTX
VTR
VTRS
VZ
WAB
WAT
WBA
WBD
WDC
WEC
WELL
WFC
WHR
WM
WMB
WMT
WRB
WST
WTW
WY
WYNN
XEL
XOM
XRAY
XYL
YUM
ZBH
ZBRA
ZION
ZTS
```

- [ ] **Step 3: Create `src/screener/data/broad_market.txt`**

Supplemental tickers only (not already in `sp500.txt`) — mid/large-cap NASDAQ/NYSE names that
broaden the scan beyond the index. This is a curated supplement, not an exhaustive NYSE/NASDAQ
listing (documented in `universe.py`'s docstring):

```text
AFRM
ALAB
APP
ARM
ASTS
BILL
BROS
CART
CAVA
CELH
CFLT
CHWY
CLSK
COIN
CPNG
CRWD
CVNA
DASH
DDOG
DKNG
DUOL
DV
ELF
ENVX
ESTC
FIVN
FOUR
FROG
FUBO
GTLB
HIMS
HOOD
IONQ
IOT
JOBY
KVYO
LMND
MARA
MDB
MNDY
MSTR
NET
NU
OKTA
ONON
PATH
PCOR
PINS
PLTR
PLUG
PSTG
RBLX
RDDT
RIOT
RIVN
ROKU
RXRX
S
SE
SEZL
SFM
SHOP
SMAR
SNAP
SNOW
SOFI
SOUN
SQ
SST
SSTK
SYM
TDOC
TEAM
TOST
TTD
TWLO
U
UBER
UPST
VRT
W
WDAY
WOLF
WRBY
XPEV
YETI
ZI
ZM
ZS
```

- [ ] **Step 4: Write the failing tests**

Create `tests/screener/test_universe.py`:

```python
from __future__ import annotations

import pytest

from src.screener.universe import load_universe


def test_load_universe_sp500_is_nonempty_deduplicated_uppercase() -> None:
    tickers = load_universe("sp500")

    assert len(tickers) > 400
    assert tickers == sorted(set(tickers))
    assert all(t == t.upper() for t in tickers)


def test_load_universe_broad_includes_sp500_and_supplement() -> None:
    sp500 = set(load_universe("sp500"))
    broad = load_universe("broad")

    assert set(broad) >= sp500
    assert len(broad) > len(sp500)
    assert len(broad) == len(set(broad))


def test_load_universe_rejects_unknown_name() -> None:
    with pytest.raises(ValueError, match="unknown universe"):
        load_universe("nasdaq100")
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `python -m uv run pytest tests/screener/test_universe.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.screener.universe'`

- [ ] **Step 6: Write `src/screener/universe.py`**

```python
from __future__ import annotations

import pathlib as _pl

_DATA_DIR = _pl.Path(__file__).parent / "data"

# "broad" is a curated supplement (src/screener/data/broad_market.txt) unioned with the S&P 500
# list, not an exhaustive NYSE/NASDAQ listing. Both files are point-in-time snapshots; refreshing
# them is a manual, infrequent maintenance task, not a runtime concern.
_UNIVERSE_FILES = {
    "sp500": ["sp500.txt"],
    "broad": ["sp500.txt", "broad_market.txt"],
}


def load_universe(name: str) -> list[str]:
    if name not in _UNIVERSE_FILES:
        raise ValueError(f"unknown universe {name!r}; expected one of {sorted(_UNIVERSE_FILES)}")

    tickers: set[str] = set()
    for filename in _UNIVERSE_FILES[name]:
        text = (_DATA_DIR / filename).read_text(encoding="utf-8")
        for line in text.splitlines():
            ticker = line.strip().upper()
            if ticker:
                tickers.add(ticker)
    return sorted(tickers)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m uv run pytest tests/screener/test_universe.py -v`
Expected: PASS (3 passed)

- [ ] **Step 8: Commit**

```bash
git add src/screener/__init__.py src/screener/universe.py src/screener/data/sp500.txt \
        src/screener/data/broad_market.txt tests/screener/__init__.py tests/screener/test_universe.py
git commit -m "feat(screener): add universe loader with bundled S&P 500 + broad market ticker lists"
```

- [ ] **Step 9: Code review**

Dispatch a review of this task's diff (`ecc:python-reviewer` agent or `code-review` skill at
medium effort). Check specifically: no duplicate tickers leak between the two files in a way that
breaks the "broad ⊇ sp500, strictly larger" invariant, and `BF-B`/`BRK-B` use yfinance's
hyphenated class-share format (not `BF.B`/`BRK.B`, which yfinance rejects).

---

### Task 2: Metrics — `src/screener/metrics.py`

**Files:**
- Create: `src/screener/metrics.py`
- Test: `tests/screener/test_metrics.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (pure functions over `pd.DataFrame`).
- Produces: `compute_metrics(bars_by_symbol: dict[str, pd.DataFrame], spy_df: pd.DataFrame) ->
  pd.DataFrame`, indexed by symbol, columns: `momentum_1m, momentum_3m, momentum_6m,
  momentum_12m, rel_strength_1m, rel_strength_3m, rel_strength_6m, rel_strength_12m, rsi14,
  rel_volume, volatility, trend_quality`. Each per-symbol `pd.DataFrame` (including `spy_df`) is
  expected to have a `close` and `volume` column, sorted ascending by date (this is what
  `data.fetch_universe_bars` in Task 3 returns).

- [ ] **Step 1: Write the failing tests**

Create `tests/screener/test_metrics.py`:

```python
from __future__ import annotations

import numpy as np
import pandas as pd

from src.screener.metrics import compute_metrics


def _flat_series(n: int, close: float = 100.0, volume: float = 1_000_000) -> pd.DataFrame:
    return pd.DataFrame({"close": [close] * n, "volume": [volume] * n})


def _uptrend_series(n: int, start: float = 100.0, daily_return: float = 0.003) -> pd.DataFrame:
    closes = [start * (1 + daily_return) ** i for i in range(n)]
    return pd.DataFrame({"close": closes, "volume": [1_000_000] * n})


def test_flat_series_has_zero_momentum_and_neutral_rsi() -> None:
    bars = {"FLAT": _flat_series(300)}
    spy = _flat_series(300)

    metrics = compute_metrics(bars, spy)

    assert metrics.loc["FLAT", "momentum_1m"] == 0.0
    assert metrics.loc["FLAT", "momentum_12m"] == 0.0
    assert metrics.loc["FLAT", "rsi14"] == 100.0  # matches src/ml/features.py's _rsi convention


def test_uptrend_beats_flat_benchmark_on_momentum_and_relative_strength() -> None:
    bars = {"UP": _uptrend_series(300)}
    spy = _flat_series(300)

    metrics = compute_metrics(bars, spy)

    assert metrics.loc["UP", "momentum_12m"] > 0
    assert metrics.loc["UP", "rel_strength_12m"] > 0
    assert metrics.loc["UP", "trend_quality"] > 0.9


def test_volume_spike_raises_relative_volume() -> None:
    df = _flat_series(300)
    df.loc[df.index[-1], "volume"] = 10_000_000  # 10x the trailing 20-day average
    bars = {"SPIKE": df}
    spy = _flat_series(300)

    metrics = compute_metrics(bars, spy)

    assert metrics.loc["SPIKE", "rel_volume"] > 5.0


def test_symbol_with_insufficient_history_is_dropped() -> None:
    bars = {"NEWCO": _flat_series(10), "OLD": _flat_series(300)}
    spy = _flat_series(300)

    metrics = compute_metrics(bars, spy)

    assert "NEWCO" not in metrics.index
    assert "OLD" in metrics.index
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m uv run pytest tests/screener/test_metrics.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.screener.metrics'`

- [ ] **Step 3: Write `src/screener/metrics.py`**

```python
from __future__ import annotations

import numpy as np
import pandas as pd

# Trading-day approximations for the four momentum/relative-strength windows.
_WINDOWS = {"1m": 21, "3m": 63, "6m": 126, "12m": 252}
# Minimum trailing history required for a symbol to be scored (12-month window + warm-up).
_MIN_HISTORY = 260


def compute_metrics(bars_by_symbol: dict[str, pd.DataFrame], spy_df: pd.DataFrame) -> pd.DataFrame:
    rows: dict[str, dict[str, float]] = {}
    for symbol, df in bars_by_symbol.items():
        if len(df) < _MIN_HISTORY:
            continue
        rows[symbol] = _metrics_for_symbol(df, spy_df)

    return pd.DataFrame.from_dict(rows, orient="index")


def _metrics_for_symbol(df: pd.DataFrame, spy_df: pd.DataFrame) -> dict[str, float]:
    close = df["close"]
    row: dict[str, float] = {}

    for label, window in _WINDOWS.items():
        sym_return = _trailing_return(close, window)
        spy_return = _trailing_return(spy_df["close"], window)
        row[f"momentum_{label}"] = sym_return
        row[f"rel_strength_{label}"] = sym_return - spy_return

    row["rsi14"] = float(_rsi(close, period=14).iloc[-1])
    row["rel_volume"] = _relative_volume(df["volume"])
    row["volatility"] = _realized_volatility(close)
    row["trend_quality"] = _trend_quality(close)
    return row


def _trailing_return(close: pd.Series, window: int) -> float:
    if len(close) <= window:
        return 0.0
    start, end = close.iloc[-window - 1], close.iloc[-1]
    if start == 0:
        return 0.0
    return float((end - start) / start)


# Same rolling-gain/loss formula as src/ml/features.py's _rsi — duplicated rather than shared
# (see plan's Global Constraints for why).
def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.where(avg_loss != 0, 100.0)


def _relative_volume(volume: pd.Series) -> float:
    avg20 = volume.rolling(window=20).mean().iloc[-1]
    if avg20 == 0 or np.isnan(avg20):
        return 1.0
    return float(volume.iloc[-1] / avg20)


def _realized_volatility(close: pd.Series) -> float:
    daily_returns = close.pct_change().dropna().iloc[-20:]
    return float(daily_returns.std() * np.sqrt(252))


def _trend_quality(close: pd.Series) -> float:
    sma50 = close.rolling(window=50).mean()
    tail_close = close.iloc[-50:]
    tail_sma = sma50.iloc[-50:]
    return float((tail_close > tail_sma).mean())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m uv run pytest tests/screener/test_metrics.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/screener/metrics.py tests/screener/test_metrics.py
git commit -m "feat(screener): add per-symbol momentum/relative-strength/RSI/volume/volatility metrics"
```

- [ ] **Step 6: Code review**

Dispatch `ecc:python-reviewer` (or `code-review` skill, medium effort) on this diff. Check
specifically: `_trailing_return`'s off-by-one (`window`-day return should compare `close[-1]` to
`close[-1-window]`, not `close[-window]`), and that `_MIN_HISTORY` (260) is actually enough
padding above the 252-day window for the rolling calcs not to silently emit `NaN` into the final
row (they won't, since `_MIN_HISTORY > 252`, but confirm this explicitly rather than trusting the
comment).

---

### Task 3: Data fetch + caching — `src/screener/data.py`

**Files:**
- Create: `src/screener/data.py`
- Test: `tests/screener/test_data.py`

**Interfaces:**
- Consumes: nothing from earlier tasks directly (takes a `list[str]` of symbols).
- Produces: `fetch_universe_bars(universe_name: str, symbols: list[str], cache_dir: pathlib.Path
  | None = None) -> dict[str, pd.DataFrame]`. Always includes `"SPY"` in the returned dict (fetched
  alongside the universe, used by Task 2's `compute_metrics` as the benchmark) even though `"SPY"`
  is not part of the `symbols` list the caller passes in.

- [ ] **Step 1: Write the failing tests**

Create `tests/screener/test_data.py`:

```python
from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from src.screener import data as data_module
from src.screener.data import fetch_universe_bars


def _fake_download(tickers: str, **kwargs: Any) -> pd.DataFrame:
    symbols = tickers.split()
    idx = pd.date_range("2025-01-01", periods=5, freq="D")
    columns = pd.MultiIndex.from_product([symbols, ["Open", "High", "Low", "Close", "Volume"]])
    data = {}
    for sym in symbols:
        for field, val in [("Open", 10.0), ("High", 11.0), ("Low", 9.0), ("Close", 10.5), ("Volume", 100.0)]:
            data[(sym, field)] = [val] * len(idx)
    return pd.DataFrame(data, index=idx, columns=columns)


def test_fetch_universe_bars_includes_spy_and_requested_symbols(monkeypatch: Any, tmp_path: Any) -> None:
    monkeypatch.setattr(data_module.yf, "download", _fake_download)

    result = fetch_universe_bars("sp500", ["AAPL", "MSFT"], cache_dir=tmp_path)

    assert set(result) == {"AAPL", "MSFT", "SPY"}
    assert list(result["AAPL"].columns) == ["open", "high", "low", "close", "volume"]
    assert result["AAPL"]["close"].iloc[0] == 10.5


def test_fetch_universe_bars_writes_and_reuses_cache(monkeypatch: Any, tmp_path: Any) -> None:
    calls = {"count": 0}

    def _counting_download(tickers: str, **kwargs: Any) -> pd.DataFrame:
        calls["count"] += 1
        return _fake_download(tickers, **kwargs)

    monkeypatch.setattr(data_module.yf, "download", _counting_download)

    fetch_universe_bars("sp500", ["AAPL"], cache_dir=tmp_path)
    first_call_count = calls["count"]
    fetch_universe_bars("sp500", ["AAPL"], cache_dir=tmp_path)

    assert calls["count"] == first_call_count  # second call hit the cache, no new network calls
    cached_files = list(tmp_path.glob("sp500_*.parquet"))
    assert len(cached_files) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m uv run pytest tests/screener/test_data.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.screener.data'`

- [ ] **Step 3: Write `src/screener/data.py`**

```python
from __future__ import annotations

import datetime as _dt
import pathlib as _pl

import pandas as pd
import yfinance as yf

_DEFAULT_CACHE_DIR = _pl.Path(".cache/screener")
_CHUNK_SIZE = 100
_PERIOD = "14mo"
_BENCHMARK = "SPY"


def fetch_universe_bars(
    universe_name: str, symbols: list[str], cache_dir: _pl.Path | None = None
) -> dict[str, pd.DataFrame]:
    cache_dir = cache_dir if cache_dir is not None else _DEFAULT_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    today = _dt.datetime.now(_dt.UTC).date().isoformat()
    cache_path = cache_dir / f"{universe_name}_{today}.parquet"

    if cache_path.exists():
        combined = pd.read_parquet(cache_path)
    else:
        all_symbols = sorted(set(symbols) | {_BENCHMARK})
        combined = _download_chunked(all_symbols)
        combined.to_parquet(cache_path)

    return _split_by_symbol(combined, sorted(set(symbols) | {_BENCHMARK}))


def _download_chunked(symbols: list[str]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for i in range(0, len(symbols), _CHUNK_SIZE):
        chunk = symbols[i : i + _CHUNK_SIZE]
        raw = yf.download(
            " ".join(chunk), period=_PERIOD, interval="1d", group_by="ticker",
            auto_adjust=True, progress=False, threads=True,
        )
        frames.append(_normalize_columns(raw, chunk))
    return pd.concat(frames, axis=1)


def _normalize_columns(raw: pd.DataFrame, symbols: list[str]) -> pd.DataFrame:
    # yfinance returns a single-level column index (OHLCV) when only one ticker was requested,
    # and a MultiIndex (ticker, field) for multi-ticker downloads — normalize both to MultiIndex.
    if len(symbols) == 1 and not isinstance(raw.columns, pd.MultiIndex):
        raw = pd.concat({symbols[0]: raw}, axis=1)
    return raw


def _split_by_symbol(combined: pd.DataFrame, symbols: list[str]) -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        if sym not in combined.columns.get_level_values(0):
            continue
        df = combined[sym][["Open", "High", "Low", "Close", "Volume"]].dropna()
        df.columns = ["open", "high", "low", "close", "volume"]
        result[sym] = df.sort_index()
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m uv run pytest tests/screener/test_data.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/screener/data.py tests/screener/test_data.py
git commit -m "feat(screener): batch-fetch yfinance OHLCV with per-day disk cache"
```

- [ ] **Step 6: Update `.gitignore`**

Add a line to `C:\Users\tshor\OneDrive\Desktop\Projects\Hedge\Hedge fund\.gitignore`:

```text
.cache/
```

```bash
git add .gitignore
git commit -m "chore: ignore .cache/ (screener parquet cache)"
```

- [ ] **Step 7: Code review**

Dispatch `ecc:python-reviewer` on this diff — this task is the highest-risk one (external I/O,
caching, chunking) and should get a strong-model review regardless of who implemented it. Check
specifically: cache-key collisions between `"sp500"` and `"broad"` runs on the same day (they use
different filenames, so this is fine — confirm), and that `_split_by_symbol` correctly drops a
requested symbol that yfinance simply didn't return data for (e.g., a delisted ticker) instead of
raising a `KeyError`.

---

### Task 4: Scorer — `src/screener/scorer.py`

**Files:**
- Create: `src/screener/scorer.py`
- Test: `tests/screener/test_scorer.py`

**Interfaces:**
- Consumes: a `pd.DataFrame` shaped like Task 2's `compute_metrics` output (indexed by symbol,
  numeric columns).
- Produces: `DEFAULT_WEIGHTS: dict[str, float]` (see Global Constraints for values — keys are
  `momentum, rel_strength, rsi, rel_volume, volatility`, each a blend of that factor's `_1m.._12m`
  columns where applicable, see Step 3), `score(metrics_df: pd.DataFrame, weights: dict[str,
  float] | None = None) -> pd.DataFrame`, returns `metrics_df` with an added `score` column
  (0–100), sorted descending by `score`. Raises `ValueError` if `weights` values don't sum to
  `1.0` (within `1e-6` tolerance).

- [ ] **Step 1: Write the failing tests**

Create `tests/screener/test_scorer.py`:

```python
from __future__ import annotations

import pandas as pd
import pytest

from src.screener.scorer import DEFAULT_WEIGHTS, score


def _sample_metrics() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "momentum_1m": [0.01, 0.05, -0.02],
            "momentum_3m": [0.02, 0.10, -0.03],
            "momentum_6m": [0.05, 0.20, -0.05],
            "momentum_12m": [0.10, 0.40, -0.10],
            "rel_strength_1m": [0.0, 0.03, -0.01],
            "rel_strength_3m": [0.0, 0.06, -0.02],
            "rel_strength_6m": [0.0, 0.12, -0.03],
            "rel_strength_12m": [0.0, 0.25, -0.05],
            "rsi14": [50.0, 70.0, 30.0],
            "rel_volume": [1.0, 2.0, 0.5],
            "volatility": [0.2, 0.3, 0.15],
        },
        index=["FLAT", "WINNER", "LOSER"],
    )


def test_default_weights_sum_to_one() -> None:
    assert abs(sum(DEFAULT_WEIGHTS.values()) - 1.0) < 1e-9


def test_score_ranks_strong_momentum_symbol_first() -> None:
    result = score(_sample_metrics())

    assert result.index[0] == "WINNER"
    assert result["score"].is_monotonic_decreasing


def test_score_rejects_weights_not_summing_to_one() -> None:
    bad_weights = {**DEFAULT_WEIGHTS, "momentum": DEFAULT_WEIGHTS["momentum"] + 0.5}
    with pytest.raises(ValueError, match="must sum to 1.0"):
        score(_sample_metrics(), weights=bad_weights)


def test_low_weight_factor_does_not_dominate_ranking() -> None:
    # LOSER has the lowest volatility (best by our "lower is better" convention) but should not
    # overtake WINNER when volatility's weight is small relative to momentum/rel_strength.
    result = score(_sample_metrics())
    assert result.index[0] == "WINNER"
    assert result.loc["LOSER", "score"] < result.loc["WINNER", "score"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m uv run pytest tests/screener/test_scorer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.screener.scorer'`

- [ ] **Step 3: Write `src/screener/scorer.py`**

```python
from __future__ import annotations

import pandas as pd

DEFAULT_WEIGHTS: dict[str, float] = {
    "momentum": 0.30,
    "rel_strength": 0.30,
    "rsi": 0.15,
    "rel_volume": 0.10,
    "volatility": 0.15,
}

# Multi-window factors are averaged across their _1m.._12m columns before percentile-ranking.
# volatility is inverted (lower realized vol ranks higher) — it's a risk penalty, not a reward.
_MULTI_WINDOW_FACTORS = {
    "momentum": ["momentum_1m", "momentum_3m", "momentum_6m", "momentum_12m"],
    "rel_strength": ["rel_strength_1m", "rel_strength_3m", "rel_strength_6m", "rel_strength_12m"],
}
_SINGLE_COLUMN_FACTORS = {"rsi": "rsi14", "rel_volume": "rel_volume"}
_INVERTED_FACTORS = {"volatility": "volatility"}


def score(metrics_df: pd.DataFrame, weights: dict[str, float] | None = None) -> pd.DataFrame:
    """weights, if given, must specify all five factor keys (momentum, rel_strength, rsi,
    rel_volume, volatility) — it replaces DEFAULT_WEIGHTS entirely rather than merging into it."""
    weights = weights if weights is not None else DEFAULT_WEIGHTS
    total = sum(weights.values())
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"weights must sum to 1.0, got {total}")

    percentiles = pd.DataFrame(index=metrics_df.index)
    for factor, cols in _MULTI_WINDOW_FACTORS.items():
        raw = metrics_df[cols].mean(axis=1)
        percentiles[factor] = raw.rank(pct=True) * 100

    for factor, col in _SINGLE_COLUMN_FACTORS.items():
        percentiles[factor] = metrics_df[col].rank(pct=True) * 100

    for factor, col in _INVERTED_FACTORS.items():
        percentiles[factor] = (1 - metrics_df[col].rank(pct=True)) * 100

    composite = sum(percentiles[factor] * weight for factor, weight in weights.items())

    result = metrics_df.copy()
    result["score"] = composite
    return result.sort_values("score", ascending=False)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m uv run pytest tests/screener/test_scorer.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/screener/scorer.py tests/screener/test_scorer.py
git commit -m "feat(screener): percentile-rank + weighted composite scorer"
```

- [ ] **Step 6: Code review**

Dispatch `ecc:python-reviewer` on this diff. Check specifically: a caller-supplied `weights` dict
that omits one of the five factor keys makes the `sum(percentiles[factor] * weight for factor,
weight in weights.items())` comprehension silently skip that factor rather than raising — confirm
this is intentional (weights replace defaults entirely, per the docstring) and not a latent bug;
if the reviewer thinks a missing key should raise loudly instead, treat that as a design question
for the user rather than silently changing the contract.

---

### Task 5: Orchestration service — `src/screener/service.py`

**Files:**
- Create: `src/screener/service.py`
- Test: `tests/screener/test_service.py`

**Interfaces:**
- Consumes: `load_universe` (Task 1), `fetch_universe_bars` (Task 3), `compute_metrics` (Task 2),
  `score`/`DEFAULT_WEIGHTS` (Task 4).
- Produces: `ScreenProgress` dataclass (`stage: str`, `detail: str = ""`), `run_screen(universe:
  str, weights: dict[str, float] | None = None, on_progress: Callable[[ScreenProgress], None] |
  None = None) -> pd.DataFrame`. Calls `on_progress` at four stages in order: `"universe_loaded"`,
  `"data_fetched"`, `"metrics_computed"`, `"done"`. Fully synchronous — no `async def` anywhere in
  this module, matching the spec's requirement that the caller runs it off-thread if needed.

- [ ] **Step 1: Write the failing tests**

Create `tests/screener/test_service.py`:

```python
from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from src.screener import service as service_module
from src.screener.service import ScreenProgress, run_screen


def _fake_load_universe(name: str) -> list[str]:
    return ["AAPL", "MSFT"]


def _fake_fetch_universe_bars(universe_name: str, symbols: list[str], cache_dir: Any = None) -> dict[str, pd.DataFrame]:
    n = 300
    closes = [100.0 + i * 0.1 for i in range(n)]
    df = pd.DataFrame({"close": closes, "volume": [1_000_000] * n})
    return {sym: df for sym in [*symbols, "SPY"]}


def test_run_screen_reports_all_four_stages_in_order(monkeypatch: Any) -> None:
    monkeypatch.setattr(service_module, "load_universe", _fake_load_universe)
    monkeypatch.setattr(service_module, "fetch_universe_bars", _fake_fetch_universe_bars)

    stages: list[str] = []
    result = run_screen("sp500", on_progress=lambda p: stages.append(p.stage))

    assert stages == ["universe_loaded", "data_fetched", "metrics_computed", "done"]
    assert isinstance(result, pd.DataFrame)
    assert "score" in result.columns
    assert set(result.index) == {"AAPL", "MSFT"}


def test_run_screen_works_without_progress_callback(monkeypatch: Any) -> None:
    monkeypatch.setattr(service_module, "load_universe", _fake_load_universe)
    monkeypatch.setattr(service_module, "fetch_universe_bars", _fake_fetch_universe_bars)

    result = run_screen("sp500")

    assert not result.empty


def test_run_screen_accepts_custom_weights(monkeypatch: Any) -> None:
    monkeypatch.setattr(service_module, "load_universe", _fake_load_universe)
    monkeypatch.setattr(service_module, "fetch_universe_bars", _fake_fetch_universe_bars)
    custom = {"momentum": 1.0, "rel_strength": 0.0, "rsi": 0.0, "rel_volume": 0.0, "volatility": 0.0}

    result = run_screen("sp500", weights=custom)

    assert "score" in result.columns


def test_run_screen_raises_clear_error_when_spy_benchmark_missing(monkeypatch: Any) -> None:
    monkeypatch.setattr(service_module, "load_universe", _fake_load_universe)

    def _fetch_without_spy(universe_name: str, symbols: list[str], cache_dir: Any = None) -> dict[str, pd.DataFrame]:
        n = 300
        df = pd.DataFrame({"close": [100.0] * n, "volume": [1_000_000] * n})
        return {sym: df for sym in symbols}  # no SPY

    monkeypatch.setattr(service_module, "fetch_universe_bars", _fetch_without_spy)

    with pytest.raises(RuntimeError, match="SPY benchmark data unavailable"):
        run_screen("sp500")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m uv run pytest tests/screener/test_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.screener.service'`

- [ ] **Step 3: Write `src/screener/service.py`**

```python
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd

from src.screener.data import fetch_universe_bars
from src.screener.metrics import compute_metrics
from src.screener.scorer import score
from src.screener.universe import load_universe

ProgressCallback = Callable[["ScreenProgress"], None]


@dataclass
class ScreenProgress:
    stage: str
    detail: str = ""


def run_screen(
    universe: str,
    weights: dict[str, float] | None = None,
    on_progress: ProgressCallback | None = None,
) -> pd.DataFrame:
    def _report(stage: str, detail: str = "") -> None:
        if on_progress is not None:
            on_progress(ScreenProgress(stage=stage, detail=detail))

    symbols = load_universe(universe)
    _report("universe_loaded", f"{len(symbols)} symbols")

    bars_by_symbol = fetch_universe_bars(universe, symbols)
    _report("data_fetched", f"{len(bars_by_symbol)} symbols with data")

    if "SPY" not in bars_by_symbol:
        raise RuntimeError("SPY benchmark data unavailable — cannot compute relative strength")
    spy_df = bars_by_symbol["SPY"]
    scannable = {sym: df for sym, df in bars_by_symbol.items() if sym != "SPY"}
    metrics_df = compute_metrics(scannable, spy_df)
    _report("metrics_computed", f"{len(metrics_df)} symbols scored")

    result = score(metrics_df, weights=weights)
    _report("done")
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m uv run pytest tests/screener/test_service.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/screener/service.py tests/screener/test_service.py
git commit -m "feat(screener): orchestrate universe -> data -> metrics -> scorer with progress callbacks"
```

- [ ] **Step 6: Code review**

Dispatch `ecc:python-reviewer` on this diff (strong-model review — this is the module every other
caller depends on). Check specifically: the `RuntimeError` guard added in Step 3 is tested (Step
1's last test) and that no other required key (`bars_by_symbol` being empty entirely, e.g. every
single fetch failed) can similarly crash downstream with a confusing raw exception — if so, decide
with the reviewer whether an equally explicit guard is warranted there too.

---

### Task 6: Dashboard integration — endpoints, WS broadcast, `DashboardState`

**Files:**
- Modify: `src/dashboard/app.py` (add `ScreenRequest`/`ScreenStopRequest` models,
  `/api/screener/run`, `/api/screener/stop`, `_active_screen` state, `broadcast_screener_result`
  on `DashboardState`)
- Test: `tests/dashboard/test_screener_api.py`

**Interfaces:**
- Consumes: `run_screen`, `ScreenProgress` from `src.screener.service` (Task 5).
- Produces: `POST /api/screener/run` (body `{"universe": str, "weights": dict[str, float] |
  None}`) → `202 {"status": "started"}` or `409 {"status": "already_running"}` if one is already in
  flight. `POST /api/screener/stop` → `{"status": "stopping"}` (broadcast-suppression only —
  `run_screen` has no per-item checkpoint to actually interrupt, unlike the NN-trainer's per-epoch
  `Trainer.stop()`; "stopping" reflects this honestly, confirmed with the user during Task 6's
  review) or `{"status": "not_running"}`.
  `DashboardState.broadcast_screener_result(payload: dict[str, Any]) -> None` (async), broadcasts
  `{"type": "screener_result", **payload}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/dashboard/test_screener_api.py`:

```python
from __future__ import annotations

import time
from typing import Any

import pandas as pd
from fastapi.testclient import TestClient

import src.dashboard.app as app_module
from src.dashboard.app import create_app


def _fake_run_screen(universe: str, weights: Any = None, on_progress: Any = None) -> pd.DataFrame:
    if on_progress is not None:
        from src.screener.service import ScreenProgress
        on_progress(ScreenProgress(stage="universe_loaded"))
        on_progress(ScreenProgress(stage="done"))
    return pd.DataFrame({"score": [90.0, 80.0]}, index=["AAPL", "MSFT"])


def test_start_screen_returns_202(monkeypatch: Any) -> None:
    monkeypatch.setattr(app_module, "run_screen", _fake_run_screen)
    client = TestClient(create_app())

    resp = client.post("/api/screener/run", json={"universe": "sp500"})

    assert resp.status_code == 202
    assert resp.json()["status"] == "started"


def test_start_screen_rejects_duplicate(monkeypatch: Any) -> None:
    monkeypatch.setattr(app_module, "run_screen", _fake_run_screen)
    app_module._active_screen["running"] = True
    client = TestClient(create_app())

    resp = client.post("/api/screener/run", json={"universe": "sp500"})

    assert resp.status_code == 409
    app_module._active_screen["running"] = False


def test_stop_screen_is_noop_when_not_running() -> None:
    client = TestClient(create_app())

    resp = client.post("/api/screener/stop", json={})

    assert resp.status_code == 200
    assert resp.json()["status"] == "not_running"


def test_start_screen_broadcasts_done_with_results(monkeypatch: Any) -> None:
    monkeypatch.setattr(app_module, "run_screen", _fake_run_screen)

    broadcasts: list[dict[str, Any]] = []
    original_broadcast = app_module._state.broadcast_screener_result

    async def _capturing_broadcast(payload: dict[str, Any]) -> None:
        broadcasts.append(payload)
        await original_broadcast(payload)

    monkeypatch.setattr(app_module._state, "broadcast_screener_result", _capturing_broadcast)

    client = TestClient(create_app())
    resp = client.post("/api/screener/run", json={"universe": "sp500"})
    assert resp.status_code == 202

    for _ in range(100):
        if any(b.get("status") == "done" for b in broadcasts):
            break
        time.sleep(0.02)

    done = [b for b in broadcasts if b.get("status") == "done"]
    assert done, "expected a done broadcast"
    assert done[0]["results"][0]["symbol"] == "AAPL"
    assert app_module._active_screen["running"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m uv run pytest tests/dashboard/test_screener_api.py -v`
Expected: FAIL — `app_module.run_screen` doesn't exist yet, `AttributeError`.

- [ ] **Step 3: Add the `ScreenRequest`/`ScreenStopRequest` models and imports**

In `src/dashboard/app.py`, add to the imports near the top (after the existing `from src.ml...`
lines):

```python
from src.screener.service import ScreenProgress, run_screen
```

Add near `class StopRequest(BaseModel):` (after it):

```python
class ScreenRequest(BaseModel):
    universe: str
    weights: dict[str, float] | None = None


class ScreenStopRequest(BaseModel):
    pass
```

- [ ] **Step 4: Add screener state and `broadcast_screener_result` to `DashboardState`**

In `src/dashboard/app.py`, add this method to `DashboardState` right after
`broadcast_ml_training`:

```python
    async def broadcast_screener_result(self, payload: dict[str, Any]) -> None:
        await self._broadcast({"type": "screener_result", **payload})
```

Add this module-level state near `_active_trainers`:

```python
_active_screen: dict[str, bool] = {"running": False}
_screen_stop_requested = False
```

- [ ] **Step 5: Add the two endpoints**

In `src/dashboard/app.py`, inside `create_app()`, add these two routes right after the
`stop_ml_training` route:

```python
    @app.post("/api/screener/run")
    async def start_screen(req: ScreenRequest) -> JSONResponse:
        if _active_screen["running"]:
            return JSONResponse(status_code=409, content={"status": "already_running"})

        _active_screen["running"] = True
        global _screen_stop_requested
        _screen_stop_requested = False
        loop = asyncio.get_running_loop()

        def on_progress(progress: ScreenProgress) -> None:
            if _screen_stop_requested:
                return
            asyncio.run_coroutine_threadsafe(
                _state.broadcast_screener_result(
                    {"status": "progress", "stage": progress.stage, "detail": progress.detail}
                ),
                loop,
            )

        async def _run() -> None:
            try:
                result_df = await asyncio.to_thread(
                    run_screen, req.universe, req.weights, on_progress
                )
                results = [
                    {"symbol": sym, **row.to_dict()} for sym, row in result_df.iterrows()
                ]
                await _state.broadcast_screener_result({"status": "done", "results": results})
            except Exception as exc:
                log.exception("screener_failed", universe=req.universe)
                await _state.broadcast_screener_result({"status": "error", "detail": str(exc)})
            finally:
                _active_screen["running"] = False

        asyncio.create_task(_run())
        return JSONResponse(status_code=202, content={"status": "started"})

    @app.post("/api/screener/stop")
    async def stop_screen(req: ScreenStopRequest) -> dict[str, str]:
        global _screen_stop_requested
        if not _active_screen["running"]:
            return {"status": "not_running"}
        _screen_stop_requested = True
        return {"status": "stopping"}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m uv run pytest tests/dashboard/test_screener_api.py -v`
Expected: PASS (4 passed)

- [ ] **Step 7: Run the full test suite to check for regressions**

Run: `python -m uv run pytest -x -q`
Expected: all tests pass (existing + new)

- [ ] **Step 8: Commit**

```bash
git add src/dashboard/app.py tests/dashboard/test_screener_api.py
git commit -m "feat(dashboard): add /api/screener/run and /api/screener/stop, screener_result WS broadcast"
```

- [ ] **Step 9: Code review**

Dispatch `ecc:security-reviewer` alongside `ecc:python-reviewer` on this diff (strong-model review
— this is the concurrency-bridging code, the highest-risk piece in the whole plan). Check
specifically:
1. `asyncio.run_coroutine_threadsafe` is called from the worker thread — confirm `loop` (captured
   before `asyncio.to_thread` starts) is still the running loop when the callback fires, and that
   a progress callback firing after the client disconnects can't raise unhandled into the thread
   pool.
2. `_screen_stop_requested` only stops progress *broadcasts* — `run_screen` itself doesn't check
   it and will run to completion. Confirm this matches user expectations for "Stop" (it mirrors
   `Trainer.stop()`'s cooperative-checkpoint pattern in spirit, but `run_screen` has no natural
   per-epoch checkpoint to check a stop flag at). If the reviewer decides silent-continue-in-
   background is unacceptable, escalate to the user rather than guessing at a fix — this changes
   the spec's execution model.
3. `req.weights` from an untrusted client is passed straight into `scorer.score()` — a
   caller-supplied dict with unexpected keys or values (e.g. negative weights, or keys that don't
   match any known factor) is either silently ignored (extra keys) or produces a nonsensical but
   non-crashing score (negative weights) rather than a crash, since `score()` iterates over
   `weights.items()` rather than looking up caller-supplied keys in a fixed structure. Confirm this
   degrades gracefully (already caught by the outer `try/except Exception` in `_run()` in the
   worst case) and doesn't need input validation added at the endpoint boundary; escalate to the
   user only if the reviewer thinks silently-wrong scores (as opposed to a clear error) are an
   unacceptable UX for bad client input.

---

### Task 7: Dashboard widget — `src/dashboard/static/js/screener.js`

**Files:**
- Create: `src/dashboard/static/js/screener.js`
- Modify: `src/dashboard/static/js/widgets.js` (register widget type, add `dispatchScreenerResult`)
- Modify: `src/dashboard/static/js/ws.js` (dispatch `screener_result` messages)
- Modify: `src/dashboard/static/js/layout.js` (pass through the `universe` config key on restore)

**Interfaces:**
- Consumes: `WIDGET_TYPES`, `createWidget`, `instances` from `widgets.js` (existing); `POST
  /api/screener/run` / `/api/screener/stop` (Task 6); `screener_result` WS messages shaped
  `{type: "screener_result", status: "progress"|"done"|"error", stage?, detail?, results?}` where
  each `results[i]` is `{symbol, score, momentum_1m, ..., trend_quality}` (Task 6's
  `row.to_dict()` output, flattened).
- Produces: `createScreenerWidget(container, config) -> {handleScreenerResult(msg), getConfig(),
  destroy()}` — same instance-handle shape as `createMlWidget` in `ml.js`.

- [ ] **Step 1: Create `src/dashboard/static/js/screener.js`**

```javascript
// Stock screener widget: pick a universe, run a scan, show a sortable ranked table. Mirrors
// ml.js's Start/Stop + WS-progress pattern, but has no per-symbol subscription (needsSymbol: false).
export function createScreenerWidget(container, config) {
  config.universe = config.universe || 'sp500';

  container.innerHTML = `
    <div class="panel">
      <div class="panel-header" style="flex-wrap:wrap;gap:6px">
        <span class="w-chart-label">Screener</span>
        <div style="display:flex;gap:8px;align-items:center;font-size:11px">
          <label>Universe
            <select class="w-scr-universe">
              <option value="sp500">S&amp;P 500</option>
              <option value="broad">Broad Market</option>
            </select>
          </label>
          <button class="w-scr-run">Run</button>
          <button class="w-scr-stop">Stop</button>
        </div>
        <span class="w-scr-status" style="color:#a39c8f;font-size:11px;width:100%"></span>
      </div>
      <div class="w-scr-table-wrap" style="flex:1 1 auto;overflow:auto">
        <table class="w-scr-table" style="width:100%;border-collapse:collapse;font-size:12px">
          <thead>
            <tr>
              <th data-col="symbol">Symbol</th>
              <th data-col="score">Score</th>
              <th data-col="momentum_12m">Mom 12m</th>
              <th data-col="rel_strength_12m">RelStr 12m</th>
              <th data-col="rsi14">RSI14</th>
              <th data-col="rel_volume">RelVol</th>
              <th data-col="volatility">Vol</th>
            </tr>
          </thead>
          <tbody></tbody>
        </table>
      </div>
    </div>`;

  const universeSelect = container.querySelector('.w-scr-universe');
  universeSelect.value = config.universe;
  const statusEl = container.querySelector('.w-scr-status');
  const tbody = container.querySelector('tbody');
  let rows = [];
  let sortCol = 'score';
  let sortAsc = false;

  function render() {
    const sorted = [...rows].sort((a, b) => {
      const av = a[sortCol] ?? 0, bv = b[sortCol] ?? 0;
      return sortAsc ? av - bv : bv - av;
    });
    tbody.innerHTML = sorted.map(r => `
      <tr>
        <td>${r.symbol}</td>
        <td>${(r.score ?? 0).toFixed(1)}</td>
        <td>${((r.momentum_12m ?? 0) * 100).toFixed(1)}%</td>
        <td>${((r.rel_strength_12m ?? 0) * 100).toFixed(1)}%</td>
        <td>${(r.rsi14 ?? 0).toFixed(0)}</td>
        <td>${(r.rel_volume ?? 0).toFixed(2)}x</td>
        <td>${((r.volatility ?? 0) * 100).toFixed(1)}%</td>
      </tr>`).join('');
  }

  container.querySelectorAll('[data-col]').forEach(th => {
    th.style.cursor = 'pointer';
    th.onclick = () => {
      const col = th.dataset.col;
      sortAsc = sortCol === col ? !sortAsc : false;
      sortCol = col;
      render();
    };
  });

  function handleScreenerResult(msg) {
    if (msg.status === 'progress') {
      statusEl.textContent = `running — ${msg.stage}${msg.detail ? ': ' + msg.detail : ''}`;
    } else if (msg.status === 'done') {
      rows = msg.results || [];
      statusEl.textContent = `done — ${rows.length} symbols`;
      render();
    } else if (msg.status === 'error') {
      statusEl.textContent = `error: ${msg.detail}`;
    }
  }

  container.querySelector('.w-scr-run').onclick = async () => {
    config.universe = universeSelect.value;
    statusEl.textContent = 'starting...';
    try {
      const r = await fetch('/api/screener/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ universe: config.universe }),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        statusEl.textContent = `could not start: ${body.status || r.status}`;
      }
    } catch (e) {
      statusEl.textContent = 'failed to start';
    }
  };

  container.querySelector('.w-scr-stop').onclick = async () => {
    try {
      await fetch('/api/screener/stop', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      statusEl.textContent = 'stopping...';
    } catch (e) { /* best effort */ }
  };

  return {
    handleScreenerResult,
    getConfig() { return { universe: config.universe }; },
    destroy() {},
  };
}
```

- [ ] **Step 2: Register the widget type in `widgets.js`**

In `src/dashboard/static/js/widgets.js`, add the import (after the `createMlWidget` import):

```javascript
import { createScreenerWidget } from './screener.js';
```

Add an entry to `WIDGET_TYPES` (after the `ml:` entry):

```javascript
  screener: { label: 'Screener',      defaultSize: { w: 8, h: 6 }, needsSymbol: false, allowsPortfolio: false },
```

Add a branch to `createWidget` (after the `ml` branch):

```javascript
  else if (type === 'screener') handle = createScreenerWidget(container, config);
```

Add a new dispatch function at the end of the file (after `dispatchMlTraining`):

```javascript
export function dispatchScreenerResult(msg) {
  for (const inst of instances.values()) {
    if (inst.type === 'screener' && inst.handle.handleScreenerResult) inst.handle.handleScreenerResult(msg);
  }
}
```

- [ ] **Step 3: Wire the WS dispatch in `ws.js`**

In `src/dashboard/static/js/ws.js`, add `dispatchScreenerResult` to the import list:

```javascript
import {
  dispatchBar, dispatchPortfolioValue, dispatchOrder,
  dispatchHoldings, dispatchPosition, dispatchMlTraining, dispatchScreenerResult,
} from './widgets.js';
```

Add a branch in `handleMessage` (after the `ml_training` branch):

```javascript
  } else if (msg.type === 'screener_result') {
    dispatchScreenerResult(msg);
  }
```

- [ ] **Step 4: Pass through the `universe` config key in `layout.js`**

In `src/dashboard/static/js/layout.js`, in `restoreWorkspace()`'s `config` object literal, add a
`universe: w.universe,` line right after `hiddenSize: w.hiddenSize,` so a saved screener widget
restores its selected universe instead of always resetting to the `'sp500'` default:

```javascript
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
```

- [ ] **Step 5: Validate JS syntax (no bundler, no test harness — per project convention)**

Run each modified/created file through Node's syntax checker:

```bash
node --input-type=module --check < src/dashboard/static/js/screener.js
node --input-type=module --check < src/dashboard/static/js/widgets.js
node --input-type=module --check < src/dashboard/static/js/ws.js
node --input-type=module --check < src/dashboard/static/js/layout.js
```

Expected: no output (silent success) from all four.

- [ ] **Step 6: Manual browser pass**

Start the dashboard (`python -m uv run python main.py`), open `http://localhost:8080`, use "+ Add
View" to add a Screener widget, select a universe, click Run, confirm the status line updates
through progress stages and a results table renders sorted by score descending; click a column
header to confirm re-sorting works; click Stop mid-run and confirm the status line updates.

- [ ] **Step 7: Commit**

```bash
git add src/dashboard/static/js/screener.js src/dashboard/static/js/widgets.js \
        src/dashboard/static/js/ws.js src/dashboard/static/js/layout.js
git commit -m "feat(dashboard): add Screener widget (universe picker, Run/Stop, sortable results table)"
```

- [ ] **Step 8: Code review**

Dispatch a review of this diff (`code-review` skill at medium effort is sufficient — this is
pattern-following JS, lower risk than Task 6's concurrency code). Check specifically: `sortAsc`
toggling logic when switching columns (should reset to descending on a new column, matching
`score`'s initial default), and that `handleScreenerResult` doesn't throw if `msg.results` is
missing on a `"done"` message from a future/altered backend response shape (it already defaults to
`[]` via `msg.results || []` — confirm this is sufficient and not just accidentally correct).

---

### Task 8: Standalone CLI script — `scripts/run_screener.py`

**Files:**
- Create: `scripts/run_screener.py`
- Test: `tests/scripts/test_run_screener.py`

**Interfaces:**
- Consumes: `run_screen` from `src.screener.service` (Task 5).
- Produces: a CLI runnable as `python -m uv run python scripts/run_screener.py --universe sp500
  [--weights '{"momentum": ...}'] [--top 20]`. Writes the full ranked table to
  `screener_results_<universe>_<date>.csv` in the current working directory and prints the top N
  rows to stdout.

- [ ] **Step 1: Write the failing test**

Create `tests/scripts/test_run_screener.py`:

```python
from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from scripts import run_screener


def test_main_writes_csv_and_prints_top_n(monkeypatch: Any, tmp_path: Any, capsys: Any) -> None:
    df = pd.DataFrame(
        {"score": [95.0, 80.0, 60.0]}, index=["AAPL", "MSFT", "GOOG"]
    )

    def _fake_run_screen(universe: str, weights: Any = None, on_progress: Any = None) -> pd.DataFrame:
        return df

    monkeypatch.setattr(run_screener, "run_screen", _fake_run_screen)
    monkeypatch.chdir(tmp_path)

    run_screener.main(["--universe", "sp500", "--top", "2"])

    captured = capsys.readouterr()
    assert "AAPL" in captured.out
    assert "MSFT" in captured.out
    assert "GOOG" not in captured.out  # only top 2 printed

    csv_files = list(tmp_path.glob("screener_results_sp500_*.csv"))
    assert len(csv_files) == 1
    written = pd.read_csv(csv_files[0], index_col=0)
    assert list(written.index) == ["AAPL", "MSFT", "GOOG"]  # full table written, not just top N


def test_main_parses_weights_json(monkeypatch: Any, tmp_path: Any) -> None:
    captured_weights: dict[str, Any] = {}

    def _fake_run_screen(universe: str, weights: Any = None, on_progress: Any = None) -> pd.DataFrame:
        captured_weights["weights"] = weights
        return pd.DataFrame({"score": [1.0]}, index=["AAPL"])

    monkeypatch.setattr(run_screener, "run_screen", _fake_run_screen)
    monkeypatch.chdir(tmp_path)

    run_screener.main(["--universe", "sp500", "--weights", '{"momentum": 1.0}'])

    assert captured_weights["weights"] == {"momentum": 1.0}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m uv run pytest tests/scripts/test_run_screener.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.run_screener'`

- [ ] **Step 3: Write `scripts/run_screener.py`**

```python
from __future__ import annotations

import argparse
import datetime as _dt
import json

from src.screener.service import run_screen
from src.utils import get_logger

log = get_logger(__name__)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    weights = json.loads(args.weights) if args.weights else None

    result = run_screen(args.universe, weights=weights)

    today = _dt.datetime.now(_dt.UTC).date().isoformat()
    out_path = f"screener_results_{args.universe}_{today}.csv"
    result.to_csv(out_path)
    log.info("screener_results_written", path=out_path, symbols=len(result))

    print(result.head(args.top).to_string())


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the quant stock screener and write ranked results to CSV"
    )
    parser.add_argument("--universe", type=str, default="sp500", choices=["sp500", "broad"])
    parser.add_argument(
        "--weights", type=str, default=None,
        help='JSON string of factor weights, e.g. \'{"momentum": 0.5, "rel_strength": 0.5, '
             '"rsi": 0.0, "rel_volume": 0.0, "volatility": 0.0}\'',
    )
    parser.add_argument("--top", type=int, default=20, help="rows to print to stdout")
    return parser.parse_args(argv)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m uv run pytest tests/scripts/test_run_screener.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/run_screener.py tests/scripts/test_run_screener.py
git commit -m "feat: add standalone run_screener.py CLI script"
```

- [ ] **Step 6: Code review**

Dispatch `code-review` skill (medium effort) — mechanical CLI wrapper, cheaper-model-suitable.
Check specifically: the script doesn't call `asyncio.set_event_loop(asyncio.new_event_loop())`
before any `ib_insync`-adjacent import the way `main.py` and `backfill_history.py` do — confirm
this script has no `ib_insync` transitive import at all (it doesn't: `src.screener.service` only
imports pandas/numpy/yfinance) so the workaround genuinely isn't needed here, rather than assuming
it's fine without checking.

---

### Task 9: Final integration review

**Files:** none created — this is a verification-only task covering the whole `src/screener/`
package, `src/dashboard/app.py`'s screener additions, the JS widget, and the CLI script.

- [ ] **Step 1: Run the full test suite**

Run: `python -m uv run pytest -x -q`
Expected: all tests pass, including all `tests/screener/`, `tests/dashboard/test_screener_api.py`,
and `tests/scripts/test_run_screener.py` tests added in Tasks 1–8.

- [ ] **Step 2: Run mypy strict**

Run: `python -m uv run mypy src/ main.py`
Expected: no errors in `src/screener/` or the `src/dashboard/app.py` additions. Fix any typing
issues (e.g. missing return-type annotations, `Any` leaking where a concrete type is inferable)
before proceeding.

- [ ] **Step 3: Run ruff**

Run: `python -m uv run ruff check src/ main.py tests/ scripts/`
Expected: no violations in new/modified files.

- [ ] **Step 4: Dispatch a full-diff strong-model review**

Use the `code-review` skill at **high** effort (or `/code-review ultra` if the user wants the
multi-agent cloud review) over the entire branch diff for this feature, covering all of Tasks 1–8
together — this catches cross-task inconsistencies a per-task review can miss (e.g., a column name
drifting between `metrics.py`'s output and `scorer.py`'s expected input, or the JS results
payload's field names not matching `app.py`'s `row.to_dict()` output). Specifically re-verify:
- `compute_metrics`'s output columns (Task 2) exactly match `scorer.score`'s expected input
  columns (Task 4) and the JS table's expected fields (Task 7).
- The three open decisions the spec explicitly deferred to planning (chunk size, `_rsi`
  sharing-vs-duplication, ticker-list source) are each resolved and documented in this plan's
  Global Constraints — confirm no `TBD` slipped through.

- [ ] **Step 5: Manual end-to-end pass**

With `docker compose up -d` (TimescaleDB) and `python -m uv run python main.py` running, exercise
both the CLI (`python -m uv run python scripts/run_screener.py --universe sp500 --top 10`) and the
dashboard widget end-to-end, confirming the ranked results are directionally sane (e.g. a stock
with a strong recent uptrend scores above a flat one) — this is a sanity check on the real
yfinance data path, not just the mocked unit tests.

- [ ] **Step 6: Update `CLAUDE.md`'s module map**

Add `src/screener/` and `scripts/run_screener.py` entries to the module map in
`C:\Users\tshor\OneDrive\Desktop\Projects\Hedge\Hedge fund\CLAUDE.md`, following the existing
`src/ml/` entry's format, plus a one-line mention in the dashboard section listing `screener_result`
alongside the other WS message types.

- [ ] **Step 7: Final commit**

```bash
git add CLAUDE.md
git commit -m "docs: add stock screener to CLAUDE.md module map"
```
