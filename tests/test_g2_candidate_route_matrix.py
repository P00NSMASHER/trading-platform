from pathlib import Path

import g2_candidate_route_matrix as matrix


ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "data/processed/real_data_release_sprint/g2_champion_minimum_source_date_requirements.csv"


def test_conservative_candidate_route_matrix_matches_frozen_scope():
    manifest = matrix.build_matrix(matrix.load_requirements(REQ))

    assert manifest["champion_minimum_rows"] == 1242
    assert manifest["candidate_rows"] == 1137
    assert manifest["unresolved_rows"] == 105
    assert manifest["candidate_fraction"] == 1137 / 1242

    assert manifest["route_counts"] == {
        "candidate_cboe_option_trades": 83,
        "candidate_databento_opra_trades": 226,
        "candidate_tickdata_equity_nbbo_quotes": 414,
        "candidate_tickdata_equity_trades": 414,
        "unresolved_2011_option_trade": 105,
    }
    assert manifest["unresolved_by_record_kind"] == {
        "option_trade": 105,
    }


def test_matrix_never_counts_uncertain_rows_as_candidates():
    manifest = matrix.build_matrix(matrix.load_requirements(REQ))

    unresolved = [row for row in manifest["rows"] if row["route"].startswith("unresolved_")]
    assert len(unresolved) == 105
    assert all(
        row["record_kind"] == "option_trade"
        for row in unresolved
    )
