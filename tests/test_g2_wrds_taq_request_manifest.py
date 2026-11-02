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


def test_wrds_access_contract_fails_closed_for_personal_direct_access():
    payload = wrds.build_requests(wrds._read(TRADES), wrds._read(QUOTES))
    access = payload["access_contract"]
    assert access["personal_direct_wrds_access"] is False
    assert access["coverage_authority"] is False
    assert "institution/entity WRDS authorization" in access["execution_requires"]
    assert "157666" in access["support_ticket"]



def test_wrds_access_plan_does_not_bundle_unlicensed_sas():
    # A publicly visible upstream repository without a declared redistribution
    # license is a research reference, not permission to copy source files.
    upstream = "https://github.com/gen-li/Extract_TAQ_from_WRDS_Cloud"
    payload = wrds.build_requests(wrds._read(TRADES), wrds._read(QUOTES))
    assert payload["source_logic"]["upstream_reference"] == upstream
    assert payload["access_contract"]["personal_direct_wrds_access"] is False
    assert payload["access_contract"]["coverage_authority"] is False
    assert not (ROOT / "vendor_sources" / "wrds" / "gen_li"
                / "WRDS_batch_ticker_cq.sas").exists()
    assert not (ROOT / "vendor_sources" / "wrds" / "gen_li"
                / "WRDS_batch_ticker_ct.sas").exists()


def test_wrds_manifest_rejects_mismatched_trade_quote_rows():
    import pytest
    trades = wrds._read(TRADES)
    quotes = wrds._read(QUOTES)
    with pytest.raises(ValueError, match="row-count mismatch"):
        wrds.build_requests(trades, quotes[:-1])
    altered = [dict(row) for row in quotes]
    altered[0]["historical_symbols"] = "NOT_AN_AUTHORIZED_SUBSTITUTE"
    with pytest.raises(ValueError, match="symbol mismatch"):
        wrds.build_requests(trades, altered)
