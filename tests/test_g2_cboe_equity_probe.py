from pathlib import Path

import g2_cboe_equity_probe as probe


ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "data/processed/real_data_release_sprint/g2_champion_minimum_source_date_requirements.csv"


def test_cboe_equity_probe_matches_champion_minimum_scope():
    manifest = probe.build_probe_manifest(probe.load_requirements(REQ))

    assert manifest["historical_start"] == "2010-01-01"
    assert manifest["total_required_equity_dates"] == 414
    assert manifest["equity_trade_candidate_rows"] == 414
    assert manifest["equity_quote_interval_rows_not_counted"] == 414
    assert manifest["equity_symbol_date_pairs"] == 3828
    assert manifest["champion_minimum_total_rows"] == 1242
    assert manifest["candidate_champion_minimum_rows"] == 414
    assert manifest["remaining_champion_minimum_rows_after_equity_trades"] == 828

    for row in manifest["dates"]:
        trade = row["requests"]["equity_trade"]
        quote = row["requests"]["equity_quote_interval"]

        assert trade["g2_status"] == "candidate_direct_coverage"
        assert quote["g2_status"] == "fidelity_review_required_not_counted"
        assert trade["product"] == "Cboe Equity & ETF Trades"
        assert quote["product"] == "Cboe Equity & ETF Quotes"
