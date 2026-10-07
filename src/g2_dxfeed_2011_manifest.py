from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

DEFAULT_REQUIREMENTS = Path(
    "data/processed/real_data_release_sprint/g2_option_source_date_requirements.csv"
)
CUTOFF = "2012-01-01"
EXPECTED_DATES = 105
EXPECTED_PAIRS = 464


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("requirements file is empty")
    required = {
        "record_kind",
        "trade_date",
        "historical_symbols",
        "unique_symbol_count",
        "symbol_date_pair_count",
    }
    missing = required - set(rows[0])
    if missing:
        raise ValueError(f"requirements file missing columns: {sorted(missing)}")
    return rows


def build_manifest(rows: list[dict[str, str]]) -> dict:
    by_kind: dict[str, dict[str, set[str]]] = {
        "option_trade": {},
        "option_quote": {},
    }

    for row in rows:
        kind = row["record_kind"]
        if kind not in by_kind:
            continue
        date = row["trade_date"]
        if not date or date >= CUTOFF:
            continue
        symbols = {s for s in row["historical_symbols"].split(";") if s}
        expected_unique = int(row["unique_symbol_count"])
        expected_pairs = int(row["symbol_date_pair_count"])
        if len(symbols) != expected_unique or len(symbols) != expected_pairs:
            raise ValueError(f"{date}/{kind}: symbol-count mismatch")
        if date in by_kind[kind]:
            raise ValueError(f"{date}/{kind}: duplicate source-date row")
        by_kind[kind][date] = symbols

    trade_dates = set(by_kind["option_trade"])
    quote_dates = set(by_kind["option_quote"])
    if trade_dates != quote_dates:
        raise ValueError("2011 option trade/quote date sets differ")
    dates = sorted(trade_dates)
    if len(dates) != EXPECTED_DATES:
        raise ValueError(f"expected {EXPECTED_DATES} 2011 dates, found {len(dates)}")

    tasks: list[dict[str, object]] = []
    for date in dates:
        trade_symbols = by_kind["option_trade"][date]
        quote_symbols = by_kind["option_quote"][date]
        if trade_symbols != quote_symbols:
            raise ValueError(f"{date}: option trade/quote symbol sets differ")
        for symbol in sorted(trade_symbols):
            tasks.append(
                {
                    "trade_date": date,
                    "historical_symbol": symbol,
                    "required_record_kinds": "option_trade;option_quote",
                    "candidate_route": "dxfeed_historical_options",
                    "delivery_request": "targeted_historical_tick_extract",
                    "authorization_required": True,
                    "retention_rights_required": True,
                    "validated_coverage": False,
                }
            )

    if len(tasks) != EXPECTED_PAIRS:
        raise ValueError(
            f"expected {EXPECTED_PAIRS} 2011 underlying/date pairs, found {len(tasks)}"
        )
    if len({(row["trade_date"], row["historical_symbol"]) for row in tasks}) != len(tasks):
        raise ValueError("duplicate 2011 underlying/date task")

    return {
        "schema_version": "1",
        "purpose": (
            "Deterministic vendor-ready request manifest for the unresolved 2011 G2 "
            "option residual. It requests both tick option trades and tick option quotes "
            "for each frozen underlying/date pair and makes no entitlement, delivery, "
            "retention, validation, or G2 coverage claim."
        ),
        "vendor_candidate": "dxFeed",
        "date_floor": dates[0],
        "date_ceiling": dates[-1],
        "source_date_count": len(dates),
        "underlying_date_pair_count": len(tasks),
        "unique_historical_underlyings": len(
            {str(row["historical_symbol"]) for row in tasks}
        ),
        "required_record_kinds": ["option_trade", "option_quote"],
        "source_contract": str(DEFAULT_REQUIREMENTS),
        "authorization_required": True,
        "retention_rights_required": True,
        "validated_coverage_change": 0,
        "tasks": tasks,
    }


def write_manifest(payload: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    tasks = list(payload["tasks"])
    csv_path = output_dir / "dxfeed_2011_option_tasks.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = [
            "trade_date",
            "historical_symbol",
            "required_record_kinds",
            "candidate_route",
            "delivery_request",
            "authorization_required",
            "retention_rights_required",
            "validated_coverage",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(tasks)

    summary = {k: v for k, v in payload.items() if k != "tasks"}
    (output_dir / "dxfeed_2011_option_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the exact fail-closed dxFeed request manifest for 2011 G2 options."
    )
    parser.add_argument("--requirements", type=Path, default=DEFAULT_REQUIREMENTS)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    payload = build_manifest(_read(args.requirements))
    if args.output_dir:
        write_manifest(payload, args.output_dir)
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
