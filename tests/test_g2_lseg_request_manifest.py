from pathlib import Path

import g2_lseg_request_manifest as lseg


ROOT = Path(__file__).resolve().parents[1]
MAPPING = ROOT / "data/processed/g2_vendor_requests/lseg_equity_ric_mapping.csv"
SECONDARY = ROOT / "data/processed/g2_vendor_requests/lseg_secondary_ric_candidates.csv"
CORE = ROOT / "data/processed/real_data_release_sprint/g2_core_source_date_requirements.csv"
OPTIONS = ROOT / "data/processed/real_data_release_sprint/g2_option_source_date_requirements.csv"


def _plan():
    return lseg.build_plan(
        lseg._read_csv(MAPPING),
        lseg._read_csv(SECONDARY),
        lseg._read_csv(CORE),
        lseg._read_csv(OPTIONS),
    )


def test_lseg_plan_matches_frozen_g2_scope():
    plan = _plan()

    assert plan["mapping_summary"]["g2_unique_symbols"] == 146
    assert plan["mapping_summary"]["primary_exact_companion_symbols"] == 112
    assert plan["mapping_summary"]["secondary_repository_candidate_symbols"] == 34
    assert plan["mapping_summary"]["unresolved_symbols"] == 0

    assert plan["request_summary"]["equity_total_candidate_symbol_kind_dates"] == 7656
    assert plan["request_summary"]["equity_primary_symbol_kind_dates"] == 5852
    assert plan["request_summary"]["equity_secondary_symbol_kind_dates"] == 1804
    assert plan["request_summary"]["equity_unresolved_symbol_kind_dates"] == 0

    assert plan["request_summary"]["option_total_candidate_underlying_kind_dates"] == 7656
    assert plan["request_summary"]["option_primary_underlying_kind_dates"] == 5852
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

    primary = [
        row for row in plan["equity_requests"]
        if row["mapping_class"] == "primary_exact_companion_match"
    ]
    secondary = [
        row for row in plan["equity_requests"]
        if row["mapping_class"] == "secondary_repository_candidate"
    ]
    assert primary
    assert secondary
    assert all(row["status"] == "candidate_direct_time_and_sales" for row in primary)
    assert all(
        row["status"] == "candidate_time_and_sales_historical_identifier_validation_required"
        for row in secondary
    )
    assert plan["unresolved"] == []
