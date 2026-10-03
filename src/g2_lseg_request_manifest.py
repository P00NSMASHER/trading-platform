from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

DEFAULT_MAPPING = Path("data/processed/g2_vendor_requests/lseg_equity_ric_mapping.csv")
DEFAULT_CORE = Path("data/processed/real_data_release_sprint/g2_core_source_date_requirements.csv")
DEFAULT_OPTIONS = Path("data/processed/real_data_release_sprint/g2_option_source_date_requirements.csv")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"{path}: empty CSV")
    return rows


def _mapping(rows: list[dict[str, str]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for row in rows:
        symbol = row["historical_symbol"].strip()
        rics = [x for x in row["candidate_rics"].split(";") if x]
        if row["mapping_status"] == "candidate_exact_root_match" and not rics:
            raise ValueError(f"{symbol}: matched status without a RIC")
        out[symbol] = rics
    return out


def _expand(
    requirement_rows: list[dict[str, str]],
    symbol_to_rics: dict[str, list[str]],
    *,
    lane: str,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    requests: list[dict[str, str]] = []
    unresolved: list[dict[str, str]] = []

    for row in requirement_rows:
        trade_date = row["trade_date"]
        record_kind = row["record_kind"]
        symbols = [x for x in row["historical_symbols"].split(";") if x]
        if len(symbols) != int(row["symbol_date_pair_count"]):
            raise ValueError(f"{trade_date}/{record_kind}: pair-count mismatch")

        for symbol in symbols:
            rics = symbol_to_rics.get(symbol, [])
            if not rics:
                unresolved.append(
                    {
                        "lane": lane,
                        "trade_date": trade_date,
                        "record_kind": record_kind,
                        "historical_symbol": symbol,
                        "reason": "no exact-root RIC in extracted companion mapping",
                    }
                )
                continue

            requests.append(
                {
                    "lane": lane,
                    "trade_date": trade_date,
                    "record_kind": record_kind,
                    "historical_symbol": symbol,
                    "candidate_rics": ";".join(rics),
                    "request_type": (
                        "TickHistoryTimeAndSales"
                        if lane == "equity"
                        else "HistoricalOptionChainThenTickHistoryTimeAndSales"
                    ),
                    "status": (
                        "candidate_direct_time_and_sales"
                        if lane == "equity"
                        else "candidate_underlying_mapped_option_contract_resolution_required"
                    ),
                }
            )

    return requests, unresolved


def build_plan(
    mapping_rows: list[dict[str, str]],
    core_rows: list[dict[str, str]],
    option_rows: list[dict[str, str]],
) -> dict:
    symbol_to_rics = _mapping(mapping_rows)
    equity, unresolved_equity = _expand(core_rows, symbol_to_rics, lane="equity")
    options, unresolved_options = _expand(option_rows, symbol_to_rics, lane="options")

    unique_symbols = sorted(symbol_to_rics)
    mapped_symbols = sorted(k for k, v in symbol_to_rics.items() if v)
    unresolved_symbols = sorted(k for k, v in symbol_to_rics.items() if not v)

    return {
        "schema_version": "1",
        "purpose": (
            "Deterministic LSEG Tick History acquisition plan derived only from repository-held "
            "G2 requirements and repository-extracted RIC metadata. No authentication, API call, "
            "download, purchase, or G2 coverage mutation is performed."
        ),
        "source_contract": {
            "template": "TickHistoryTimeAndSales",
            "allow_historical_instruments": True,
            "equity_fields": [
                "#RIC",
                "Date-Time",
                "Price",
                "Volume",
                "Bid Price",
                "Bid Size",
                "Ask Price",
                "Ask Size",
            ],
            "option_contract_discovery": (
                "Resolve the complete historical option chain for each mapped underlying/date, "
                "then request Tick History Time & Sales for every required contract."
            ),
            "option_fields": [
                "#RIC",
                "Date-Time",
                "Price",
                "Volume",
                "Bid Price",
                "Bid Size",
                "Ask Price",
                "Ask Size",
            ],
        },
        "mapping_summary": {
            "g2_unique_symbols": len(unique_symbols),
            "mapped_symbols": len(mapped_symbols),
            "unresolved_symbols": len(unresolved_symbols),
            "unresolved_symbol_list": unresolved_symbols,
        },
        "request_summary": {
            "equity_mapped_symbol_kind_dates": len(equity),
            "equity_unresolved_symbol_kind_dates": len(unresolved_equity),
            "option_mapped_underlying_kind_dates": len(options),
            "option_unresolved_underlying_kind_dates": len(unresolved_options),
        },
        "equity_requests": equity,
        "option_underlying_requests": options,
        "unresolved": unresolved_equity + unresolved_options,
    }


def _write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a dry-run LSEG G2 acquisition plan.")
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--core", type=Path, default=DEFAULT_CORE)
    parser.add_argument("--options", type=Path, default=DEFAULT_OPTIONS)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    plan = build_plan(_read_csv(args.mapping), _read_csv(args.core), _read_csv(args.options))
    args.output_dir.mkdir(parents=True, exist_ok=True)

    request_fields = [
        "lane",
        "trade_date",
        "record_kind",
        "historical_symbol",
        "candidate_rics",
        "request_type",
        "status",
    ]
    _write_csv(args.output_dir / "equity_requests.csv", plan["equity_requests"], request_fields)
    _write_csv(
        args.output_dir / "option_underlying_requests.csv",
        plan["option_underlying_requests"],
        request_fields,
    )
    _write_csv(
        args.output_dir / "unresolved.csv",
        plan["unresolved"],
        ["lane", "trade_date", "record_kind", "historical_symbol", "reason"],
    )

    summary = {k: v for k, v in plan.items() if k not in {"equity_requests", "option_underlying_requests", "unresolved"}}
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
