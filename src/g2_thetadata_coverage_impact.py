from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

DEFAULT_CORE = Path(
    "data/processed/real_data_release_sprint/g2_core_source_date_requirements.csv"
)
DEFAULT_OPTIONS = Path(
    "data/processed/real_data_release_sprint/g2_option_source_date_requirements.csv"
)
DEFAULT_THETA_EQUITY = Path(
    "data/processed/g2_vendor_requests/cheap_route_partitions/thetadata_equity.csv"
)
DEFAULT_THETA_OPTIONS = Path(
    "data/processed/g2_vendor_requests/cheap_route_partitions/thetadata_options.csv"
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [{str(k): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(handle)]


def _key(row: dict[str, str]) -> tuple[str, str]:
    return row["record_kind"], row["trade_date"]


def _symbols(text: str) -> set[str]:
    return {x for x in text.split(";") if x}


def _candidate_index(*partitions: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    out: dict[tuple[str, str], dict[str, str]] = {}
    for rows in partitions:
        for row in rows:
            key = _key(row)
            if key in out:
                raise ValueError(f"duplicate ThetaData partition row {key}")
            out[key] = row
    return out


def classify_scope(
    required_rows: list[dict[str, str]],
    theta_index: dict[tuple[str, str], dict[str, str]],
) -> dict:
    full = partial = untouched = 0
    required_pairs = touched_pairs = full_required_pairs = 0
    by_kind: dict[str, dict[str, int]] = {}
    row_receipts = []

    for req in required_rows:
        kind = req["record_kind"]
        req_symbols = _symbols(req["historical_symbols"])
        req_pairs = int(req["symbol_date_pair_count"])
        if req_pairs != len(req_symbols):
            raise ValueError(f"{_key(req)} required symbol/pair mismatch")
        required_pairs += req_pairs

        theta = theta_index.get(_key(req))
        theta_symbols = _symbols(theta["historical_symbols"]) if theta else set()
        if not theta_symbols.issubset(req_symbols):
            raise ValueError(f"{_key(req)} ThetaData contains symbols outside frozen requirement")
        theta_pairs = len(theta_symbols)
        touched_pairs += theta_pairs

        if theta_symbols == req_symbols and req_symbols:
            status = "FULL_CANDIDATE"
            full += 1
            full_required_pairs += req_pairs
        elif theta_symbols:
            status = "PARTIAL_CANDIDATE"
            partial += 1
        else:
            status = "UNTOUCHED"
            untouched += 1

        k = by_kind.setdefault(kind, {
            "required_rows": 0,
            "full_candidate_rows": 0,
            "partial_candidate_rows": 0,
            "untouched_rows": 0,
            "required_symbol_date_pairs": 0,
            "touched_symbol_date_pairs": 0,
        })
        k["required_rows"] += 1
        k["required_symbol_date_pairs"] += req_pairs
        k["touched_symbol_date_pairs"] += theta_pairs
        if status == "FULL_CANDIDATE":
            k["full_candidate_rows"] += 1
        elif status == "PARTIAL_CANDIDATE":
            k["partial_candidate_rows"] += 1
        else:
            k["untouched_rows"] += 1

        row_receipts.append({
            "record_kind": kind,
            "trade_date": req["trade_date"],
            "status": status,
            "required_symbol_count": len(req_symbols),
            "thetadata_symbol_count": theta_pairs,
            "residual_symbol_count": len(req_symbols - theta_symbols),
        })

    return {
        "required_source_date_rows": len(required_rows),
        "full_candidate_rows": full,
        "partial_candidate_rows": partial,
        "untouched_rows": untouched,
        "remaining_rows_not_fully_closed": len(required_rows) - full,
        "required_record_kind_symbol_date_pairs": required_pairs,
        "thetadata_touched_record_kind_symbol_date_pairs": touched_pairs,
        "full_candidate_required_symbol_date_pairs": full_required_pairs,
        "by_record_kind": dict(sorted(by_kind.items())),
        "_row_receipts": row_receipts,
    }


def build_impact(
    core_path: Path,
    option_path: Path,
    theta_equity_path: Path,
    theta_option_path: Path,
) -> dict:
    core = _read_csv(core_path)
    options = _read_csv(option_path)
    theta_equity = _read_csv(theta_equity_path)
    theta_options = _read_csv(theta_option_path)
    theta = _candidate_index(theta_equity, theta_options)

    canonical_rows = core + options
    champion_rows = core + [row for row in options if row["record_kind"] == "option_trade"]

    canonical = classify_scope(canonical_rows, theta)
    champion = classify_scope(champion_rows, theta)
    canonical_receipts = canonical.pop("_row_receipts")
    champion.pop("_row_receipts")

    if len(canonical_rows) != 1656 or len(champion_rows) != 1242:
        raise ValueError("frozen G2 row counts changed")

    return {
        "schema_version": "1",
        "purpose": (
            "Planning-only impact receipt for the written ThetaData $320 one-month route. "
            "Full/partial candidate status does not claim authorization, delivery, validation, or G2 coverage."
        ),
        "vendor": "ThetaData",
        "written_bundle_price_usd": 320,
        "written_terms_source_date": "2026-10-02",
        "request_plan_total_requests": 8888,
        "canonical_full_g2": canonical,
        "champion_minimum": champion,
        "economics": {
            "usd_per_fully_closable_canonical_source_date_row": (
                320 / canonical["full_candidate_rows"]
            ),
            "usd_per_planned_request": 320 / 8888,
        },
        "retention_constraint": {
            "raw_delete_days_after_billing_period_end": 30,
            "derived_or_modified_research_data_retention_allowed": True,
            "retention_plan": "data/processed/g2_vendor_requests/thetadata_retention_plan.json",
        },
        "guardrails": {
            "candidate_is_not_coverage": True,
            "purchase_requires_explicit_user_authorization": True,
            "partial_rows_require_residual_vendor_symbols_before_source_date_closure": True,
            "g2_release_gate_unchanged": True,
        },
        "_canonical_row_receipts": canonical_receipts,
    }


def write_impact(payload: dict, output_json: Path, output_csv: Path) -> None:
    receipts = payload.pop("_canonical_row_receipts")
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    fields = [
        "record_kind",
        "trade_date",
        "status",
        "required_symbol_count",
        "thetadata_symbol_count",
        "residual_symbol_count",
    ]
    with output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(receipts)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build ThetaData G2 coverage-impact receipt.")
    parser.add_argument("--core", type=Path, default=DEFAULT_CORE)
    parser.add_argument("--options", type=Path, default=DEFAULT_OPTIONS)
    parser.add_argument("--theta-equity", type=Path, default=DEFAULT_THETA_EQUITY)
    parser.add_argument("--theta-options", type=Path, default=DEFAULT_THETA_OPTIONS)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, required=True)
    args = parser.parse_args()

    payload = build_impact(args.core, args.options, args.theta_equity, args.theta_options)
    write_impact(payload, args.output_json, args.output_csv)


if __name__ == "__main__":
    main()
