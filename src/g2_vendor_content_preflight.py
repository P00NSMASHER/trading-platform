from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import historical_market_backfill as backfill
from g2_vendor_delivery_preflight import ROUTE_EXPECTATIONS


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def preflight(request_manifest: Path, market_contract: Path) -> dict:
    requested = _read_csv(request_manifest)
    if not requested:
        raise ValueError("request manifest is empty")

    routes = {row.get("route", "").strip() for row in requested}
    if len(routes) != 1:
        raise ValueError(f"request manifest must contain one route, found={sorted(routes)}")
    route = next(iter(routes))
    expected = ROUTE_EXPECTATIONS.get(route)
    if expected is None:
        raise ValueError(f"unsupported route={route!r}")

    record_kinds = {row.get("record_kind", "").strip() for row in requested}
    if record_kinds != {expected["record_kind"]}:
        raise ValueError(
            f"request manifest record_kind mismatch: expected={expected['record_kind']} "
            f"found={sorted(record_kinds)}"
        )

    specs, _ = backfill.load_contract(market_contract)
    relevant = [
        spec
        for spec in specs
        if spec.record_kind == expected["record_kind"]
        and spec.source_family == expected["source_family"]
    ]

    requested_by_date = {row["trade_date"]: row for row in requested}
    specs_by_date: dict[str, list] = defaultdict(list)
    undated_specs = []
    for spec in relevant:
        if spec.trade_date:
            specs_by_date[spec.trade_date].append(spec)
        else:
            undated_specs.append(spec)

    date_results = []
    complete_rows = 0
    complete_pairs = 0
    total_errors = 0

    for day in sorted(requested_by_date):
        row = requested_by_date[day]
        required = {
            symbol.strip().upper()
            for symbol in row.get("historical_symbols", "").split(";")
            if symbol.strip()
        }
        expected_count = int(row.get("unique_symbol_count") or 0)
        if expected_count != len(required):
            raise ValueError(
                f"{day}: unique_symbol_count={expected_count} does not match "
                f"historical_symbols={len(required)}"
            )

        candidates = list(specs_by_date.get(day, [])) + undated_specs
        observed: set[str] = set()
        source_results = []
        errors = []

        for spec in candidates:
            try:
                result = backfill.inspect_source_coverage(
                    spec,
                    expected_trade_date=day,
                    required_symbols=required,
                )
                observed.update(result["observed_required_symbols"])
                source_results.append(
                    {
                        "source_id": spec.source_id,
                        "declared_trade_date": spec.trade_date,
                        "matching_date_rows": result["matching_date_rows"],
                        "observed_required_symbols": result["observed_required_symbols"],
                        "missing_required_symbols": result["missing_required_symbols"],
                        "content_coverage_valid_for_source": result["content_coverage_valid"],
                    }
                )
            except Exception as exc:
                errors.append(
                    {
                        "source_id": spec.source_id,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )

        missing = sorted(required - observed)
        valid = bool(candidates) and not missing and not errors
        if valid:
            complete_rows += 1
            complete_pairs += int(row.get("symbol_date_pair_count") or 0)
        total_errors += len(errors)

        date_results.append(
            {
                "trade_date": day,
                "required_symbol_count": len(required),
                "observed_required_symbol_count": len(required & observed),
                "missing_required_symbols": missing,
                "candidate_source_count": len(candidates),
                "source_error_count": len(errors),
                "content_preflight_valid": valid,
                "source_results": source_results,
                "source_errors": errors,
            }
        )

    requested_dates = set(requested_by_date)
    unexpected_declared_dates = sorted(
        {
            spec.trade_date
            for spec in relevant
            if spec.trade_date and spec.trade_date not in requested_dates
        }
    )
    requested_pairs = sum(int(row.get("symbol_date_pair_count") or 0) for row in requested)

    return {
        "schema_version": "1",
        "purpose": (
            "Post-activation G2 vendor content preflight using the production parser. "
            "This proves date + required-symbol presence only; it does not count G2 coverage."
        ),
        "route": route,
        "expected_record_kind": expected["record_kind"],
        "expected_source_family": expected["source_family"],
        "requested_source_date_rows": len(requested),
        "requested_symbol_date_pairs": requested_pairs,
        "content_complete_source_date_rows": complete_rows,
        "content_complete_symbol_date_pairs": complete_pairs,
        "missing_or_invalid_source_date_rows": len(requested) - complete_rows,
        "relevant_contract_source_count": len(relevant),
        "source_error_count": total_errors,
        "unexpected_declared_dates": unexpected_declared_dates,
        "ready_for_coverage_audit": (
            complete_rows == len(requested)
            and total_errors == 0
            and not unexpected_declared_dates
        ),
        "coverage_policy": {
            "production_parser_used": True,
            "required_symbol_presence_validated": True,
            "authorization_inherited_from_loaded_contract": True,
            "g2_coverage_counted": False,
            "release_gate_unchanged": True,
        },
        "dates": date_results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Post-activation content preflight for one G2 vendor request manifest."
    )
    parser.add_argument("--request-manifest", type=Path, required=True)
    parser.add_argument("--market-contract", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    payload = preflight(args.request_manifest, args.market_contract)
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
