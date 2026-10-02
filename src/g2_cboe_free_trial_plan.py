from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

DEFAULT_REQUIREMENTS = Path(
    "data/processed/real_data_release_sprint/g2_champion_minimum_source_date_requirements.csv"
)
POINTS_PER_HISTORICAL_REQUEST = 15
FREE_POINTS_PER_DAY = 500
FREE_TRIAL_DAYS = 14
MAX_ROWS_PER_REQUEST = 10_000
MAX_REQUESTS_PER_DAY = FREE_POINTS_PER_DAY // POINTS_PER_HISTORICAL_REQUEST
MAX_TRIAL_REQUESTS = MAX_REQUESTS_PER_DAY * FREE_TRIAL_DAYS


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


def _choose_residual_dates(rows: list[dict[str, object]], request_capacity: int) -> list[dict[str, object]]:
    total = sum(int(r["request_count"]) for r in rows)
    need_to_drop = max(0, total - request_capacity)
    if need_to_drop == 0:
        return []

    # DP by dropped request count. For each sum keep the best tuple:
    # fewest residual dates first, then lexicographically earliest residual dates.
    dp: dict[int, tuple[int, tuple[str, ...]]] = {0: (0, ())}
    by_date = {str(r["trade_date"]): r for r in rows}
    for row in rows:
        n = int(row["request_count"])
        day = str(row["trade_date"])
        nxt = dict(dp)
        for s, (count, dates) in dp.items():
            ns = s + n
            cand = (count + 1, tuple(sorted((*dates, day))))
            prev = nxt.get(ns)
            if prev is None or cand < prev:
                nxt[ns] = cand
        dp = nxt

    feasible = [(s, payload) for s, payload in dp.items() if s >= need_to_drop]
    if not feasible:
        raise AssertionError("unable to select residual dates")
    dropped_sum, (_, dates) = min(feasible, key=lambda x: (x[1][0], x[0], x[1][1]))
    assert dropped_sum >= need_to_drop
    return [by_date[d] for d in dates]


def build_plan(rows: list[dict[str, object]], *, reserved_requests: int) -> dict:
    if reserved_requests < 0 or reserved_requests >= MAX_TRIAL_REQUESTS:
        raise ValueError("reserved_requests out of range")
    capacity = MAX_TRIAL_REQUESTS - reserved_requests
    residual = _choose_residual_dates(rows, capacity)
    residual_dates = {str(r["trade_date"]) for r in residual}
    covered = [r for r in rows if str(r["trade_date"]) not in residual_dates]

    first_page_requests = sum(int(r["request_count"]) for r in covered)
    residual_pairs = sum(int(r["request_count"]) for r in residual)
    request_rows = []
    day_index = 1
    used_today = 0
    for row in covered:
        for symbol in row["symbols"]:
            if used_today >= MAX_REQUESTS_PER_DAY:
                day_index += 1
                used_today = 0
            request_rows.append(
                {
                    "trial_day": day_index,
                    "trade_date": row["trade_date"],
                    "symbol": symbol,
                    "points": POINTS_PER_HISTORICAL_REQUEST,
                    "limit": MAX_ROWS_PER_REQUEST,
                    "seq_no": 0,
                }
            )
            used_today += 1

    return {
        "free_trial": {
            "points_per_day": FREE_POINTS_PER_DAY,
            "trial_days": FREE_TRIAL_DAYS,
            "points_per_historical_request": POINTS_PER_HISTORICAL_REQUEST,
            "max_first_page_requests_per_day": MAX_REQUESTS_PER_DAY,
            "max_trial_requests": MAX_TRIAL_REQUESTS,
            "page_limit_rows": MAX_ROWS_PER_REQUEST,
        },
        "reserved_requests_for_pagination": reserved_requests,
        "scheduled_first_page_requests": first_page_requests,
        "scheduled_points": first_page_requests * POINTS_PER_HISTORICAL_REQUEST,
        "covered_source_dates": len(covered),
        "residual_source_dates": len(residual),
        "residual_symbol_date_pairs": residual_pairs,
        "residual": residual,
        "requests": request_rows,
        "warning": (
            "This is a planning upper bound, not G2 coverage. Any symbol/date returning more than "
            "10,000 rows requires additional 15-point pagination requests. Trial/API eligibility, "
            "authorization, response completeness, and production validation must all pass."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan Cboe All Access free-trial coverage for 2011 G2 option trades.")
    parser.add_argument("--requirements", type=Path, default=DEFAULT_REQUIREMENTS)
    parser.add_argument("--reserved-requests", type=int, default=46)
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
