from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

DEFAULT_REQUIREMENTS = Path(
    "data/processed/real_data_release_sprint/g2_champion_minimum_source_date_requirements.csv"
)
HISTORICAL_START = "2010-01-01"


def load_requirements(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    required = {
        "record_kind",
        "trade_date",
        "historical_symbols",
        "unique_symbol_count",
        "symbol_date_pair_count",
    }
    if not rows:
        raise ValueError("requirements file is empty")
    missing = sorted(required - set(rows[0]))
    if missing:
        raise ValueError(f"requirements file missing columns: {missing}")
    return rows


def build_probe_manifest(rows: list[dict[str, str]]) -> dict:
    equity_rows = [row for row in rows if row["record_kind"] in {"equity_trade", "equity_quote"}]
    if not equity_rows:
        raise ValueError("requirements contain no equity_trade/equity_quote rows")

    grouped: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for row in equity_rows:
        grouped[row["trade_date"]][row["record_kind"]] = row

    dates = []
    for day_text in sorted(grouped):
        kinds = grouped[day_text]
        trade = kinds.get("equity_trade")
        quote = kinds.get("equity_quote")
        if trade is None or quote is None:
            raise ValueError(f"{day_text}: expected both equity_trade and equity_quote requirements")
        if trade["historical_symbols"] != quote["historical_symbols"]:
            raise ValueError(f"{day_text}: equity trade/quote symbol sets differ")

        symbols = [s for s in trade["historical_symbols"].split(";") if s]
        dates.append(
            {
                "trade_date": day_text,
                "historical_symbols": symbols,
                "symbol_date_pair_count": int(trade["symbol_date_pair_count"]),
                "requests": {
                    "equity_trade": {
                        "product": "Cboe Equity & ETF Trades",
                        "historical_start": HISTORICAL_START,
                        "g2_status": "candidate_direct_coverage",
                        "reason": (
                            "Current Cboe product documentation states 2010-present history and "
                            "provides trade price, size, venue, and NBBO at trade time. Production G2 "
                            "must still validate authorization, exact date, required symbols, canonical "
                            "trade fields, and source completeness."
                        ),
                    },
                    "equity_quote_interval": {
                        "product": "Cboe Equity & ETF Quotes",
                        "historical_start": HISTORICAL_START,
                        "g2_status": "fidelity_review_required_not_counted",
                        "reason": (
                            "Current Cboe product documentation describes interval snapshots with "
                            "bid/ask rather than every quote update. Frozen equity spread features are "
                            "currently computed from per-minute mean quote observations, so interval "
                            "quotes are not counted without a separate fidelity-equivalence proof."
                        ),
                    },
                },
            }
        )

    champion_total = len(rows) if len(rows) == 1242 else None
    trade_candidates = len(dates)
    return {
        "schema_version": "1",
        "purpose": (
            "Deterministic, no-purchase Cboe equity candidate plan for frozen G2 champion-minimum "
            "requirements. This manifest does not claim G2 coverage."
        ),
        "historical_start": HISTORICAL_START,
        "total_required_equity_dates": len(dates),
        "equity_trade_candidate_rows": trade_candidates,
        "equity_quote_interval_rows_not_counted": len(dates),
        "equity_symbol_date_pairs": sum(r["symbol_date_pair_count"] for r in dates),
        "champion_minimum_total_rows": champion_total,
        "candidate_champion_minimum_rows": trade_candidates if champion_total else None,
        "remaining_champion_minimum_rows_after_equity_trades": (
            champion_total - trade_candidates if champion_total else None
        ),
        "dates": dates,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a no-purchase Cboe equity candidate plan for frozen G2 requirements."
    )
    parser.add_argument("--requirements", type=Path, default=DEFAULT_REQUIREMENTS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    manifest = build_probe_manifest(load_requirements(args.requirements))
    rendered = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
