from pathlib import Path

import g2_lseg_secondary_validation_manifest as validation


ROOT = Path(__file__).resolve().parents[1]
SECONDARY = ROOT / "data/processed/g2_vendor_requests/lseg_secondary_ric_candidates.csv"
CORE = ROOT / "data/processed/real_data_release_sprint/g2_core_source_date_requirements.csv"
OPTIONS = ROOT / "data/processed/real_data_release_sprint/g2_option_source_date_requirements.csv"


def test_secondary_lseg_validation_manifest_matches_frozen_scope():
    manifest = validation.build_validation_manifest(
        validation._read_csv(SECONDARY),
        validation._read_csv(CORE),
        validation._read_csv(OPTIONS),
    )

    assert manifest["summary"] == {
        "secondary_symbols": 34,
        "unique_symbol_date_validation_jobs": 902,
        "lane_symbol_date_checks_represented": 1804,
        "record_kind_symbol_date_checks_represented": 3608,
        "min_trade_date": "2011-03-21",
        "max_trade_date": "2015-05-20",
        "unresolved_candidate_jobs": 902,
        "g2_coverage_change": False,
    }

    jobs = manifest["jobs"]
    assert len(jobs) == 902
    assert len({(row["trade_date"], row["historical_symbol"]) for row in jobs}) == 902
    assert len({row["historical_symbol"] for row in jobs}) == 34
    assert all(row["candidate_rics"] for row in jobs)
    assert all(row["required_lanes"] == "equity;options" for row in jobs)
    assert all(
        row["required_record_kinds"]
        == "equity_quote;equity_trade;option_quote;option_trade"
        for row in jobs
    )
    assert all(
        row["validation_status"] == "requires_live_lseg_historical_date_validation"
        for row in jobs
    )


def test_secondary_lseg_validation_manifest_remains_fail_closed():
    manifest = validation.build_validation_manifest(
        validation._read_csv(SECONDARY),
        validation._read_csv(CORE),
        validation._read_csv(OPTIONS),
    )

    assert manifest["summary"]["g2_coverage_change"] is False
    assert manifest["summary"]["unresolved_candidate_jobs"] == len(manifest["jobs"])
    assert "no API call" in manifest["purpose"]


def test_secondary_manifest_rejects_prematurely_promoted_candidate():
    secondary = validation._read_csv(SECONDARY)
    secondary[0] = dict(secondary[0])
    secondary[0]["validation_status"] = "validated"

    try:
        validation.build_validation_manifest(
            secondary,
            validation._read_csv(CORE),
            validation._read_csv(OPTIONS),
        )
    except ValueError as exc:
        assert "not fail-closed" in str(exc)
    else:
        raise AssertionError("prematurely validated secondary RIC was accepted")
