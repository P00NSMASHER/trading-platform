from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import security_identity_evidence_builder as builder


def queue():
    return [
        {
            "request_id": "SID-1",
            "permno": "10001",
            "gvkey": "123",
            "historical_symbol": "AAA",
            "trade_date": "2015-01-05",
            "event_ids": "EV1",
        },
        {
            "request_id": "SID-2",
            "permno": "10001",
            "gvkey": "123",
            "historical_symbol": "AAA",
            "trade_date": "2015-01-06",
            "event_ids": "EV1",
        },
        {
            "request_id": "SID-3",
            "permno": "20002",
            "gvkey": "456",
            "historical_symbol": "BBB",
            "trade_date": "2013-04-24",
            "event_ids": "EV2",
        },
    ]


def stocknames():
    return [
        {
            "permno": "10001",
            "ticker": "AAA",
            "namedt": "2010-01-01",
            "nameendt": "2015-12-31",
        },
        {
            "permno": "20002",
            "ticker": "BBB",
            "namedt": "2012-01-01",
            "nameendt": "",
        },
    ]


def test_builder_compresses_per_date_requests_to_source_intervals():
    evidence, summary = builder.build_evidence(
        queue(),
        stocknames(),
        source_reference="authorized://crsp/stocknames/extract.csv",
        authorization_reference="ENTITLEMENT-RECEIPT-1",
    )

    assert len(evidence) == 2
    assert summary["queue_request_count"] == 3
    assert summary["evidence_interval_count"] == 2
    assert summary["unique_permno_count"] == 2
    assert summary["ready_for_identity_gate_ingest"] is True
    assert {row["historical_symbol"] for row in evidence} == {"AAA", "BBB"}
    assert evidence[0]["evidence_id"].startswith("SID-EVID-")
    assert all(row["research_use_only"] == "1" for row in evidence)


def test_builder_fails_closed_when_any_request_is_not_datedly_covered():
    rows = stocknames()
    rows[0]["nameendt"] = "2015-01-05"
    with pytest.raises(builder.StableIdEvidenceError, match="does not close queue"):
        builder.build_evidence(
            queue(),
            rows,
            source_reference="authorized://crsp/stocknames/extract.csv",
            authorization_reference="ENTITLEMENT-RECEIPT-1",
        )


def test_builder_fails_closed_on_symbol_mismatch():
    rows = stocknames()
    rows[0]["ticker"] = "WRONG"
    with pytest.raises(builder.StableIdEvidenceError, match="does not close queue"):
        builder.build_evidence(
            queue(),
            rows,
            source_reference="authorized://crsp/stocknames/extract.csv",
            authorization_reference="ENTITLEMENT-RECEIPT-1",
        )


def test_builder_rejects_blank_authorization_and_nonclosing_lane():
    with pytest.raises(builder.StableIdEvidenceError, match="authorization_reference"):
        builder.build_evidence(
            queue(),
            stocknames(),
            source_reference="authorized://crsp/stocknames/extract.csv",
            authorization_reference="",
        )
    with pytest.raises(builder.StableIdEvidenceError, match="not closing-authorized"):
        builder.build_evidence(
            queue(),
            stocknames(),
            source_reference="authorized://crsp/stocknames/extract.csv",
            authorization_reference="ENTITLEMENT-RECEIPT-1",
            evidence_lane="PUBLIC_CORROBORATION",
        )


def test_builder_detects_conflicting_overlapping_history_rows():
    rows = stocknames() + [{
        "permno": "10001",
        "ticker": "AAA",
        "namedt": "2014-01-01",
        "nameendt": "2015-12-31",
    }]
    with pytest.raises(builder.StableIdEvidenceError, match="does not close queue"):
        builder.build_evidence(
            queue(),
            rows,
            source_reference="authorized://crsp/stocknames/extract.csv",
            authorization_reference="ENTITLEMENT-RECEIPT-1",
        )
