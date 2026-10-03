from pathlib import Path
import json

import g2_thetadata_coverage_impact as impact


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "data/processed/real_data_release_sprint/g2_core_source_date_requirements.csv"
OPTIONS = ROOT / "data/processed/real_data_release_sprint/g2_option_source_date_requirements.csv"
THETA_EQUITY = ROOT / "data/processed/g2_vendor_requests/cheap_route_partitions/thetadata_equity.csv"
THETA_OPTIONS = ROOT / "data/processed/g2_vendor_requests/cheap_route_partitions/thetadata_options.csv"
COMMITTED_JSON = ROOT / "data/processed/g2_vendor_requests/thetadata_coverage_impact.json"
COMMITTED_CSV = ROOT / "data/processed/g2_vendor_requests/thetadata_coverage_impact_rows.csv"


def test_thetadata_coverage_impact_matches_frozen_requirements():
    payload = impact.build_impact(CORE, OPTIONS, THETA_EQUITY, THETA_OPTIONS)

    canonical = payload["canonical_full_g2"]
    assert canonical["required_source_date_rows"] == 1656
    assert canonical["full_candidate_rows"] == 650
    assert canonical["partial_candidate_rows"] == 392
    assert canonical["untouched_rows"] == 614
    assert canonical["remaining_rows_not_fully_closed"] == 1006
    assert canonical["required_record_kind_symbol_date_pairs"] == 15312
    assert canonical["thetadata_touched_record_kind_symbol_date_pairs"] == 8888
    assert canonical["full_candidate_required_symbol_date_pairs"] == 6132

    assert canonical["by_record_kind"] == {
        "equity_quote": {
            "required_rows": 414,
            "full_candidate_rows": 34,
            "partial_candidate_rows": 196,
            "untouched_rows": 184,
            "required_symbol_date_pairs": 3828,
            "touched_symbol_date_pairs": 1430,
        },
        "equity_trade": {
            "required_rows": 414,
            "full_candidate_rows": 34,
            "partial_candidate_rows": 196,
            "untouched_rows": 184,
            "required_symbol_date_pairs": 3828,
            "touched_symbol_date_pairs": 1430,
        },
        "option_quote": {
            "required_rows": 414,
            "full_candidate_rows": 291,
            "partial_candidate_rows": 0,
            "untouched_rows": 123,
            "required_symbol_date_pairs": 3828,
            "touched_symbol_date_pairs": 3014,
        },
        "option_trade": {
            "required_rows": 414,
            "full_candidate_rows": 291,
            "partial_candidate_rows": 0,
            "untouched_rows": 123,
            "required_symbol_date_pairs": 3828,
            "touched_symbol_date_pairs": 3014,
        },
    }

    champion = payload["champion_minimum"]
    assert champion["required_source_date_rows"] == 1242
    assert champion["full_candidate_rows"] == 359
    assert champion["partial_candidate_rows"] == 392
    assert champion["untouched_rows"] == 491
    assert champion["remaining_rows_not_fully_closed"] == 883
    assert champion["required_record_kind_symbol_date_pairs"] == 11484
    assert champion["thetadata_touched_record_kind_symbol_date_pairs"] == 5874
    assert champion["full_candidate_required_symbol_date_pairs"] == 3118

    assert payload["written_bundle_price_usd"] == 320
    assert payload["request_plan_total_requests"] == 8888
    assert payload["retention_constraint"]["raw_delete_days_after_billing_period_end"] == 30
    assert payload["guardrails"]["purchase_requires_explicit_user_authorization"] is True


def test_committed_thetadata_impact_matches_generator(tmp_path: Path):
    payload = impact.build_impact(CORE, OPTIONS, THETA_EQUITY, THETA_OPTIONS)
    json_out = tmp_path / "impact.json"
    csv_out = tmp_path / "impact.csv"
    impact.write_impact(payload, json_out, csv_out)

    assert json.loads(json_out.read_text()) == json.loads(COMMITTED_JSON.read_text())
    assert csv_out.read_bytes() == COMMITTED_CSV.read_bytes()
