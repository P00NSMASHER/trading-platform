from pathlib import Path

import g2_lseg_request_manifest as lseg


ROOT = Path(__file__).resolve().parents[1]
MAPPING = ROOT / "data/processed/g2_vendor_requests/lseg_equity_ric_mapping.csv"
CORE = ROOT / "data/processed/real_data_release_sprint/g2_core_source_date_requirements.csv"
OPTIONS = ROOT / "data/processed/real_data_release_sprint/g2_option_source_date_requirements.csv"


def test_lseg_plan_matches_frozen_g2_scope():
    plan = lseg.build_plan(
        lseg._read_csv(MAPPING),
        lseg._read_csv(CORE),
        lseg._read_csv(OPTIONS),
    )

    assert plan["mapping_summary"]["g2_unique_symbols"] == 146
    assert plan["mapping_summary"]["mapped_symbols"] == 112
    assert plan["mapping_summary"]["unresolved_symbols"] == 34

    assert plan["request_summary"]["equity_mapped_symbol_kind_dates"] == 5852
    assert plan["request_summary"]["equity_unresolved_symbol_kind_dates"] == 1804
    assert plan["request_summary"]["option_mapped_underlying_kind_dates"] == 5852
    assert plan["request_summary"]["option_unresolved_underlying_kind_dates"] == 1804

    assert len(plan["equity_requests"]) + plan["request_summary"]["equity_unresolved_symbol_kind_dates"] == 7656
    assert len(plan["option_underlying_requests"]) + plan["request_summary"]["option_unresolved_underlying_kind_dates"] == 7656


def test_lseg_plan_preserves_strict_field_contract_and_no_coverage_claim():
    plan = lseg.build_plan(
        lseg._read_csv(MAPPING),
        lseg._read_csv(CORE),
        lseg._read_csv(OPTIONS),
    )

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
    assert all(row["status"] == "candidate_direct_time_and_sales" for row in plan["equity_requests"])
    assert all(
        row["status"] == "candidate_underlying_mapped_option_contract_resolution_required"
        for row in plan["option_underlying_requests"]
    )
