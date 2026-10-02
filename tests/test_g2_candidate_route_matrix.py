from pathlib import Path

import g2_candidate_route_matrix as matrix


ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "data/processed/real_data_release_sprint/g2_champion_minimum_source_date_requirements.csv"


def test_conservative_candidate_route_matrix_matches_frozen_scope():
    manifest = matrix.build_matrix(matrix.load_requirements(REQ))

    assert manifest["champion_minimum_rows"] == 1242
    assert manifest["candidate_rows"] == 1242
    assert manifest["unresolved_rows"] == 0
    assert manifest["candidate_fraction"] == 1.0

    assert manifest["route_counts"] == {
        "candidate_cboe_option_trades": 83,
        "candidate_databento_opra_trades": 226,
        "candidate_lseg_opra_tick_history": 105,
        "candidate_tickdata_equity_nbbo_quotes": 414,
        "candidate_tickdata_equity_trades": 414,
    }
    assert manifest["route_symbol_date_pair_counts"] == {
        "candidate_cboe_option_trades": 489,
        "candidate_databento_opra_trades": 2875,
        "candidate_lseg_opra_tick_history": 464,
        "candidate_tickdata_equity_nbbo_quotes": 3828,
        "candidate_tickdata_equity_trades": 3828,
    }
    assert manifest["unresolved_by_record_kind"] == {}


def test_matrix_has_candidate_source_for_every_champion_minimum_row():
    manifest = matrix.build_matrix(matrix.load_requirements(REQ))

    unresolved = [row for row in manifest["rows"] if row["route"].startswith("unresolved_")]
    assert unresolved == []
    assert all(row["route"].startswith("candidate_") for row in manifest["rows"])
