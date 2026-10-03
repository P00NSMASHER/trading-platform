from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

DEFAULT_MAPPING = Path("data/processed/g2_vendor_requests/lseg_equity_ric_mapping.csv")
DEFAULT_SECONDARY = Path("data/processed/g2_vendor_requests/lseg_secondary_ric_candidates.csv")
DEFAULT_EVENT_MAPPING = Path("data/processed/g2_vendor_requests/lseg_event_permno_ric_mapping.csv")
DEFAULT_CORE = Path("data/processed/real_data_release_sprint/g2_core_source_date_requirements.csv")
DEFAULT_OPTIONS = Path("data/processed/real_data_release_sprint/g2_option_source_date_requirements.csv")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"{path}: empty CSV")
    return rows


def _mapping(
    primary_rows: list[dict[str, str]],
    secondary_rows: list[dict[str, str]],
    event_rows: list[dict[str, str]],
) -> dict[str, dict[str, object]]:
    secondary = {
        row["historical_symbol"]: [x for x in row["candidate_rics"].split(";") if x]
        for row in secondary_rows
    }
    event_linked_symbols = {
        row["SYMBOL"]
        for row in event_rows
        if row["mapping_status"] == "study_permno_linked_candidate"
    }

    out: dict[str, dict[str, object]] = {}
    for row in primary_rows:
        symbol = row["historical_symbol"].strip()
        primary_rics = [x for x in row["candidate_rics"].split(";") if x]
        if row["mapping_status"] == "candidate_exact_root_match":
            if not primary_rics:
                raise ValueError(f"{symbol}: primary match without a RIC")
            mapping_class = (
                "study_permno_linked_companion_match"
                if symbol in event_linked_symbols
                else "companion_root_match_without_permno_link"
            )
            out[symbol] = {
                "rics": primary_rics,
                "mapping_class": mapping_class,
            }
            continue

        secondary_rics = secondary.get(symbol, [])
        if secondary_rics:
            out[symbol] = {
                "rics": secondary_rics,
                "mapping_class": "secondary_repository_candidate",
            }
        else:
            out[symbol] = {
                "rics": [],
                "mapping_class": "unresolved",
            }

    return out


def _expand(
    requirement_rows: list[dict[str, str]],
    symbol_map: dict[str, dict[str, object]],
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
            mapping = symbol_map.get(
                symbol,
                {"rics": [], "mapping_class": "unresolved"},
            )
            rics = list(mapping["rics"])
            mapping_class = str(mapping["mapping_class"])

            if not rics:
                unresolved.append(
                    {
                        "lane": lane,
                        "trade_date": trade_date,
                        "record_kind": record_kind,
                        "historical_symbol": symbol,
                        "reason": "no repository-extracted RIC candidate",
                    }
                )
                continue

            strong = mapping_class == "study_permno_linked_companion_match"
            if lane == "equity":
                status = (
                    "candidate_direct_time_and_sales"
                    if strong
                    else "candidate_time_and_sales_historical_identifier_validation_required"
                )
                request_type = "TickHistoryTimeAndSales"
            else:
                status = (
                    "candidate_underlying_mapped_option_contract_resolution_required"
                    if strong
                    else "candidate_underlying_historical_ric_validation_and_option_contract_resolution_required"
                )
                request_type = "HistoricalOptionChainThenTickHistoryTimeAndSales"

            requests.append(
                {
                    "lane": lane,
                    "trade_date": trade_date,
                    "record_kind": record_kind,
                    "historical_symbol": symbol,
                    "candidate_rics": ";".join(rics),
                    "mapping_class": mapping_class,
                    "request_type": request_type,
                    "status": status,
                }
            )

    return requests, unresolved


def build_plan(
    primary_mapping_rows: list[dict[str, str]],
    secondary_mapping_rows: list[dict[str, str]],
    event_mapping_rows: list[dict[str, str]],
    core_rows: list[dict[str, str]],
    option_rows: list[dict[str, str]],
) -> dict:
    symbol_map = _mapping(primary_mapping_rows, secondary_mapping_rows, event_mapping_rows)
    equity, unresolved_equity = _expand(core_rows, symbol_map, lane="equity")
    options, unresolved_options = _expand(option_rows, symbol_map, lane="options")

    classes = {
        name: sorted(k for k, v in symbol_map.items() if v["mapping_class"] == name)
        for name in {
            "study_permno_linked_companion_match",
            "companion_root_match_without_permno_link",
            "secondary_repository_candidate",
            "unresolved",
        }
    }

    def count_mapping_class(rows: list[dict[str, str]], mapping_class: str) -> int:
        return sum(row["mapping_class"] == mapping_class for row in rows)

    return {
        "schema_version": "3",
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
            "g2_unique_symbols": len(symbol_map),
            "study_permno_linked_companion_symbols": len(
                classes["study_permno_linked_companion_match"]
            ),
            "companion_root_only_symbols": len(
                classes["companion_root_match_without_permno_link"]
            ),
            "secondary_repository_candidate_symbols": len(
                classes["secondary_repository_candidate"]
            ),
            "unresolved_symbols": len(classes["unresolved"]),
            "companion_root_only_symbol_list": classes[
                "companion_root_match_without_permno_link"
            ],
            "secondary_validation_required": classes["secondary_repository_candidate"],
            "unresolved_symbol_list": classes["unresolved"],
        },
        "request_summary": {
            "equity_total_candidate_symbol_kind_dates": len(equity),
            "equity_study_permno_linked_symbol_kind_dates": count_mapping_class(
                equity, "study_permno_linked_companion_match"
            ),
            "equity_companion_root_only_symbol_kind_dates": count_mapping_class(
                equity, "companion_root_match_without_permno_link"
            ),
            "equity_secondary_symbol_kind_dates": count_mapping_class(
                equity, "secondary_repository_candidate"
            ),
            "equity_unresolved_symbol_kind_dates": len(unresolved_equity),
            "option_total_candidate_underlying_kind_dates": len(options),
            "option_study_permno_linked_underlying_kind_dates": count_mapping_class(
                options, "study_permno_linked_companion_match"
            ),
            "option_companion_root_only_underlying_kind_dates": count_mapping_class(
                options, "companion_root_match_without_permno_link"
            ),
            "option_secondary_underlying_kind_dates": count_mapping_class(
                options, "secondary_repository_candidate"
            ),
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
    parser.add_argument("--secondary-mapping", type=Path, default=DEFAULT_SECONDARY)
    parser.add_argument("--event-mapping", type=Path, default=DEFAULT_EVENT_MAPPING)
    parser.add_argument("--core", type=Path, default=DEFAULT_CORE)
    parser.add_argument("--options", type=Path, default=DEFAULT_OPTIONS)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    plan = build_plan(
        _read_csv(args.mapping),
        _read_csv(args.secondary_mapping),
        _read_csv(args.event_mapping),
        _read_csv(args.core),
        _read_csv(args.options),
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)

    request_fields = [
        "lane",
        "trade_date",
        "record_kind",
        "historical_symbol",
        "candidate_rics",
        "mapping_class",
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

    summary = {
        k: v
        for k, v in plan.items()
        if k not in {"equity_requests", "option_underlying_requests", "unresolved"}
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
