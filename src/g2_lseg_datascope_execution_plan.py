from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Iterable

import g2_lseg_request_manifest as manifest

DEFAULT_MAPPING = manifest.DEFAULT_MAPPING
DEFAULT_SECONDARY = manifest.DEFAULT_SECONDARY
DEFAULT_EVENT_MAPPING = manifest.DEFAULT_EVENT_MAPPING
DEFAULT_CORE = manifest.DEFAULT_CORE
DEFAULT_OPTIONS = manifest.DEFAULT_OPTIONS

TIME_AND_SALES_FIELDS = [
    "#RIC",
    "Date-Time",
    "GMT Offset",
    "Type",
    "Ex/Cntrb.ID",
    "Price",
    "Volume",
    "Bid Price",
    "Bid Size",
    "Ask Price",
    "Ask Size",
    "Qualifiers",
    "Seq. No.",
    "Exch Time",
]

BASE_PATH = "/RestApi/v1"
AUTH_ENDPOINT = f"{BASE_PATH}/Authentication/RequestToken"
FUTURES_OPTIONS_SEARCH_ENDPOINT = f"{BASE_PATH}/Search/FuturesAndOptionsSearch"
HISTORICAL_CHAIN_ENDPOINT = f"{BASE_PATH}/Search/HistoricalChainResolution"
EXTRACT_ENDPOINT = f"{BASE_PATH}/Extractions/ExtractRaw"


def _split(value: str) -> list[str]:
    return [part for part in str(value or "").split(";") if part]


def _collapse_symbol_date_rows(
    rows: Iterable[dict[str, str]],
    *,
    expected_kinds: set[str],
) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], dict[str, object]] = {}

    for row in rows:
        key = (row["trade_date"], row["historical_symbol"])
        item = grouped.setdefault(
            key,
            {
                "trade_date": row["trade_date"],
                "historical_symbol": row["historical_symbol"],
                "candidate_rics": _split(row["candidate_rics"]),
                "mapping_class": row["mapping_class"],
                "record_kinds": set(),
                "statuses": set(),
            },
        )
        if item["candidate_rics"] != _split(row["candidate_rics"]):
            raise ValueError(f"{key}: candidate RIC drift across record kinds")
        if item["mapping_class"] != row["mapping_class"]:
            raise ValueError(f"{key}: mapping-class drift across record kinds")
        item["record_kinds"].add(row["record_kind"])
        item["statuses"].add(row["status"])

    out: list[dict[str, object]] = []
    for key in sorted(grouped):
        item = grouped[key]
        if item["record_kinds"] != expected_kinds:
            raise ValueError(
                f"{key}: expected record kinds {sorted(expected_kinds)}, "
                f"got {sorted(item['record_kinds'])}"
            )
        out.append(
            {
                "trade_date": item["trade_date"],
                "historical_symbol": item["historical_symbol"],
                "candidate_rics": item["candidate_rics"],
                "mapping_class": item["mapping_class"],
                "record_kinds": sorted(item["record_kinds"]),
                "statuses": sorted(item["statuses"]),
                "historical_validation_required": (
                    item["mapping_class"] != "study_permno_linked_companion_match"
                ),
            }
        )
    return out


def _date_batches(symbol_dates: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in symbol_dates:
        grouped[str(row["trade_date"])].append(row)

    batches: list[dict[str, object]] = []
    for trade_date in sorted(grouped):
        rows = sorted(grouped[trade_date], key=lambda row: str(row["historical_symbol"]))
        candidate_rics = sorted(
            {
                ric
                for row in rows
                for ric in list(row["candidate_rics"])
            }
        )
        validation_symbols = [
            str(row["historical_symbol"])
            for row in rows
            if bool(row["historical_validation_required"])
        ]
        batches.append(
            {
                "trade_date": trade_date,
                "historical_symbols": [
                    str(row["historical_symbol"]) for row in rows
                ],
                "candidate_rics": candidate_rics,
                "historical_symbol_count": len(rows),
                "candidate_ric_count": len(candidate_rics),
                "historical_validation_required_symbols": validation_symbols,
                "report_type": "TickHistoryTimeAndSales",
                "content_fields": TIME_AND_SALES_FIELDS,
                "condition": {
                    "ReportDateRangeType": "Range",
                    "QueryStartDate": f"{trade_date}T00:00:00.000000000",
                    "QueryEndDate": f"{trade_date}T23:59:59.999999999",
                    "DateRangeTimeZone": "Local Exchange Time Zone",
                    "TimeRangeMode": "Inclusive",
                    "SortBy": "SingleByTimestamp",
                    "MessageTimeStampIn": "LocalExchangeTime",
                    "ApplyCorrectionsAndCancellations": False,
                },
                "identifier_validation": {
                    "AllowHistoricalInstruments": True,
                    "UseUserPreferencesForValidationOptions": False,
                },
            }
        )
    return batches


def build_execution_plan(plan: dict) -> dict:
    equity_symbol_dates = _collapse_symbol_date_rows(
        plan["equity_requests"],
        expected_kinds={"equity_trade", "equity_quote"},
    )
    option_underlying_dates = _collapse_symbol_date_rows(
        plan["option_underlying_requests"],
        expected_kinds={"option_trade", "option_quote"},
    )

    equity_batches = _date_batches(equity_symbol_dates)

    option_discovery = []
    for row in option_underlying_dates:
        option_discovery.append(
            {
                **row,
                "discovery_methods": [
                    {
                        "endpoint": FUTURES_OPTIONS_SEARCH_ENDPOINT,
                        "method": "futures_and_options_search",
                        "request": {
                            "SearchRequest": {
                                "FuturesAndOptionsType": "Options",
                                "UnderlyingRicCandidates": row["candidate_rics"],
                                "ExpirationDate": {
                                    "ComparisonOperator": "GreaterThanEquals",
                                    "Value": row["trade_date"],
                                },
                            }
                        },
                    },
                    {
                        "endpoint": HISTORICAL_CHAIN_ENDPOINT,
                        "method": "historical_chain_resolution",
                        "chain_pattern_candidates": [
                            f"0#{ric.split('.')[0]}*.U"
                            for ric in row["candidate_rics"]
                        ],
                        "range": {
                            "Start": f"{row['trade_date']}T00:00:00.000Z",
                            "End": f"{row['trade_date']}T23:59:59.999Z",
                        },
                    },
                ],
                "next_step": (
                    "resolve every option contract valid on this underlying/date, "
                    "validate contract metadata, then include those option RICs in "
                    "the date's TickHistoryTimeAndSales extraction batch"
                ),
            }
        )

    return {
        "schema_version": "1",
        "purpose": (
            "Credential-free execution plan for the licensed LSEG DataScope Select route. "
            "It collapses duplicate trade/quote requirements into logical API work while "
            "preserving the frozen G2 symbol/date universe. No network call, download, "
            "purchase, credential read, or G2 coverage mutation occurs."
        ),
        "api": {
            "base_path": BASE_PATH,
            "authentication_endpoint": AUTH_ENDPOINT,
            "option_search_endpoint": FUTURES_OPTIONS_SEARCH_ENDPOINT,
            "historical_chain_endpoint": HISTORICAL_CHAIN_ENDPOINT,
            "extract_endpoint": EXTRACT_ENDPOINT,
            "time_and_sales_fields": TIME_AND_SALES_FIELDS,
        },
        "summary": {
            "frozen_source_dates": len(equity_batches),
            "equity_source_date_rows": 828,
            "option_source_date_rows": 828,
            "original_symbol_kind_date_requests": (
                len(plan["equity_requests"]) + len(plan["option_underlying_requests"])
            ),
            "equity_unique_symbol_dates": len(equity_symbol_dates),
            "option_unique_underlying_dates": len(option_underlying_dates),
            "equity_time_and_sales_date_batches": len(equity_batches),
            "option_underlying_discovery_tasks": len(option_discovery),
            "option_time_and_sales_date_batches_after_discovery_max": len(equity_batches),
            "historical_validation_required_equity_symbol_dates": sum(
                bool(row["historical_validation_required"])
                for row in equity_symbol_dates
            ),
            "historical_validation_required_option_underlying_dates": sum(
                bool(row["historical_validation_required"])
                for row in option_underlying_dates
            ),
        },
        "equity_symbol_dates": equity_symbol_dates,
        "equity_date_batches": equity_batches,
        "option_underlying_dates": option_underlying_dates,
        "option_discovery_tasks": option_discovery,
        "private_output_policy": {
            "raw_licensed_rows": "write only to an ignored/private local destination",
            "public_repository": (
                "store only schemas, request metadata, SHA-256 receipts, validation summaries, "
                "and non-proprietary processing code"
            ),
        },
    }


def _write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            cooked = dict(row)
            for key, value in list(cooked.items()):
                if isinstance(value, list):
                    cooked[key] = ";".join(str(x) for x in value)
                elif isinstance(value, dict):
                    cooked[key] = json.dumps(value, sort_keys=True)
            writer.writerow(cooked)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a credential-free LSEG DataScope execution plan."
    )
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--secondary-mapping", type=Path, default=DEFAULT_SECONDARY)
    parser.add_argument("--event-mapping", type=Path, default=DEFAULT_EVENT_MAPPING)
    parser.add_argument("--core", type=Path, default=DEFAULT_CORE)
    parser.add_argument("--options", type=Path, default=DEFAULT_OPTIONS)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    base_plan = manifest.build_plan(
        manifest._read_csv(args.mapping),
        manifest._read_csv(args.secondary_mapping),
        manifest._read_csv(args.event_mapping),
        manifest._read_csv(args.core),
        manifest._read_csv(args.options),
    )
    execution = build_execution_plan(base_plan)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(
        json.dumps(
            {
                "schema_version": execution["schema_version"],
                "purpose": execution["purpose"],
                "api": execution["api"],
                "summary": execution["summary"],
                "private_output_policy": execution["private_output_policy"],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "equity_date_batches.json").write_text(
        json.dumps(execution["equity_date_batches"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "option_discovery_tasks.json").write_text(
        json.dumps(execution["option_discovery_tasks"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_csv(
        args.output_dir / "equity_symbol_dates.csv",
        execution["equity_symbol_dates"],
        [
            "trade_date",
            "historical_symbol",
            "candidate_rics",
            "mapping_class",
            "record_kinds",
            "statuses",
            "historical_validation_required",
        ],
    )
    _write_csv(
        args.output_dir / "option_underlying_dates.csv",
        execution["option_underlying_dates"],
        [
            "trade_date",
            "historical_symbol",
            "candidate_rics",
            "mapping_class",
            "record_kinds",
            "statuses",
            "historical_validation_required",
        ],
    )
    print(json.dumps(execution["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
