from pathlib import Path

import g2_nasdaq_tick_history_probe as probe


ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "data/processed/real_data_release_sprint/g2_champion_minimum_source_date_requirements.csv"


def test_nasdaq_tick_history_probe_matches_champion_minimum_scope():
    manifest = probe.build_probe_manifest(probe.load_requirements(REQ))

    assert manifest["high_quality_history_start"] == "2014-01-01"
    assert manifest["total_required_equity_dates"] == 414
    assert manifest["eligible_equity_dates"] == 131
    assert manifest["ineligible_pre_2014_equity_dates"] == 283
    assert manifest["eligible_equity_source_date_rows"] == 262
    assert manifest["eligible_equity_symbol_date_pairs"] == 2178
    assert manifest["ineligible_pre_2014_symbol_date_pairs"] == 1650
    assert manifest["champion_minimum_total_rows"] == 1242
    assert manifest["candidate_champion_minimum_rows"] == 262
    assert manifest["remaining_champion_minimum_rows_after_nasdaq_tick_history"] == 980

    assert all(row["g2_status"] == "candidate_exact_semantics" for row in manifest["eligible"])
    assert all(row["trade_date"] >= "2014-01-01" for row in manifest["eligible"])
    assert all(day < "2014-01-01" for day in manifest["ineligible_dates"])
