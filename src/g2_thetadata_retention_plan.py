from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

RAW_DELETE_DAYS_AFTER_BILLING_END = 30


def _deadline(billing_period_end: date | None) -> str | None:
    if billing_period_end is None:
        return None
    return (billing_period_end + timedelta(days=RAW_DELETE_DAYS_AFTER_BILLING_END)).isoformat()


def build_plan(*, billing_period_end: date | None = None) -> dict:
    return {
        "schema_version": "1",
        "purpose": (
            "Fail-closed retention plan for a prospective ThetaData historical-data acquisition. "
            "This plan does not authorize or start a subscription and does not claim G2 coverage."
        ),
        "vendor": "ThetaData",
        "written_terms_source_date": "2026-10-02",
        "commercial_terms": {
            "options_pro_monthly_usd": 160,
            "stock_pro_monthly_usd": 160,
            "one_month_bundle_total_usd": 320,
            "private_research_options_pro_eligible": True,
            "raw_unmodified_data_delete_days_after_billing_period_end": 30,
            "derived_or_modified_research_data_retention_allowed": True,
        },
        "requested_scope": {
            "option_pairs_per_record_kind": 3014,
            "option_requests_trades_plus_quotes": 6028,
            "stock_pairs_per_record_kind": 1430,
            "stock_requests_trades_plus_quotes": 2860,
            "options_tick_history_start": "2012-06-01",
            "stock_utp_tick_history_start": "2012-06-01",
        },
        "activation": {
            "subscription_authorized": False,
            "purchase_authority": False,
            "coverage_claimed": False,
            "billing_period_end": billing_period_end.isoformat() if billing_period_end else None,
            "raw_delete_deadline": _deadline(billing_period_end),
            "deadline_status": "PENDING_SUBSCRIPTION_START" if billing_period_end is None else "CALCULATED",
        },
        "storage_policy": {
            "raw_vendor_payload_committed_to_repository": False,
            "raw_vendor_payload_local_only": True,
            "raw_unmodified_data_must_be_deleted_by_deadline": True,
            "derived_or_modified_research_data_may_be_retained": True,
            "retain_sha256_and_size_receipts_after_raw_deletion": True,
            "retain_license_reference_after_raw_deletion": True,
            "retain_request_manifests_after_raw_deletion": True,
            "retain_validation_and_coverage_receipts_after_raw_deletion": True,
            "future_raw_replay_requires_reacquisition_under_valid_entitlement": True,
        },
        "required_workflow": [
            {
                "step": 1,
                "name": "Explicit purchase authorization",
                "requirement": (
                    "Do not subscribe until the user explicitly authorizes the $320 one-month "
                    "Options Pro + Stock Pro purchase."
                ),
            },
            {
                "step": 2,
                "name": "Capture binding terms",
                "requirement": (
                    "Record the applicable order/subscription terms, license reference, billing-period "
                    "end date, and computed raw-delete deadline before bulk acquisition."
                ),
            },
            {
                "step": 3,
                "name": "Local-only raw intake",
                "requirement": (
                    "Keep raw vendor payloads outside the repository. Run licensed_data_intake and "
                    "g2_vendor_delivery_preflight, preserving file SHA-256, size, date/symbol scope, "
                    "format, and license reference."
                ),
            },
            {
                "step": 4,
                "name": "Production validation and derivation",
                "requirement": (
                    "Before deletion, run production schema/date/symbol/content validation and produce "
                    "the authorized derived research outputs needed by the pipeline. Do not count file "
                    "presence as coverage."
                ),
            },
            {
                "step": 5,
                "name": "Retention classification",
                "requirement": (
                    "Classify every retained artifact as derived/modified research output or metadata/"
                    "receipt. Do not assume normalized row-level copies qualify as derived if they "
                    "substantially reproduce the vendor raw dataset."
                ),
            },
            {
                "step": 6,
                "name": "Raw deletion and deletion receipt",
                "requirement": (
                    "Delete all raw/unmodified ThetaData historical payloads no later than 30 days "
                    "after the billing period ends and retain only hashes, license/provenance records, "
                    "permitted derived/modified outputs, and a deletion receipt."
                ),
            },
            {
                "step": 7,
                "name": "Future replay rule",
                "requirement": (
                    "If a later audit or model rebuild requires raw rows after deletion, reacquire them "
                    "under a then-valid entitlement rather than silently treating hashes or derived "
                    "outputs as substitute raw coverage."
                ),
            },
        ],
        "guardrails": {
            "candidate_is_not_coverage": True,
            "subscription_requires_explicit_user_authorization": True,
            "raw_delivery_is_not_authorization": True,
            "raw_hash_receipt_is_not_raw_data": True,
            "derived_retention_does_not_waive_raw_delete_requirement": True,
            "g2_release_gate_unchanged": True,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build ThetaData raw-retention compliance plan.")
    parser.add_argument("--billing-period-end")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    billing_end = date.fromisoformat(args.billing_period_end) if args.billing_period_end else None
    payload = build_plan(billing_period_end=billing_end)
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
