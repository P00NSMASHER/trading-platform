from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

DEFAULT_REQUIREMENTS = Path(
    "data/processed/real_data_release_sprint/g2_champion_minimum_source_date_requirements.csv"
)
HIGH_QUALITY_START = "2014-01-01"


def load_requirements(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    required = {
        "record_kind",
        "trade_date",
        "historical_symbols",
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
        raise ValueError("requirements contain no equity rows")

    grouped: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for row in equity_rows:
        grouped[row["trade_date"]][row["record_kind"]] = row

    eligible = []
    ineligible = []
    for day_text in sorted(grouped):
        kinds = grouped[day_text]
        trade = kinds.get("equity_trade")
        quote = kinds.get("equity_quote")
        if trade is None or quote is None:
            raise ValueError(f"{day_text}: expected both equity_trade and equity_quote requirements")
        if trade["historical_symbols"] != quote["historical_symbols"]:
            raise ValueError(f"{day_text}: equity trade/quote symbol sets differ")

        item = {
            "trade_date": day_text,
            "historical_symbols": [s for s in trade["historical_symbols"].split(";") if s],
            "symbol_date_pair_count": int(trade["symbol_date_pair_count"]),
            "candidate_rows": 2,
            "g2_status": (
                "candidate_exact_semantics"
                if day_text >= HIGH_QUALITY_START
                else "outside_current_high_quality_history"
            ),
            "reason": (
                "Nasdaq U.S. Equity Tick History is consolidated Level-1 tick data with "
                "tick-by-tick quotes and trades; current product documentation states high-quality "
                "history back to Jan 2014. Production G2 must still validate license, exact date, "
                "required symbols, canonical fields, and source completeness."
            ),
        }
        (eligible if day_text >= HIGH_QUALITY_START else ineligible).append(item)

    champion_total = len(rows) if len(rows) == 1242 else None
    candidate_rows = 2 * len(eligible)
    return {
        "schema_version": "1",
        "purpose": (
            "Deterministic, no-purchase Nasdaq U.S. Equity Tick History candidate plan for "
            "G2_CHAMPION_MINIMUM. This manifest does not claim G2 coverage."
        ),
        "high_quality_history_start": HIGH_QUALITY_START,
        "total_required_equity_dates": len(grouped),
        "eligible_equity_dates": len(eligible),
        "ineligible_pre_2014_equity_dates": len(ineligible),
        "eligible_equity_source_date_rows": candidate_rows,
        "eligible_equity_symbol_date_pairs": sum(x["symbol_date_pair_count"] for x in eligible),
        "ineligible_pre_2014_symbol_date_pairs": sum(x["symbol_date_pair_count"] for x in ineligible),
        "champion_minimum_total_rows": champion_total,
        "candidate_champion_minimum_rows": candidate_rows if champion_total else None,
        "remaining_champion_minimum_rows_after_nasdaq_tick_history": (
            champion_total - candidate_rows if champion_total else None
        ),
        "eligible": eligible,
        "ineligible_dates": [x["trade_date"] for x in ineligible],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a no-purchase Nasdaq equity tick-history candidate plan."
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
