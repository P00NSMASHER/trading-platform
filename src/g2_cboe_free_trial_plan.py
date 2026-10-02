from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path

DEFAULT_REQUIREMENTS = Path(
    "data/processed/real_data_release_sprint/g2_champion_minimum_source_date_requirements.csv"
)
VENDOR_CONFIRMED_OPRA_START = date(2012, 1, 1)
POINTS_PER_HISTORICAL_REQUEST = 15
MAX_ROWS_PER_REQUEST = 10_000
FREE_TRIAL_DAYS = 14


def load_option_trade_requirements(path: Path) -> list[dict[str, object]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    required = {"record_kind", "trade_date", "historical_symbols", "unique_symbol_count"}
    if not rows:
        raise ValueError("requirements file is empty")
    missing = required - set(rows[0])
    if missing:
        raise ValueError(f"requirements file missing columns: {sorted(missing)}")

    out = []
    for row in rows:
        if row["record_kind"] != "option_trade":
            continue
        symbols = [s for s in row["historical_symbols"].split(";") if s]
        count = int(row["unique_symbol_count"])
        if count != len(symbols):
            raise ValueError(f'{row["trade_date"]}: symbol count mismatch')
        out.append(
            {
                "trade_date": row["trade_date"],
                "symbols": symbols,
                "request_count": count,
            }
        )
    return sorted(out, key=lambda r: str(r["trade_date"]))


def build_plan(rows: list[dict[str, object]]) -> dict:
    eligible = []
    ineligible = []
    requests = []

    for row in rows:
        trade_date = date.fromisoformat(str(row["trade_date"]))
        target = eligible if trade_date >= VENDOR_CONFIRMED_OPRA_START else ineligible
        target.append(row)

        if trade_date < VENDOR_CONFIRMED_OPRA_START:
            continue

        for symbol in row["symbols"]:
            requests.append(
                {
                    "trade_date": row["trade_date"],
                    "symbol": symbol,
                    "points_per_historical_request": POINTS_PER_HISTORICAL_REQUEST,
                    "limit": MAX_ROWS_PER_REQUEST,
                    "seq_no": 0,
                }
            )

    eligible_pairs = sum(int(r["request_count"]) for r in eligible)
    ineligible_pairs = sum(int(r["request_count"]) for r in ineligible)

    return {
        "schema_version": "2",
        "vendor_confirmed_opra_start": VENDOR_CONFIRMED_OPRA_START.isoformat(),
        "free_trial_days": FREE_TRIAL_DAYS,
        "daily_credit_limit_enforced_for_plan": False,
        "daily_credit_limit_basis": (
            "Ryan Lusk, Cboe Data Vantage, 2026-10-02: historical data should be "
            "available via the API; select Allow for exceeding the daily credit limit, "
            "which does not matter during the trial phase."
        ),
        "eligible_source_dates": len(eligible),
        "eligible_symbol_date_pairs": eligible_pairs,
        "ineligible_pre_2012_source_dates": len(ineligible),
        "ineligible_pre_2012_symbol_date_pairs": ineligible_pairs,
        "ineligible_pre_2012_first_date": (
            str(ineligible[0]["trade_date"]) if ineligible else None
        ),
        "ineligible_pre_2012_last_date": (
            str(ineligible[-1]["trade_date"]) if ineligible else None
        ),
        "requests": requests,
        "warning": (
            "Planning only, not G2 coverage. Cboe vendor-confirmed OPRA history begins "
            "in 2012, so no 2011 request is emitted. A minimal authorized historical "
            "acceptance probe must pass before bulk retrieval. Pagination, endpoint "
            "rate limits, authorization, licensing, response completeness, and "
            "production validation remain fail-closed."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Plan vendor-eligible Cboe All Access free-trial G2 option-trade requests "
            "without ever routing pre-2012 dates to Cboe."
        )
    )
    parser.add_argument("--requirements", type=Path, default=DEFAULT_REQUIREMENTS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    plan = build_plan(load_option_trade_requirements(args.requirements))
    rendered = json.dumps(plan, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
