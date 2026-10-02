from pathlib import Path

import g2_vendor_activation_blueprint as blueprint


ROOT = Path(__file__).resolve().parents[1]
VENDOR_DIR = ROOT / "data/processed/g2_vendor_requests"
SOURCE_BLUEPRINT = ROOT / "data/processed/real_data_release_sprint/production_source_contract_blueprint.json"


def test_vendor_activation_blueprint_is_fail_closed_and_complete():
    payload = blueprint.build_blueprint(VENDOR_DIR, SOURCE_BLUEPRINT)

    assert payload["champion_minimum_source_date_rows"] == 1242
    assert payload["total_record_kind_symbol_date_pairs"] == 11484
    assert len(payload["profiles"]) == 5
    assert payload["global_policy"]["authorized_defaults_false"] is True
    assert payload["global_policy"]["credentials_prohibited"] is True

    by_route = {profile["route"]: profile for profile in payload["profiles"]}
    assert by_route["candidate_tickdata_equity_trades"]["source_date_rows"] == 414
    assert by_route["candidate_tickdata_equity_nbbo_quotes"]["source_date_rows"] == 414
    assert by_route["candidate_databento_opra_trades"]["source_date_rows"] == 226
    assert by_route["candidate_cboe_option_trades"]["source_date_rows"] == 83
    assert by_route["candidate_lseg_opra_tick_history"]["source_date_rows"] == 105

    assert by_route["candidate_tickdata_equity_trades"]["symbol_date_pair_count"] == 3828
    assert by_route["candidate_tickdata_equity_nbbo_quotes"]["symbol_date_pair_count"] == 3828
    assert by_route["candidate_databento_opra_trades"]["symbol_date_pair_count"] == 2875
    assert by_route["candidate_cboe_option_trades"]["symbol_date_pair_count"] == 489
    assert by_route["candidate_lseg_opra_tick_history"]["symbol_date_pair_count"] == 464

    for profile in payload["profiles"]:
        assert profile["activation_status"] == "PENDING_DELIVERY_LICENSE_SCHEMA_REVIEW"
        assert profile["delivery"]["path"] == ""
        assert profile["delivery"]["license_reference"] == ""
        assert profile["entitlement_template"]["authorized"] is False
        assert profile["entitlement_template"]["sha256"] == ""
        assert profile["entitlement_template"]["license_reference"] == ""
        assert profile["required_canonical_fields"]
        assert profile["activation_rules"]["exact_sha256_binding_required"] is True
        assert profile["activation_rules"]["file_existence_alone_never_counts_as_coverage"] is True


def test_committed_vendor_activation_blueprint_matches_generator():
    import json

    generated = blueprint.build_blueprint(VENDOR_DIR, SOURCE_BLUEPRINT)
    committed = json.loads(
        (VENDOR_DIR / "vendor_activation_blueprint.json").read_text(encoding="utf-8")
    )
    assert generated == committed
