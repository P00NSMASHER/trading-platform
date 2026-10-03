from datetime import date
from pathlib import Path
import json

import g2_thetadata_retention_plan as plan


ROOT = Path(__file__).resolve().parents[1]
COMMITTED = ROOT / "data/processed/g2_vendor_requests/thetadata_retention_plan.json"


def test_thetadata_retention_plan_is_fail_closed_before_purchase():
    payload = plan.build_plan()

    assert payload["commercial_terms"]["one_month_bundle_total_usd"] == 320
    assert payload["commercial_terms"]["raw_unmodified_data_delete_days_after_billing_period_end"] == 30
    assert payload["commercial_terms"]["derived_or_modified_research_data_retention_allowed"] is True

    assert payload["activation"] == {
        "subscription_authorized": False,
        "purchase_authority": False,
        "coverage_claimed": False,
        "billing_period_end": None,
        "raw_delete_deadline": None,
        "deadline_status": "PENDING_SUBSCRIPTION_START",
    }

    assert payload["storage_policy"]["raw_vendor_payload_committed_to_repository"] is False
    assert payload["storage_policy"]["raw_vendor_payload_local_only"] is True
    assert payload["storage_policy"]["future_raw_replay_requires_reacquisition_under_valid_entitlement"] is True
    assert payload["guardrails"]["subscription_requires_explicit_user_authorization"] is True
    assert payload["guardrails"]["g2_release_gate_unchanged"] is True


def test_thetadata_retention_deadline_is_30_days_after_billing_end():
    payload = plan.build_plan(billing_period_end=date(2026, 10, 31))

    assert payload["activation"]["billing_period_end"] == "2026-10-31"
    assert payload["activation"]["raw_delete_deadline"] == "2026-11-30"
    assert payload["activation"]["deadline_status"] == "CALCULATED"


def test_committed_thetadata_retention_plan_matches_generator():
    assert json.loads(COMMITTED.read_text(encoding="utf-8")) == plan.build_plan()
