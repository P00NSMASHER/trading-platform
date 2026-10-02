from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

from g2_candidate_route_matrix import classify, load_requirements

DEFAULT_REQUIREMENTS = Path(
    "data/processed/real_data_release_sprint/g2_champion_minimum_source_date_requirements.csv"
)

ROUTE_FILENAMES = {
    "candidate_tickdata_equity_trades": "tickdata_equity_trades.csv",
    "candidate_tickdata_equity_nbbo_quotes": "tickdata_equity_nbbo_quotes.csv",
    "candidate_databento_opra_trades": "databento_opra_trades.csv",
    "candidate_cboe_option_trades": "cboe_option_trades.csv",
    "candidate_lseg_opra_tick_history": "lseg_opra_tick_history.csv",
}

FIELDS = [
    "trade_date",
    "record_kind",
    "historical_symbols",
    "unique_symbol_count",
    "symbol_date_pair_count",
    "route",
]


def build_manifests(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    if len(rows) != 1242:
        raise ValueError(f"expected canonical champion-minimum 1242 rows, found {len(rows)}")

    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        route, _ = classify(row)
        if route not in ROUTE_FILENAMES:
            raise ValueError(f"unsupported route={route!r}")
        grouped[route].append(
            {
                "trade_date": row["trade_date"],
                "record_kind": row["record_kind"],
                "historical_symbols": row["historical_symbols"],
                "unique_symbol_count": row["unique_symbol_count"],
                "symbol_date_pair_count": row["symbol_date_pair_count"],
                "route": route,
            }
        )

    return {route: sorted(items, key=lambda r: (r["trade_date"], r["record_kind"]))
            for route, items in sorted(grouped.items())}


def write_manifests(rows: list[dict[str, str]], output_dir: Path) -> dict:
    grouped = build_manifests(rows)
    output_dir.mkdir(parents=True, exist_ok=True)

    routes = {}
    total_rows = 0
    total_pairs = 0
    for route, filename in ROUTE_FILENAMES.items():
        route_rows = grouped.get(route, [])
        path = output_dir / filename
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(route_rows)

        pair_count = sum(int(row["symbol_date_pair_count"]) for row in route_rows)
        routes[route] = {
            "file": filename,
            "source_date_rows": len(route_rows),
            "symbol_date_pair_count": pair_count,
        }
        total_rows += len(route_rows)
        total_pairs += pair_count

    summary = {
        "schema_version": "1",
        "purpose": (
            "Deterministic vendor request manifests for G2_CHAMPION_MINIMUM candidate sources. "
            "These files do not claim authorization, purchase, delivery, or G2 coverage."
        ),
        "champion_minimum_source_date_rows": total_rows,
        "total_record_kind_symbol_date_pairs": total_pairs,
        "routes": routes,
    }
    (output_dir / "vendor_request_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Write vendor-specific request manifests for G2_CHAMPION_MINIMUM."
    )
    parser.add_argument("--requirements", type=Path, default=DEFAULT_REQUIREMENTS)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    summary = write_manifests(load_requirements(args.requirements), args.output_dir)
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
