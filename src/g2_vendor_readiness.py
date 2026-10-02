from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VENDOR_DIR = Path("data/processed/g2_vendor_requests")
DEFAULT_COVERAGE = Path("data/processed/coverage_plan_real/coverage_summary.json")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_readiness(vendor_dir: Path, coverage_summary: Path) -> dict:
    requests = _read_json(vendor_dir / "vendor_request_summary.json")
    activation = _read_json(vendor_dir / "vendor_activation_blueprint.json")
    quotes = _read_json(vendor_dir / "vendor_quote_packets.json")
    coverage = _read_json(coverage_summary)
    audit = coverage.get("contract_audit") or {}

    if requests["champion_minimum_source_date_rows"] != 1242:
        raise ValueError("vendor request summary does not match 1,242-row champion minimum")
    if activation["champion_minimum_source_date_rows"] != 1242:
        raise ValueError("activation blueprint does not match 1,242-row champion minimum")
    if quotes["champion_minimum_source_date_rows"] != 1242:
        raise ValueError("quote packets do not match 1,242-row champion minimum")
    if {
        requests["total_record_kind_symbol_date_pairs"],
        activation["total_record_kind_symbol_date_pairs"],
        quotes["total_record_kind_symbol_date_pairs"],
    } != {11484}:
        raise ValueError("vendor artifacts disagree on 11,484 request-pair footprint")

    activation_profiles = activation["profiles"]
    all_fail_closed = all(
        profile["activation_status"] == "PENDING_DELIVERY_LICENSE_SCHEMA_REVIEW"
        and profile["delivery"]["path"] == ""
        and profile["delivery"]["license_reference"] == ""
        and profile["entitlement_template"]["authorized"] is False
        for profile in activation_profiles
    )
    if not all_fail_closed:
        raise ValueError("activation blueprint is not fail-closed")

    delivery_preflight_present = (
        REPO_ROOT / "src/g2_vendor_delivery_preflight.py"
    ).exists()
    cost_probe_workflow_present = (
        REPO_ROOT / ".github/workflows/g2-databento-cost-probe.yml"
    ).exists()

    full_required = int(audit.get("required_source_date_rows", 0) or 0)
    full_covered = int(audit.get("real_authorized_required_rows_covered", 0) or 0)
    full_missing = int(audit.get("missing_real_authorized_required_rows", 0) or 0)

    return {
        "schema_version": "1",
        "purpose": (
            "Repository-side readiness receipt for G2 vendor acquisition. "
            "Planning readiness is separate from licensed delivery and validated G2 coverage."
        ),
        "champion_minimum_scope": {
            "source_date_rows": 1242,
            "record_kind_symbol_date_pairs": 11484,
            "candidate_route_count": len(activation_profiles),
        },
        "repository_readiness": {
            "vendor_request_manifests_ready": True,
            "vendor_quote_packets_ready": True,
            "fail_closed_activation_blueprint_ready": all_fail_closed,
            "delivery_preflight_tool_ready": delivery_preflight_present,
            "databento_cost_only_workflow_ready": cost_probe_workflow_present,
        },
        "external_state": {
            "vendor_quotes_or_pricing": "PENDING_EXTERNAL",
            "license_or_entitlement_terms": "PENDING_EXTERNAL",
            "licensed_data_delivery": "PENDING_EXTERNAL",
            "local_entitlement_hash_binding": "PENDING_EXTERNAL",
            "production_content_validation": "BLOCKED_ON_DELIVERY",
            "runtime_secret_state": "NOT_COMMITTED_TO_REPOSITORY",
        },
        "canonical_full_g2_state": {
            "required_source_date_rows": full_required,
            "validated_authorized_source_date_rows": full_covered,
            "missing_validated_authorized_source_date_rows": full_missing,
            "ready_for_real_backfill": bool(audit.get("ready_for_real_backfill")),
        },
        "champion_minimum_validated_coverage": {
            "separately_measured": False,
            "note": (
                "The 1,242-row champion-minimum scope is an acquisition optimization. "
                "It is not substituted for canonical G2_REAL_MARKET_DATA coverage."
            ),
        },
        "next_external_actions": [
            "Configure DATABENTO_API_KEY if cost-only OPRA pricing is desired; the workflow performs no download or purchase.",
            "Request/confirm Tick Data equity trade + tick-level NBBO quote pricing/licensing for the frozen request manifests.",
            "Request/confirm Cboe historical Option Trades pricing/licensing for the 2012-01-03 through 2013-03-28 request manifest.",
            "Request/confirm LSEG OPRA Tick History pricing/licensing for the 2011 request manifest.",
            "Place lawfully obtained vendor files in a local drop folder, run licensed-data intake + delivery preflight, then create a local hash-bound entitlement manifest.",
        ],
        "policy": {
            "candidate_source_is_not_coverage": True,
            "quote_packet_is_not_purchase_authority": True,
            "delivery_is_not_authorization": True,
            "file_presence_is_not_content_coverage": True,
            "g2_release_gate_unchanged": True,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build G2 vendor acquisition readiness receipt.")
    parser.add_argument("--vendor-dir", type=Path, default=DEFAULT_VENDOR_DIR)
    parser.add_argument("--coverage-summary", type=Path, default=DEFAULT_COVERAGE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    payload = build_readiness(args.vendor_dir, args.coverage_summary)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
