from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

DEFAULT_RESIDUAL = Path(
    "data/processed/g2_vendor_requests/cheap_route_partitions/residual_equity.csv"
)
DEFAULT_OUTPUT_DIR = Path(
    "data/processed/g2_vendor_requests/combined_equity_cheap_route"
)

FIRST_RATE_ACTIVE_LIST_URL = "https://firstratedata.com/stock-data/individual-tickers"
AUDIT_AS_OF = "2026-10-02"

# Public active-ticker listing matches that are inside the ThetaData residual.
# ThetaData-covered XNAS symbols are intentionally excluded here so the two routes
# never double-count a frozen symbol/date pair.
FIRST_RATE_RESIDUAL_MATCHES = frozenset(
    {
        "AMD", "AMP", "BA", "CAT", "CB", "DE", "EW", "F", "FL", "FLR",
        "GME", "GT", "HBI", "HON", "IDXX", "JNPR", "JWN", "MKC", "NKE",
        "NOW", "NVR", "PBI", "PLL", "PRU", "R", "ROL", "STT", "TER",
        "THC", "TXT", "URI",
    }
)

OUTPUT_FIELDS = [
    "record_kind",
    "trade_date",
    "historical_symbols",
    "unique_symbol_count",
    "symbol_date_pair_count",
    "route",
]


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"{path}: empty CSV")
    required = {"record_kind", "trade_date", "historical_symbols"}
    missing = sorted(required - set(rows[0]))
    if missing:
        raise ValueError(f"{path}: missing columns {missing}")
    return rows


def _row(source: dict[str, str], symbols: list[str], route: str) -> dict[str, str]:
    return {
        "record_kind": source["record_kind"],
        "trade_date": source["trade_date"],
        "historical_symbols": ";".join(symbols),
        "unique_symbol_count": str(len(symbols)),
        "symbol_date_pair_count": str(len(symbols)),
        "route": route,
    }


def build(residual_rows: list[dict[str, str]]) -> tuple[dict[str, list[dict[str, str]]], dict]:
    first_rate: list[dict[str, str]] = []
    tickdata_residual: list[dict[str, str]] = []

    first_rate_pairs = {"equity_trade": 0, "equity_quote": 0}
    tickdata_pairs = {"equity_trade": 0, "equity_quote": 0}
    first_rate_dates_touched = {"equity_trade": 0, "equity_quote": 0}
    first_rate_dates_fully_cover_residual = {"equity_trade": 0, "equity_quote": 0}

    for source in residual_rows:
        kind = source["record_kind"]
        if kind not in {"equity_trade", "equity_quote"}:
            raise ValueError(f"unsupported record_kind={kind!r}")

        symbols = [s for s in source["historical_symbols"].split(";") if s]
        matched = [s for s in symbols if s in FIRST_RATE_RESIDUAL_MATCHES]
        remaining = [s for s in symbols if s not in FIRST_RATE_RESIDUAL_MATCHES]

        if matched:
            first_rate.append(_row(source, matched, "candidate_firstrate_tickhistory"))
            first_rate_pairs[kind] += len(matched)
            first_rate_dates_touched[kind] += 1
            if len(matched) == len(symbols):
                first_rate_dates_fully_cover_residual[kind] += 1

        if remaining:
            tickdata_residual.append(
                _row(source, remaining, "candidate_tickdata_equity_residual")
            )
            tickdata_pairs[kind] += len(remaining)

    residual_trade_rows = [r for r in tickdata_residual if r["record_kind"] == "equity_trade"]
    residual_symbols = sorted(
        {
            symbol
            for row in residual_trade_rows
            for symbol in row["historical_symbols"].split(";")
            if symbol
        }
    )
    residual_symbol_years = sorted(
        {
            f"{symbol}|{row['trade_date'][:4]}"
            for row in residual_trade_rows
            for symbol in row["historical_symbols"].split(";")
            if symbol
        }
    )
    residual_dates = sorted({row["trade_date"] for row in residual_trade_rows})

    summary = {
        "schema_version": "1",
        "purpose": (
            "Planning-only union of ThetaData's point-in-time XNAS/UTP equity slice with "
            "FirstRate's public active-ticker matches, leaving an exact Tick Data residual. "
            "No purchase, entitlement, route activation, or G2 coverage is implied."
        ),
        "audit_as_of": AUDIT_AS_OF,
        "first_rate_active_list_url": FIRST_RATE_ACTIVE_LIST_URL,
        "first_rate_residual_direct_match_symbols": sorted(FIRST_RATE_RESIDUAL_MATCHES),
        "accounting_per_record_kind": {
            "required_pairs": 3828,
            "thetadata_pairs": 1430,
            "firstrate_additional_pairs": first_rate_pairs["equity_trade"],
            "combined_cheap_route_pairs": 1430 + first_rate_pairs["equity_trade"],
            "tickdata_residual_pairs": tickdata_pairs["equity_trade"],
        },
        "first_rate": {
            "additional_residual_symbols": len(FIRST_RATE_RESIDUAL_MATCHES),
            "pairs_per_record_kind": first_rate_pairs,
            "source_date_rows_touched": first_rate_dates_touched,
            "fully_covered_residual_dates": first_rate_dates_fully_cover_residual,
        },
        "tickdata_residual": {
            "pairs_per_record_kind": tickdata_pairs,
            "unique_symbols": len(residual_symbols),
            "unique_symbol_years": len(residual_symbol_years),
            "market_dates": len(residual_dates),
            "symbols": residual_symbols,
        },
        "policy": {
            "candidate_is_not_coverage": True,
            "firstrate_active_listing_is_not_historical_entitlement": True,
            "thetadata_license_clearance_required": True,
            "firstrate_license_and_pricing_clearance_required": True,
            "tickdata_license_and_pricing_clearance_required": True,
            "do_not_purchase_automatically": True,
            "do_not_switch_preferred_route_automatically": True,
        },
    }

    for kind in ("equity_trade", "equity_quote"):
        if 1430 + first_rate_pairs[kind] + tickdata_pairs[kind] != 3828:
            raise AssertionError(f"{kind}: pair conservation failed")

    return {
        "firstrate_equity_additional.csv": first_rate,
        "tickdata_equity_residual.csv": tickdata_residual,
    }, summary


def write_outputs(outputs: dict[str, list[dict[str, str]]], summary: dict, outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    for filename, rows in outputs.items():
        with (outdir / filename).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
    (outdir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build ThetaData + FirstRate cheap equity union and Tick Data residual."
    )
    parser.add_argument("--residual", type=Path, default=DEFAULT_RESIDUAL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    outputs, summary = build(_read(args.residual))
    write_outputs(outputs, summary, args.output_dir)
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
