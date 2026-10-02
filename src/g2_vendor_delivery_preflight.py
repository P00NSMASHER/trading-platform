from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

ROUTE_EXPECTATIONS = {
    "candidate_tickdata_equity_trades": {
        "record_kind": "equity_trade",
        "source_family": "generic_authorized_market_data",
    },
    "candidate_tickdata_equity_nbbo_quotes": {
        "record_kind": "equity_quote",
        "source_family": "generic_authorized_market_data",
    },
    "candidate_databento_opra_trades": {
        "record_kind": "option_trade",
        "source_family": "generic_authorized_market_data",
    },
    "candidate_cboe_option_trades": {
        "record_kind": "option_trade",
        "source_family": "cboe_option_trades",
    },
    "candidate_lseg_opra_tick_history": {
        "record_kind": "option_trade",
        "source_family": "generic_authorized_market_data",
    },
    "candidate_lseg_opra_tick_history_option_quotes": {
        "record_kind": "option_quote",
        "source_family": "generic_authorized_market_data",
    },
}

ACTIVATABLE_INTAKE_STATUS = "PENDING_AUTHORIZATION_AND_REVIEW"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def preflight(request_manifest: Path, intake_inventory: Path) -> dict:
    requested = _read_csv(request_manifest)
    inventory = _read_csv(intake_inventory)
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

    required_by_date = {row["trade_date"]: row for row in requested}
    relevant = [
        row for row in inventory
        if row.get("candidate_record_kind", "").strip() == expected["record_kind"]
        and row.get("candidate_source_family", "").strip() == expected["source_family"]
    ]
    by_date: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in relevant:
        day = row.get("detected_trade_date", "").strip()
        if day:
            by_date[day].append(row)

    date_results = []
    counts = defaultdict(int)
    for day in sorted(required_by_date):
        matches = by_date.get(day, [])
        if not matches:
            status = "MISSING_DELIVERY"
        elif any(row.get("status", "").strip() == ACTIVATABLE_INTAKE_STATUS for row in matches):
            status = "PRESENT_PENDING_AUTHORIZATION"
        else:
            status = "PRESENT_SCHEMA_BLOCKED"

        counts[status] += 1
        date_results.append(
            {
                "trade_date": day,
                "status": status,
                "required_symbols": required_by_date[day].get("historical_symbols", ""),
                "required_symbol_count": int(required_by_date[day].get("unique_symbol_count") or 0),
                "required_symbol_date_pair_count": int(
                    required_by_date[day].get("symbol_date_pair_count") or 0
                ),
                "matching_file_count": len(matches),
                "matching_file_sha256": sorted(
                    row.get("sha256", "").strip()
                    for row in matches
                    if row.get("sha256", "").strip()
                ),
                "matching_intake_statuses": sorted(
                    {row.get("status", "").strip() for row in matches if row.get("status", "").strip()}
                ),
            }
        )

    unexpected_dates = sorted(day for day in by_date if day not in required_by_date)
    requested_rows = len(requested)
    requested_pairs = sum(int(row.get("symbol_date_pair_count") or 0) for row in requested)

    return {
        "schema_version": "1",
        "purpose": (
            "Fail-closed delivery preflight for a G2 vendor request manifest. "
            "This report validates only delivery presence/intake classification by date; "
            "it never asserts authorization, symbol coverage, or G2 coverage."
        ),
        "route": route,
        "expected_record_kind": expected["record_kind"],
        "expected_source_family": expected["source_family"],
        "requested_source_date_rows": requested_rows,
        "requested_symbol_date_pairs": requested_pairs,
        "present_pending_authorization_rows": counts["PRESENT_PENDING_AUTHORIZATION"],
        "present_schema_blocked_rows": counts["PRESENT_SCHEMA_BLOCKED"],
        "missing_delivery_rows": counts["MISSING_DELIVERY"],
        "unexpected_delivery_dates": unexpected_dates,
        "ready_for_entitlement_review": (
            counts["MISSING_DELIVERY"] == 0
            and counts["PRESENT_SCHEMA_BLOCKED"] == 0
            and counts["PRESENT_PENDING_AUTHORIZATION"] == requested_rows
        ),
        "coverage_policy": {
            "authorization_validated": False,
            "license_validated": False,
            "required_symbol_content_validated": False,
            "g2_coverage_counted": False,
            "file_presence_alone_is_never_coverage": True,
        },
        "dates": date_results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fail-closed delivery preflight for a G2 vendor request manifest."
    )
    parser.add_argument("--request-manifest", type=Path, required=True)
    parser.add_argument("--intake-inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    payload = preflight(args.request_manifest, args.intake_inventory)
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
