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



def test_wrds_reference_sas_files_abort_unconditionally():
    # Raw upstream examples are retained for provenance, not as an
    # alternate path around the authorized adapted extractors.
    root = ROOT / "vendor_sources/wrds/gen_li"
    for name in ("WRDS_batch_ticker_cq.sas", "WRDS_batch_ticker_ct.sas"):
        content = (root / name).read_text(encoding="utf-8")
        assert content.startswith("/* PROVENANCE-ONLY REFERENCE COPY: NEVER RUN.")
        program = content.split("*/", 1)[1].lstrip()
        assert program.startswith("%macro g2_wrds_provenance_abort;")
        assert (
            program.index("%abort cancel;")
            < program.index("%mend;")
            < program.index("%g2_wrds_provenance_abort;")
            < program.index("filename input")
        )

    for name in ("g2_wrds_taq_legacy.sas", "g2_wrds_taq_msec.sas"):
        content = (root / name).read_text(encoding="utf-8")
        assert "%macro g2_require_wrds_entitlement;" in content
        assert "%sysget(G2_WRDS_AUTHORIZED)" in content
        assert (
            content.index("%abort cancel;")
            < content.index("%mend;")
            < content.index("%g2_require_wrds_entitlement;")
            < content.index("data g2_pairs;")
        )
