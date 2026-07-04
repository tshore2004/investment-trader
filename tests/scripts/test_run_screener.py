from __future__ import annotations

from typing import Any

import pandas as pd

from scripts import run_screener


def test_main_writes_csv_and_prints_top_n(
    monkeypatch: Any, tmp_path: Any, capsys: Any
) -> None:
    df = pd.DataFrame(
        {"score": [95.0, 80.0, 60.0]}, index=["AAPL", "MSFT", "GOOG"]
    )

    def _fake_run_screen(
        universe: str, weights: Any = None, on_progress: Any = None
    ) -> pd.DataFrame:
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

    def _fake_run_screen(
        universe: str, weights: Any = None, on_progress: Any = None
    ) -> pd.DataFrame:
        captured_weights["weights"] = weights
        return pd.DataFrame({"score": [1.0]}, index=["AAPL"])

    monkeypatch.setattr(run_screener, "run_screen", _fake_run_screen)
    monkeypatch.chdir(tmp_path)

    run_screener.main(["--universe", "sp500", "--weights", '{"momentum": 1.0}'])

    assert captured_weights["weights"] == {"momentum": 1.0}
