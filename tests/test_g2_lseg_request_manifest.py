from pathlib import Path

import g2_lseg_request_manifest as lseg


ROOT = Path(__file__).resolve().parents[1]
MAPPING = ROOT / "data/processed/g2_vendor_requests/lseg_equity_ric_mapping.csv"
SECONDARY = ROOT / "data/processed/g2_vendor_requests/lseg_secondary_ric_candidates.csv"
EVENT_MAPPING = ROOT / "data/processed/g2_vendor_requests/lseg_event_permno_ric_mapping.csv"
CORE = ROOT / "data/processed/real_data_release_sprint/g2_core_source_date_requirements.csv"
OPTIONS = ROOT / "data/processed/real_data_release_sprint/g2_option_source_date_requirements.csv"


def _plan():
    return lseg.build_plan(
        lseg._read_csv(MAPPING),
        lseg._read_csv(SECONDARY),
        lseg._read_csv(EVENT_MAPPING),
        lseg._read_csv(CORE),
        lseg._read_csv(OPTIONS),
    )


def test_lseg_plan_matches_frozen_g2_scope():
    plan = _plan()

    assert plan["mapping_summary"]["g2_unique_symbols"] == 146
    assert plan["mapping_summary"]["study_permno_linked_companion_symbols"] == 111
    assert plan["mapping_summary"]["companion_root_only_symbols"] == 1
    assert plan["mapping_summary"]["companion_root_only_symbol_list"] == ["MUSA"]
    assert plan["mapping_summary"]["secondary_repository_candidate_symbols"] == 34
    assert plan["mapping_summary"]["unresolved_symbols"] == 0

    assert plan["request_summary"]["equity_total_candidate_symbol_kind_dates"] == 7656
    assert plan["request_summary"]["equity_study_permno_linked_symbol_kind_dates"] == 5764
    assert plan["request_summary"]["equity_companion_root_only_symbol_kind_dates"] == 88
    assert plan["request_summary"]["equity_secondary_symbol_kind_dates"] == 1804
    assert plan["request_summary"]["equity_unresolved_symbol_kind_dates"] == 0

    assert plan["request_summary"]["option_total_candidate_underlying_kind_dates"] == 7656
    assert plan["request_summary"]["option_study_permno_linked_underlying_kind_dates"] == 5764
    assert plan["request_summary"]["option_companion_root_only_underlying_kind_dates"] == 88
    assert plan["request_summary"]["option_secondary_underlying_kind_dates"] == 1804
    assert plan["request_summary"]["option_unresolved_underlying_kind_dates"] == 0


def test_lseg_plan_preserves_strict_field_contract_and_validation_labels():
    plan = _plan()

    assert plan["source_contract"]["allow_historical_instruments"] is True
    assert plan["source_contract"]["equity_fields"] == [
        "#RIC",
        "Date-Time",
        "Price",
        "Volume",
        "Bid Price",
        "Bid Size",
        "Ask Price",
        "Ask Size",
    ]
    assert "No authentication, API call, download, purchase, or G2 coverage mutation" in plan["purpose"]

    strong = [
        row for row in plan["equity_requests"]
        if row["mapping_class"] == "study_permno_linked_companion_match"
    ]
    weak = [
        row for row in plan["equity_requests"]
        if row["mapping_class"] != "study_permno_linked_companion_match"
    ]
    assert strong
    assert weak
    assert all(row["status"] == "candidate_direct_time_and_sales" for row in strong)
    assert all(
        row["status"] == "candidate_time_and_sales_historical_identifier_validation_required"
        for row in weak
    )
    assert plan["unresolved"] == []
