from pathlib import Path

import g2_full_replication_option_quote_plan as plan


ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "data/processed/real_data_release_sprint/g2_option_source_date_requirements.csv"
COMMITTED_DIR = ROOT / "data/processed/real_data_release_sprint/vendor_requests"


def test_full_replication_option_quote_plan_matches_frozen_scope():
    rows, summary = plan.build_plan(plan.load_requirements(REQ))

    assert len(rows) == 414
    assert summary["full_replication_option_quote_source_date_rows"] == 414
    assert summary["full_replication_option_quote_symbol_date_pairs"] == 3828
    assert summary["unique_historical_underlyings"] == 146
    assert summary["first_trade_date"] == "2011-03-21"
    assert summary["last_trade_date"] == "2015-05-20"

    assert summary["slices"]["pre_2012_06_01"] == {
        "route": "candidate_lseg_opra_tick_history_option_quotes",
        "source_date_rows": 123,
        "symbol_date_pair_count": 814,
        "unique_historical_underlyings": 35,
    }
    assert summary["slices"]["2012_06_01_onward"] == {
        "route": "candidate_thetadata_options_pro_option_quotes",
        "source_date_rows": 291,
        "symbol_date_pair_count": 3014,
        "unique_historical_underlyings": 115,
    }

    assert {row["record_kind"] for row in rows} == {"option_quote"}
    assert {
        row["route"] for row in rows if row["trade_date"] < "2012-06-01"
    } == {"candidate_lseg_opra_tick_history_option_quotes"}
    assert {
        row["route"] for row in rows if row["trade_date"] >= "2012-06-01"
    } == {"candidate_thetadata_options_pro_option_quotes"}
    assert {row["candidate_source_family"] for row in rows} == {
        "generic_authorized_market_data"
    }


def test_full_replication_quote_plan_keeps_tick_fidelity_fail_closed():
    _, summary = plan.build_plan(plan.load_requirements(REQ))

    candidates = {item["vendor"]: item for item in summary["preferred_candidate_split"]}
    assert candidates["LSEG"]["status"] == "CANDIDATE_SOURCE_AVAILABLE_NOT_ACQUIRED"
    assert candidates["LSEG"]["source_date_rows"] == 123
    assert candidates["ThetaData"]["status"] == "CANDIDATE_SOURCE_AVAILABLE_NOT_ACQUIRED"
    assert candidates["ThetaData"]["source_date_rows"] == 291
    assert (
        candidates["ThetaData"]["license_status"]
        == "PENDING_WRITTEN_USE_CLASSIFICATION_AND_RETENTION_TERMS"
    )
    assert summary["fallback_candidates"][0]["vendor"] == "algoseek"
    assert summary["fidelity_requirement"]["tick_level_option_quote_updates"] is True
    assert summary["fidelity_requirement"]["minute_snapshot_substitution_allowed"] is False
    assert summary["policy"]["candidate_source_is_not_coverage"] is True
    assert summary["policy"]["purchase_not_authorized"] is True
    assert summary["policy"]["thetadata_retail_license_not_assumed"] is True
    assert summary["policy"]["retention_rights_not_assumed"] is True
    assert summary["policy"]["canonical_full_g2_gate_unchanged"] is True


def test_committed_full_replication_option_quote_artifacts_are_reproducible(tmp_path: Path):
    output_csv = tmp_path / "lseg_opra_tick_history_option_quotes.csv"
    output_summary = tmp_path / "full_replication_option_quote_plan.json"

    plan.write_plan(
        plan.load_requirements(REQ),
        output_csv,
        output_summary,
    )

    assert output_csv.read_bytes() == (
        COMMITTED_DIR / "lseg_opra_tick_history_option_quotes.csv"
    ).read_bytes()

    import json

    assert json.loads(output_summary.read_text()) == json.loads(
        (COMMITTED_DIR / "full_replication_option_quote_plan.json").read_text()
    )
