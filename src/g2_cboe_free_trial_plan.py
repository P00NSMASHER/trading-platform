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
PUBLISHED_TRIAL_POINTS_PER_DAY = 500
PUBLISHED_TRIAL_OVERAGE_AVAILABLE = False
MAX_FIRST_PAGE_REQUESTS_PER_DAY = (
    PUBLISHED_TRIAL_POINTS_PER_DAY // POINTS_PER_HISTORICAL_REQUEST
)
MAX_FIRST_PAGE_REQUESTS_OVER_TRIAL = MAX_FIRST_PAGE_REQUESTS_PER_DAY * FREE_TRIAL_DAYS


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


def _maximize_complete_dates(
    rows: list[dict[str, object]],
    budget: int = MAX_FIRST_PAGE_REQUESTS_OVER_TRIAL,
) -> tuple[list[dict[str, object]], int]:
    ranked = sorted(
        rows,
        key=lambda r: (int(r["request_count"]), str(r["trade_date"])),
    )
    chosen = []
    used = 0
    for row in ranked:
        cost = int(row["request_count"])
        if used + cost > budget:
            continue
        chosen.append(row)
        used += cost
    return chosen, used


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
    selected, selected_pairs = _maximize_complete_dates(eligible)
    selected_dates = sorted(str(r["trade_date"]) for r in selected)

    if len(selected) != 180 or selected_pairs != 460:
        raise ValueError(
            "frozen Cboe trade-only trial optimum drifted: "
            f"dates={len(selected)} pairs={selected_pairs}"
        )

    return {
        "schema_version": "3",
        "vendor_confirmed_opra_start": VENDOR_CONFIRMED_OPRA_START.isoformat(),
        "free_trial_days": FREE_TRIAL_DAYS,
        "published_trial_points_per_day": PUBLISHED_TRIAL_POINTS_PER_DAY,
        "published_trial_overage_available": PUBLISHED_TRIAL_OVERAGE_AVAILABLE,
        "daily_credit_limit_enforced_for_plan": True,
        "daily_credit_limit_basis": (
            "Current Cboe All Access product page lists 500 points/day for the free trial, "
            "overage rates N/A, and says trial subscriptions cannot use overage. Ryan Lusk's "
            "2026-10-02 instruction to select Allow is retained as vendor guidance, but it is "
            "not treated as proof that the trial can exceed the published daily cap."
        ),
        "max_first_page_requests_per_day": MAX_FIRST_PAGE_REQUESTS_PER_DAY,
        "max_first_page_requests_over_trial": MAX_FIRST_PAGE_REQUESTS_OVER_TRIAL,
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
        "candidate_request_universe": requests,
        "candidate_request_universe_count": len(requests),
        "free_trial_trade_only_optimum": {
            "complete_source_dates": len(selected),
            "underlying_date_pairs": selected_pairs,
            "selected_dates": selected_dates,
            "remaining_source_dates": len(eligible) - len(selected),
            "remaining_underlying_date_pairs": eligible_pairs - selected_pairs,
            "note": (
                "Optimistic first-page option-trade-only ceiling. Pagination and any "
                "reference/options, quote, retry, or other API requests reduce this capacity."
            ),
        },
        "warning": (
            "Planning only, not G2 coverage. No 2011 request is emitted. The candidate "
            "universe contains all vendor-floor-eligible requests, but the current published "
            "free-trial cap can fund at most 462 15-point first pages, which optimally closes "
            "180 complete option-trade source dates / 460 underlying-date pairs before any "
            "pagination or quote acquisition. Runtime access, rate limits, retention rights, "
            "response completeness, and production validation remain fail-closed."
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
