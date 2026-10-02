from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

DEFAULT_REQUIREMENTS = Path(
    "data/processed/real_data_release_sprint/g2_champion_minimum_source_date_requirements.csv"
)


def load_requirements(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    required = {"record_kind", "trade_date"}
    if not rows:
        raise ValueError("requirements file is empty")
    missing = sorted(required - set(rows[0]))
    if missing:
        raise ValueError(f"requirements file missing columns: {missing}")
    return rows


def classify(row: dict[str, str]) -> tuple[str, str]:
    kind = row["record_kind"]
    day = row["trade_date"]

    if kind == "equity_trade":
        return (
            "candidate_tickdata_equity_trades",
            "Tick Data U.S. Equities currently provides tick-by-tick trades across the full "
            "frozen date range; still requires license and production content validation.",
        )
    if kind == "equity_quote":
        return (
            "candidate_tickdata_equity_nbbo_quotes",
            "Tick Data NBBO for U.S. Equities currently provides tick-by-tick consolidated "
            "NBBO quotes back to Jan 2004, covering the full frozen date range; still "
            "requires license and production content validation.",
        )
    if kind == "option_trade":
        if day >= "2013-04-01":
            return (
                "candidate_databento_opra_trades",
                "Databento OPRA trades candidate for 2013-04-01 onward; still requires "
                "license and production content validation.",
            )
        if day >= "2012-01-01":
            return (
                "candidate_cboe_option_trades",
                "Cboe Option Trades current self-service product states Jan 2012 onward; "
                "still requires license and production content validation.",
            )
        return (
            "candidate_lseg_opra_tick_history",
            "LSEG OPRA currently documents Tick History from 1997 with last-sale content and "
            "licensed full-tick workflows, covering the 2011 frozen dates; still requires "
            "license and production content validation.",
        )
    raise ValueError(f"unsupported champion-minimum record_kind={kind!r}")


def build_matrix(rows: list[dict[str, str]]) -> dict:
    if len(rows) != 1242:
        raise ValueError(f"expected canonical champion-minimum 1242 rows, found {len(rows)}")

    classified = []
    counts = Counter()
    unresolved = Counter()
    for row in rows:
        route, reason = classify(row)
        counts[route] += 1
        if route.startswith("unresolved_"):
            unresolved[row["record_kind"]] += 1
        classified.append(
            {
                "trade_date": row["trade_date"],
                "record_kind": row["record_kind"],
                "route": route,
                "reason": reason,
            }
        )

    candidate_rows = sum(v for k, v in counts.items() if k.startswith("candidate_"))
    unresolved_rows = len(rows) - candidate_rows
    return {
        "schema_version": "1",
        "purpose": (
            "Conservative no-purchase candidate-route matrix for G2_CHAMPION_MINIMUM. "
            "Candidate does not mean covered; authorization and production validation remain required."
        ),
        "champion_minimum_rows": len(rows),
        "candidate_rows": candidate_rows,
        "candidate_fraction": candidate_rows / len(rows),
        "unresolved_rows": unresolved_rows,
        "route_counts": dict(sorted(counts.items())),
        "unresolved_by_record_kind": dict(sorted(unresolved.items())),
        "rows": classified,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the conservative G2 champion-minimum candidate-route matrix."
    )
    parser.add_argument("--requirements", type=Path, default=DEFAULT_REQUIREMENTS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    manifest = build_matrix(load_requirements(args.requirements))
    rendered = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
