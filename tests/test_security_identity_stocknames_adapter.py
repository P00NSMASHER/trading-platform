from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import security_identity_stocknames_adapter as adapter


def queue_row(
    *,
    request_id="SID-ONE",
    permno="12345",
    symbol="ABC",
    trade_date="2015-02-12",
):
    return {
        "request_id": request_id,
        "permno": permno,
        "gvkey": "001234",
        "historical_symbol": symbol,
        "trade_date": trade_date,
        "event_ids": "HEJFE-AAAAAAAAAAAAAAAA",
        "status": "PENDING_STABLE_ID_EVIDENCE",
        "required_evidence": "DATED_STABLE_ID_CROSSWALK",
        "primary_lane": "LICENSED_STABLE_ID_MASTER",
        "secondary_lane": "AUTHORIZED_MARKET_SECURITY_MASTER",
        "corroboration_lane": "PUBLIC_CORPORATE_ACTION_CORROBORATION",
        "research_use_only": "1",
    }


def stockname(
    *,
    permno="12345",
    ticker="ABC",
    namedt="2010-01-01",
    nameenddt="2020-12-31",
):
    return {
        "permno": permno,
        "ticker": ticker,
        "namedt": namedt,
        "nameenddt": nameenddt,
    }


def test_exact_dated_permno_ticker_history_emits_stable_id_evidence():
    rows, summary = adapter.build_evidence(
        [queue_row()],
        [stockname()],
        source_sha256="a" * 64,
        authorization_reference="AUTHORIZED_STOCKNAMES_TEST",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["permno"] == "12345"
    assert row["historical_symbol"] == "ABC"
    assert row["market_identifier"] == "ABC"
    assert row["valid_from"] == "2015-02-12"
    assert row["valid_through"] == "2015-02-12"
    assert row["evidence_lane"] == "LICENSED_STABLE_ID_MASTER"
    assert row["source_reference"] == "stocknames-sha256:" + "a" * 64
    assert summary["counts"]["evidence_rows_emitted"] == 1
    assert summary["all_queue_requests_evidence_ready"] is True
    assert summary["policy"]["coverage_change"] is False


def test_historical_symbol_mismatch_stays_unresolved():
    rows, summary = adapter.build_evidence(
        [queue_row(symbol="ABC")],
        [stockname(ticker="XYZ")],
        source_sha256="b" * 64,
        authorization_reference="AUTHORIZED_STOCKNAMES_TEST",
    )

    assert rows == []
    assert summary["counts"]["historical_symbol_mismatch"] == 1
    assert summary["unresolved"][0]["reason"] == "HISTORICAL_SYMBOL_MISMATCH"


def test_requested_date_must_be_inside_dated_name_interval():
    rows, summary = adapter.build_evidence(
        [queue_row(trade_date="2015-02-12")],
        [stockname(namedt="2016-01-01", nameenddt="2020-12-31")],
        source_sha256="c" * 64,
        authorization_reference="AUTHORIZED_STOCKNAMES_TEST",
    )

    assert rows == []
    assert summary["counts"]["no_active_history"] == 1
    assert summary["unresolved"][0]["reason"] == "NO_ACTIVE_HISTORY"


def test_multiple_distinct_active_tickers_fail_closed():
    rows, summary = adapter.build_evidence(
        [queue_row()],
        [
            stockname(ticker="ABC"),
            stockname(ticker="XYZ"),
        ],
        source_sha256="d" * 64,
        authorization_reference="AUTHORIZED_STOCKNAMES_TEST",
    )

    assert rows == []
    assert summary["counts"]["ambiguous_active_identifiers"] == 1
    assert summary["unresolved"][0]["reason"] == "AMBIGUOUS_ACTIVE_IDENTIFIERS"


def test_duplicate_active_rows_with_same_ticker_do_not_create_duplicate_evidence():
    rows, summary = adapter.build_evidence(
        [queue_row()],
        [
            stockname(ticker="ABC", namedt="2010-01-01", nameenddt="2018-01-01"),
            stockname(ticker="ABC", namedt="2012-01-01", nameenddt="2020-01-01"),
        ],
        source_sha256="e" * 64,
        authorization_reference="AUTHORIZED_STOCKNAMES_TEST",
    )

    assert len(rows) == 1
    assert summary["counts"]["ambiguous_active_identifiers"] == 0


def test_nameendt_alias_and_open_end_are_supported():
    rows, summary = adapter.build_evidence(
        [queue_row()],
        [
            {
                "PERMNO": "12345.0",
                "TICKER": "ABC",
                "NAMEDT": "2010-01-01",
                "NAMEENDT": "",
            }
        ],
        source_sha256="f" * 64,
        authorization_reference="AUTHORIZED_STOCKNAMES_TEST",
    )

    assert len(rows) == 1
    assert summary["all_queue_requests_evidence_ready"] is True


def test_malformed_or_reversed_name_history_fails_closed():
    with pytest.raises(adapter.StocknamesIdentityAdapterError, match="NAMEDT"):
        adapter.normalize_stocknames(
            [stockname(namedt="not-a-date")]
        )

    with pytest.raises(adapter.StocknamesIdentityAdapterError, match="precedes"):
        adapter.normalize_stocknames(
            [stockname(namedt="2015-01-02", nameenddt="2015-01-01")]
        )


def test_authorization_reference_and_source_hash_are_required():
    with pytest.raises(adapter.StocknamesIdentityAdapterError, match="authorization_reference"):
        adapter.build_evidence(
            [queue_row()],
            [stockname()],
            source_sha256="a" * 64,
            authorization_reference="",
        )

    with pytest.raises(adapter.StocknamesIdentityAdapterError, match="source_sha256"):
        adapter.build_evidence(
            [queue_row()],
            [stockname()],
            source_sha256="not-a-sha",
            authorization_reference="AUTHORIZED_STOCKNAMES_TEST",
        )


def test_current_identity_queue_shape_is_locked():
    queue = adapter.read_csv(ROOT / adapter.DEFAULT_QUEUE)

    assert len(queue) == 3654
    assert len({row["permno"] for row in queue}) == 146
    assert all(row["status"] == "PENDING_STABLE_ID_EVIDENCE" for row in queue)
