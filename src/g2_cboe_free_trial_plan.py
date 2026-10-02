from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

DEFAULT_REQUIREMENTS = Path(
    "data/processed/real_data_release_sprint/g2_champion_minimum_source_date_requirements.csv"
)

VENDOR_CONFIRMED_OPRA_EARLIEST_YEAR = 2012
VENDOR_HISTORY_REPLY_DATE = "2026-09-30"
VENDOR_TRIAL_CONFIRMATION_DATE = "2026-10-02"


def load_2011_option_requirements(path: Path) -> list[dict[str, object]]:
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
        if row["record_kind"] != "option_trade" or not row["trade_date"].startswith("2011-"):
            continue
        symbols = [s for s in row["historical_symbols"].split(";") if s]
        count = int(row["unique_symbol_count"])
        if count != len(symbols):
            raise ValueError(f'{row["trade_date"]}: symbol count mismatch')
        out.append({"trade_date": row["trade_date"], "symbols": symbols, "request_count": count})
    return sorted(out, key=lambda r: r["trade_date"])


def build_plan(rows: list[dict[str, object]], *, reserved_requests: int = 0) -> dict:
    if reserved_requests < 0:
        raise ValueError("reserved_requests must be >= 0")
    if not rows:
        raise ValueError("expected frozen 2011 option-trade rows")
    if any(not str(row["trade_date"]).startswith("2011-") for row in rows):
        raise ValueError("legacy fail-closed planner accepts only 2011 option-trade rows")

    pair_count = sum(int(row["request_count"]) for row in rows)
    return {
        "schema_version": "2",
        "purpose": (
            "Fail-closed audit receipt for the frozen 2011 G2 option-trade slice. "
            "Cboe Data Vantage confirmed OPRA-related datasets begin in 2012, so this "
            "legacy Cboe trial plan schedules no 2011 requests."
        ),
        "vendor_provenance": {
            "vendor_confirmed_opra_earliest_year": VENDOR_CONFIRMED_OPRA_EARLIEST_YEAR,
            "history_reply_date": VENDOR_HISTORY_REPLY_DATE,
            "trial_confirmation_date": VENDOR_TRIAL_CONFIRMATION_DATE,
            "reason": "Cboe Data Vantage states OPRA-related datasets are available from 2012 onward.",
        },
        "frozen_2011_scope": {
            "source_date_rows": len(rows),
            "underlying_date_pairs": pair_count,
            "first_trade_date": str(rows[0]["trade_date"]),
            "last_trade_date": str(rows[-1]["trade_date"]),
        },
        "cboe_eligible": False,
        "scheduled_first_page_requests": 0,
        "scheduled_points": 0,
        "covered_source_dates": 0,
        "residual_source_dates": len(rows),
        "residual_symbol_date_pairs": pair_count,
        "residual": rows,
        "requests": [],
        "reserved_requests_for_pagination": reserved_requests,
        "coverage_claimed": False,
        "warning": (
            "Do not activate or use the Cboe All Access trial for these 2011 OPRA rows. "
            "Use a pre-2012-capable source such as the separately tracked LSEG/NxCore candidate "
            "and require license plus production content validation before any G2 coverage claim."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Emit a fail-closed Cboe receipt for the unsupported 2011 G2 option-trade slice."
    )
    parser.add_argument("--requirements", type=Path, default=DEFAULT_REQUIREMENTS)
    parser.add_argument("--reserved-requests", type=int, default=0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    rows = load_2011_option_requirements(args.requirements)
    plan = build_plan(rows, reserved_requests=args.reserved_requests)
    rendered = json.dumps(plan, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
