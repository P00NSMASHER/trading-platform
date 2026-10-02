from pathlib import Path

import g2_candidate_route_matrix as matrix


ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "data/processed/real_data_release_sprint/g2_champion_minimum_source_date_requirements.csv"


def test_conservative_candidate_route_matrix_matches_frozen_scope():
    manifest = matrix.build_matrix(matrix.load_requirements(REQ))

    assert manifest["champion_minimum_rows"] == 1242
    assert manifest["candidate_rows"] == 854
    assert manifest["unresolved_rows"] == 388
    assert manifest["candidate_fraction"] == 854 / 1242

    assert manifest["route_counts"] == {
        "candidate_cboe_equity_trades": 414,
        "candidate_cboe_option_trades": 83,
        "candidate_databento_opra_trades": 226,
        "candidate_nasdaq_equity_tick_history": 131,
        "unresolved_2011_option_trade": 105,
        "unresolved_exact_equity_quote": 283,
    }
    assert manifest["unresolved_by_record_kind"] == {
        "equity_quote": 283,
        "option_trade": 105,
    }


def test_matrix_never_counts_uncertain_rows_as_candidates():
    manifest = matrix.build_matrix(matrix.load_requirements(REQ))

    unresolved = [row for row in manifest["rows"] if row["route"].startswith("unresolved_")]
    assert len(unresolved) == 388
    assert all(
        row["record_kind"] in {"equity_quote", "option_trade"}
        for row in unresolved
    )
