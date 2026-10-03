from pathlib import Path

import g2_wrds_taq_request_manifest as wrds


ROOT = Path(__file__).resolve().parents[1]
TRADES = ROOT / "data/processed/g2_vendor_requests/tickdata_equity_trades.csv"
QUOTES = ROOT / "data/processed/g2_vendor_requests/tickdata_equity_nbbo_quotes.csv"


def test_wrds_request_manifest_matches_frozen_g2_equity_scope():
    payload = wrds.build_requests(wrds._read(TRADES), wrds._read(QUOTES))

    assert payload["source_date_rows"] == 414
    assert payload["symbol_date_pairs"] == 3828
    assert payload["unique_symbols"] == 146
    assert payload["legacy_symbol_date_pairs"] == 836
    assert payload["millisecond_symbol_date_pairs"] == 2992

    assert payload["legacy"][0] == {"smbl": "JNPR", "dates": "20110321"}
    assert payload["millisecond"][-1] == {"smbl": "SCVL", "dates": "20150520"}

    all_pairs = payload["legacy"] + payload["millisecond"]
    assert len({(row["smbl"], row["dates"]) for row in all_pairs}) == 3828


def test_wrds_manifest_stays_dry_run_and_fail_closed_for_nbbo():
    payload = wrds.build_requests(wrds._read(TRADES), wrds._read(QUOTES))

    assert "no WRDS login, query, download" in payload["purpose"]
    assert "strict NBBO coverage" in payload["source_logic"]["note"]
    assert payload["source_logic"]["legacy_tables"] == [
        "taq.ct_YYYYMMDD",
        "taq.cq_YYYYMMDD",
    ]
    assert payload["source_logic"]["millisecond_tables"] == [
        "taqmsec.ctm_YYYYMMDD",
        "taqmsec.cqm_YYYYMMDD",
    ]
