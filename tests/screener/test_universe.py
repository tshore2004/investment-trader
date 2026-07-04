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
