from pathlib import Path

import g2_vendor_readiness as readiness


ROOT = Path(__file__).resolve().parents[1]
VENDOR_DIR = ROOT / "data/processed/g2_vendor_requests"
COVERAGE = ROOT / "data/processed/coverage_plan_real/coverage_summary.json"


def test_vendor_readiness_separates_repo_planning_from_real_coverage():
    payload = readiness.build_readiness(VENDOR_DIR, COVERAGE)

    assert payload["champion_minimum_scope"] == {
        "source_date_rows": 1242,
        "record_kind_symbol_date_pairs": 11484,
        "candidate_route_count": 5,
    }
    assert payload["repository_readiness"] == {
        "vendor_request_manifests_ready": True,
        "vendor_quote_packets_ready": True,
        "fail_closed_activation_blueprint_ready": True,
        "delivery_preflight_tool_ready": True,
        "databento_cost_only_workflow_ready": True,
        "cboe_trial_capacity_plan_ready": True,
    }

    assert payload["canonical_full_g2_state"] == {
        "required_source_date_rows": 1656,
        "validated_authorized_source_date_rows": 0,
        "missing_validated_authorized_source_date_rows": 1656,
        "ready_for_real_backfill": False,
    }
    assert payload["champion_minimum_validated_coverage"]["separately_measured"] is False

    assert payload["external_state"]["vendor_quotes_or_pricing"] == "PARTIAL_QUOTES_RECEIVED"
    assert payload["external_state"]["license_or_entitlement_terms"] == "PENDING_EXTERNAL"
    assert payload["external_state"]["licensed_data_delivery"] == "PENDING_EXTERNAL"
    assert payload["external_state"]["production_content_validation"] == "BLOCKED_ON_DELIVERY"
    assert payload["external_state"]["databento_cost_probe"] == "BLOCKED_API_KEY_NOT_CONFIGURED"
    assert payload["external_state"]["cboe_trial_historical_access"] == "DOCUMENTED_ELIGIBLE_NOT_RUNTIME_VERIFIED"
    assert payload["external_state"]["cboe_custom_tick_quote"] == "FULL_UNIVERSE_ONLY_QUOTE_RECEIVED_OUT_OF_SCOPE"
    assert payload["external_state"]["tickdata_written_quote"] == "PHONE_CALL_REQUIRED_WRITTEN_QUOTE_UNAVAILABLE_FOR_NOW"
    assert payload["external_state"]["lseg_2011_quote"] == "REQUEST_SENT_AWAITING_REPLY"
    assert payload["external_state"]["algoseek_quote_and_sandbox_terms"] == "REQUEST_SENT_AWAITING_REPLY"

    assert payload["policy"] == {
        "candidate_source_is_not_coverage": True,
        "quote_packet_is_not_purchase_authority": True,
        "delivery_is_not_authorization": True,
        "file_presence_is_not_content_coverage": True,
        "g2_release_gate_unchanged": True,
        "free_trial_activation_requires_explicit_user_authorization": True,
    }


def test_readiness_next_actions_cover_every_external_dependency():
    payload = readiness.build_readiness(VENDOR_DIR, COVERAGE)
    actions = "\n".join(payload["next_external_actions"])

    assert "DATABENTO_API_KEY" in actions
    assert "Tick Data" in actions
    assert "written quote as unavailable for now" in actions
    assert "Cboe" in actions
    assert "full-universe delivery" in actions
    assert "outside the project scope" in actions
    assert "explicit user authorization" in actions
    assert "runtime access is not verified" in actions
    assert "seq_no pagination" in actions
    assert "LSEG" in actions
    assert "algoseek" in actions
    assert "local drop folder" in actions
    assert "entitlement manifest" in actions


def test_committed_vendor_readiness_matches_generator():
    import json

    generated = readiness.build_readiness(VENDOR_DIR, COVERAGE)
    committed = json.loads(
        (VENDOR_DIR / "vendor_readiness.json").read_text(encoding="utf-8")
    )
    assert generated == committed
