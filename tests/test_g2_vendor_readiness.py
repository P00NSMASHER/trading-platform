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
        "vendor_reply_evidence_ready": True,
    }

    assert payload["canonical_full_g2_state"] == {
        "required_source_date_rows": 1656,
        "validated_authorized_source_date_rows": 0,
        "missing_validated_authorized_source_date_rows": 1656,
        "ready_for_real_backfill": False,
    }
    assert payload["champion_minimum_validated_coverage"]["separately_measured"] is False

    evidence = payload["vendor_reply_evidence"]
    assert evidence["source_path"] == "data/processed/g2_vendor_requests/vendor_reply_evidence_2026-10-02.json"
    assert evidence["as_of"] == "2026-10-02"
    assert evidence["coverage_effect"] == "NONE_UNTIL_ACTUAL_VALIDATED_ROWS"
    assert evidence["cboe_paid_bulk"] == {
        "research_disposition": "OUT_OF_SCOPE_CURRENT_RESEARCH",
        "sale_scope": "FULL_OPRA_UNIVERSE_ONLY",
        "rough_price_usd_2_years_5_months": 40000,
        "rough_price_usd_1_calendar_year": 24000,
        "selected_309_days_across_years": "CUSTOM_JOB_POSSIBLY_MORE_EXPENSIVE",
    }
    assert evidence["tick_data_written_quote"] == {
        "research_disposition": "UNPRICED_WRITTEN_QUOTE_UNAVAILABLE",
        "written_availability_confirmation": "NOT_PROVIDED",
        "written_price_usd": None,
        "vendor_response": "PHONE_CALL_REQUIRED",
    }
    assert evidence["cboe_zero_cost_acceptance_probe"]["pull_request"] == 258
    assert evidence["cboe_zero_cost_acceptance_probe"]["logical_separation"] == "SEPARATE_FROM_PAID_BULK_ACQUISITION"
    assert evidence["cboe_zero_cost_acceptance_probe"]["coverage_claimed"] is False
    assert evidence["cboe_zero_cost_acceptance_probe"]["coverage_count_mutation_allowed"] is False

    assert payload["external_state"]["vendor_quotes_or_pricing"] == "PARTIAL_EXTERNAL_QUOTES_RECEIVED"
    assert payload["external_state"]["license_or_entitlement_terms"] == "PENDING_EXTERNAL"
    assert payload["external_state"]["licensed_data_delivery"] == "PENDING_EXTERNAL"
    assert payload["external_state"]["production_content_validation"] == "BLOCKED_ON_DELIVERY"
    assert payload["external_state"]["databento_cost_probe"] == "BLOCKED_API_KEY_NOT_CONFIGURED"
    assert payload["external_state"]["cboe_trial_historical_access"] == "VENDOR_CONFIRMED_ELIGIBLE_RUNTIME_NOT_VERIFIED"
    assert payload["external_state"]["cboe_trial_option_quote_access"] == "DOCUMENTED_HISTORICAL_ENDPOINT_RUNTIME_TRIAL_ACCESS_UNVERIFIED"
    assert payload["external_state"]["cboe_trial_retention_rights"] == "DEFAULT_TERMINATION_DELETE_RETURN_UNLESS_ORDER_FORM_OVERRIDES"
    assert payload["external_state"]["cboe_custom_tick_quote"] == "QUOTE_RECEIVED_FULL_OPRA_ONLY_OUTSIDE_TARGET_BUDGET"
    assert payload["external_state"]["tickdata_written_quote"] == "WRITTEN_QUOTE_UNAVAILABLE_PHONE_CALL_REQUIRED"
    assert payload["external_state"]["lseg_2011_quote"] == "REQUEST_SENT_AWAITING_REPLY"
    assert payload["external_state"]["algoseek_quote_and_sandbox_terms"] == "REQUEST_SENT_AWAITING_REPLY"

    assert payload["policy"] == {
        "candidate_source_is_not_coverage": True,
        "quote_packet_is_not_purchase_authority": True,
        "delivery_is_not_authorization": True,
        "file_presence_is_not_content_coverage": True,
        "g2_release_gate_unchanged": True,
        "free_trial_activation_requires_explicit_user_authorization": True,
        "trial_download_is_not_retention_authority": True,
        "retention_rights_required_before_bulk_acquisition": True,
    }


def test_readiness_next_actions_cover_every_external_dependency():
    payload = readiness.build_readiness(VENDOR_DIR, COVERAGE)
    actions = "\n".join(payload["next_external_actions"])

    assert "DATABENTO_API_KEY" in actions
    assert "Tick Data" in actions
    assert "written quote as unavailable" in actions
    assert "Cboe" in actions
    assert "outside the target budget" in actions
    assert "explicit user authorization" in actions
    assert "daily credit limit does not gate the trial" in actions
    assert "acceptance probe" in actions
    assert "retained internal research use" in actions
    assert "deleted or returned" in actions
    assert "reference/options" in actions
    assert "option-quote pagination" in actions
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
