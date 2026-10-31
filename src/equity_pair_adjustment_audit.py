"""Audit whether ex-post adjusted closes change historical pair signal membership.

Research-only: no API calls, orders, prices, data downloads, or credentials.
The user supplies separate, immutable Git-blob-authenticated SPY and QQQ CSVs.
This is a source-sensitivity *diagnostic*, never a second tradable strategy.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import date
from pathlib import Path

from equity_pair_divergence_audit import (
    RELATIVE_LAG_THRESHOLD,
    compute_pairs,
)
from equity_reversal_audit import Bar, InvalidPriceEvidence, phase, read_bars

COST_BPS = (10.0, 20.0, 40.0)


def audit_adjustment_sensitivity(
    spy_bars: list[Bar], qqq_bars: list[Bar]
) -> dict:
    """Compare frozen 5-session adjusted-vs-raw *signal selection*, never tune.

    Always run the existing fail-closed pair calendar and OHLC validation.
    Both variants use exclusively the session T-1 and T-6 closes to decide
    whether T qualifies; T open/close is used only for hypothetical payoff.
    """
    trials = compute_pairs(spy_bars, qqq_bars)
    s = {b.day: b for b in spy_bars}
    q = {b.day: b for b in qqq_bars}
    common_days = [b.day for b in spy_bars if b.day in q]
    index = {day: i for i, day in enumerate(common_days)}
    selected: dict[str, list[dict]] = {
        "train": [], "validation": [], "holdout": [],
    }
    for trial in trials:
        i = index[trial.day]
        if i < 6:  # Defensive: the upstream audit requires six full lag bars.
            raise InvalidPriceEvidence("Incomplete strictly prior lookback.")
        prior, old = common_days[i - 1], common_days[i - 6]
        raw_prices = (s[prior].close, s[old].close, q[prior].close, q[old].close)
        if not all(math.isfinite(x) and x > 0 for x in raw_prices):
            raise InvalidPriceEvidence("Invalid raw close in source sensitivity.")
        raw_lag = q[prior].close / q[old].close - s[prior].close / s[old].close
        if not math.isfinite(raw_lag):
            raise InvalidPriceEvidence("Nonfinite raw lag.")
        selected[phase(trial.day)].append({
            "day": trial.day,
            "adjusted": trial.prior_5session_qqq_minus_spy <= -RELATIVE_LAG_THRESHOLD,
            "raw": raw_lag <= -RELATIVE_LAG_THRESHOLD,
            "gross_bps": 5000.0 * trial.intraday_qqq_minus_spy,
        })

    def mean_net(rows: list[dict], key: str, cost: float) -> float | None:
        picked = [x["gross_bps"] for x in rows if x[key]]
        return round(sum(picked) / len(picked) - cost, 3) if picked else None

    out: dict = {
        "protocol": "FROZEN_5SESSION_PAIR_ADJUSTED_CLOSE_SENSITIVITY",
        "status": "DIAGNOSTIC_NOT_AN_EXECUTABLE_STRATEGY",
        "cost_units": "bps_of_gross_pair_notional_per_roundtrip",
        "phases": {},
    }
    for label, rows in selected.items():
        different = [x for x in rows if x["adjusted"] != x["raw"]]
        out["phases"][label] = {
            "eligible_sessions": len(rows),
            "adjusted_selected": sum(x["adjusted"] for x in rows),
            "raw_selected": sum(x["raw"] for x in rows),
            "disagreements": len(different),
            "adjusted_only": sum(x["adjusted"] for x in different),
            "raw_only": sum(x["raw"] for x in different),
            "disagreement_days": [x["day"].isoformat() for x in different],
            "mean_net_bps": {
                str(int(cost)): {
                    "adjusted": mean_net(rows, "adjusted", cost),
                    "raw": mean_net(rows, "raw", cost),
                } for cost in COST_BPS
            },
        }
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spy-file", type=Path, required=True)
    parser.add_argument("--qqq-file", type=Path, required=True)
    parser.add_argument("--spy-git-blob-sha", required=True)
    parser.add_argument("--qqq-git-blob-sha", required=True)
    args = parser.parse_args()
    result = audit_adjustment_sensitivity(
        read_bars(args.spy_file, args.spy_git_blob_sha),
        read_bars(args.qqq_file, args.qqq_git_blob_sha),
    )
    result["pinned_input_blobs"] = {
        "SPY": args.spy_git_blob_sha,
        "QQQ": args.qqq_git_blob_sha,
    }
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
