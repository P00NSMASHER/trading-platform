from pathlib import Path

import g2_vendor_request_manifests as manifests


ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "data/processed/real_data_release_sprint/g2_champion_minimum_source_date_requirements.csv"


def test_vendor_request_manifests_match_frozen_scope(tmp_path: Path):
    summary = manifests.write_manifests(
        manifests.load_requirements(REQ),
        tmp_path,
    )

    assert summary["champion_minimum_source_date_rows"] == 1242
    assert summary["total_record_kind_symbol_date_pairs"] == 11484
    assert summary["routes"] == {
        "candidate_tickdata_equity_trades": {
            "file": "tickdata_equity_trades.csv",
            "source_date_rows": 414,
            "symbol_date_pair_count": 3828,
        },
        "candidate_tickdata_equity_nbbo_quotes": {
            "file": "tickdata_equity_nbbo_quotes.csv",
            "source_date_rows": 414,
            "symbol_date_pair_count": 3828,
        },
        "candidate_databento_opra_trades": {
            "file": "databento_opra_trades.csv",
            "source_date_rows": 226,
            "symbol_date_pair_count": 2875,
        },
        "candidate_cboe_option_trades": {
            "file": "cboe_option_trades.csv",
            "source_date_rows": 83,
            "symbol_date_pair_count": 489,
        },
        "candidate_lseg_opra_tick_history": {
            "file": "lseg_opra_tick_history.csv",
            "source_date_rows": 105,
            "symbol_date_pair_count": 464,
        },
    }

    for item in summary["routes"].values():
        assert (tmp_path / item["file"]).exists()
    assert (tmp_path / "vendor_request_summary.json").exists()
