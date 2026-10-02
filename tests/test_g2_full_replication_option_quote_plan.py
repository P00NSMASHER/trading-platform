from pathlib import Path

import g2_full_replication_option_quote_plan as plan


ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "data/processed/real_data_release_sprint/g2_option_source_date_requirements.csv"


def test_full_replication_option_quote_plan_matches_frozen_scope():
    rows, summary = plan.build_plan(plan.load_requirements(REQ))

    assert len(rows) == 414
    assert summary["full_replication_option_quote_source_date_rows"] == 414
    assert summary["full_replication_option_quote_symbol_date_pairs"] == 3828
    assert summary["unique_historical_underlyings"] == 146
    assert summary["first_trade_date"] == "2011-03-21"
    assert summary["last_trade_date"] == "2015-05-20"

    assert summary["slices"]["2011"] == {
        "route": "candidate_lseg_opra_tick_history_option_quotes",
        "source_date_rows": 105,
        "symbol_date_pair_count": 464,
        "unique_historical_underlyings": 35,
    }
    assert summary["slices"]["2012_2015"] == {
        "route": "candidate_algoseek_us_options_tanq",
        "source_date_rows": 309,
        "symbol_date_pair_count": 3364,
        "unique_historical_underlyings": 137,
    }

    assert {row["record_kind"] for row in rows} == {"option_quote"}
    assert {
        row["route"] for row in rows if row["trade_date"] < "2012-01-01"
    } == {"candidate_lseg_opra_tick_history_option_quotes"}
    assert {
        row["route"] for row in rows if row["trade_date"] >= "2012-01-01"
    } == {"candidate_algoseek_us_options_tanq"}
    assert {row["candidate_source_family"] for row in rows} == {
        "generic_authorized_market_data"
    }


def test_full_replication_quote_plan_keeps_tick_fidelity_fail_closed():
    _, summary = plan.build_plan(plan.load_requirements(REQ))

    candidates = {item["vendor"]: item for item in summary["preferred_candidate_split"]}
    assert candidates["LSEG"]["status"] == "CANDIDATE_SOURCE_AVAILABLE_NOT_ACQUIRED"
    assert candidates["LSEG"]["source_date_rows"] == 105
    assert candidates["algoseek"]["status"] == "CANDIDATE_SOURCE_AVAILABLE_NOT_ACQUIRED"
    assert candidates["algoseek"]["source_date_rows"] == 309
    assert "conflicting evidence" in candidates["algoseek"]["history_basis"]
    assert summary["fidelity_requirement"]["tick_level_option_quote_updates"] is True
    assert summary["fidelity_requirement"]["minute_snapshot_substitution_allowed"] is False
    assert summary["policy"]["candidate_source_is_not_coverage"] is True
    assert summary["policy"]["purchase_not_authorized"] is True
    assert (
        summary["policy"]["conflicting_public_history_copy_requires_runtime_date_validation"]
        is True
    )
    assert summary["policy"]["canonical_full_g2_gate_unchanged"] is True
