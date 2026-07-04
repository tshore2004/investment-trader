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
