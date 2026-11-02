from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import security_identity_lseg_bridge as bridge


def queue_row(*, request_id="SID-ONE", permno="12345", symbol="ABC", date="2015-02-12"):
    return {
        "request_id": request_id,
        "permno": permno,
        "gvkey": "001234",
        "historical_symbol": symbol,
        "trade_date": date,
        "event_ids": "HEJFE-AAAAAAAAAAAAAAAA",
        "status": "PENDING_STABLE_ID_EVIDENCE",
        "required_evidence": "DATED_STABLE_ID_CROSSWALK",
        "primary_lane": "LICENSED_STABLE_ID_MASTER",
        "secondary_lane": "AUTHORIZED_MARKET_SECURITY_MASTER",
        "corroboration_lane": "PUBLIC_CORPORATE_ACTION_CORROBORATION",
        "research_use_only": "1",
    }


def mapping_row(*, permno="12345.0", symbol="ABC", rics="ABC.O", status="study_permno_linked_candidate"):
    return {
        "PERMNO": permno,
        "SYMBOL": symbol,
        "GVKEY": "001234",
        "TimeOfFirstTrade": "2015-02-12 09:00:00",
        "candidate_rics": rics,
        "mapping_status": status,
        "source_event_file": "TimeOfFirstTrade.csv",
        "source_ric_file": "PERMNO_TRHT _Ticker.csv",
    }


def validation_row(*, symbol="ABC", ric="ABC.O", date="2015-02-12", status="validated_single_candidate"):
    return {
        "trade_date": date,
        "historical_symbol": symbol,
        "mapping_class": "event_permno_linked_candidate",
        "historical_validation_required": "true",
        "candidate_rics": ric,
        "observed_candidate_rics": ric,
        "selected_ric": ric,
        "validation_status": status,
        "selected_trade_rows": "1",
        "selected_quote_rows": "1",
        "selected_other_rows": "0",
        "trade_lane_observed": "true",
        "quote_lane_observed": "true",
    }


def test_date_specific_direct_permno_ric_validation_emits_closing_evidence():
    rows, summary = bridge.build_evidence(
        [validation_row()],
        [queue_row()],
        [mapping_row()],
        source_sha256="a" * 64,
        authorization_reference="LSEG_ENTITLEMENT_TEST",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["permno"] == "12345"
    assert row["historical_symbol"] == "ABC"
    assert row["market_identifier"] == "ABC.O"
    assert row["valid_from"] == "2015-02-12"
    assert row["valid_through"] == "2015-02-12"
    assert row["evidence_lane"] == "AUTHORIZED_MARKET_SECURITY_MASTER"
    assert row["source_reference"] == "lseg-tick-history-sha256:" + "a" * 64
    assert summary["counts"]["evidence_rows_emitted"] == 1
    assert summary["policy"]["coverage_change"] is False


def test_secondary_or_root_only_candidate_cannot_close_identity():
    rows, summary = bridge.build_evidence(
        [validation_row()],
        [queue_row()],
        [mapping_row(status="secondary_repository_candidate")],
        source_sha256="b" * 64,
        authorization_reference="LSEG_ENTITLEMENT_TEST",
    )

    assert rows == []
    assert summary["counts"]["not_direct_permno_bridged"] == 1
    assert summary["policy"]["secondary_or_root_only_candidates_can_close"] is False


def test_ambiguous_or_unvalidated_ric_never_emits_evidence():
    rows, summary = bridge.build_evidence(
        [validation_row(status="ambiguous_multiple_candidates_observed")],
        [queue_row()],
        [mapping_row()],
        source_sha256="c" * 64,
        authorization_reference="LSEG_ENTITLEMENT_TEST",
    )

    assert rows == []
    assert summary["counts"]["nonclosing_validation_status"] == 1


def test_direct_mapping_conflict_fails_closed():
    with pytest.raises(bridge.LsegIdentityBridgeError, match="multiple PERMNOs"):
        bridge.build_direct_bridge_index(
            [
                mapping_row(permno="12345.0"),
                mapping_row(permno="54321.0"),
            ]
        )


def test_authorization_reference_is_required():
    with pytest.raises(bridge.LsegIdentityBridgeError, match="authorization_reference"):
        bridge.build_evidence(
            [validation_row()],
            [queue_row()],
            [mapping_row()],
            source_sha256="d" * 64,
            authorization_reference="",
        )


def test_validated_direct_mapping_not_in_queue_does_not_create_new_request():
    rows, summary = bridge.build_evidence(
        [validation_row(date="2015-02-13")],
        [queue_row(date="2015-02-12")],
        [mapping_row()],
        source_sha256="e" * 64,
        authorization_reference="LSEG_ENTITLEMENT_TEST",
    )

    assert rows == []
    assert summary["counts"]["not_in_identity_queue"] == 1

def test_current_repository_direct_bridge_capacity_is_locked():
    mapping = bridge.read_csv(ROOT / bridge.DEFAULT_EVENT_MAPPING)
    queue = bridge.read_csv(ROOT / bridge.DEFAULT_QUEUE)
    index = bridge.build_direct_bridge_index(mapping)

    direct_permnos = set(index.values())
    eligible_requests = sum(
        row["permno"] in direct_permnos
        for row in queue
    )

    assert len(direct_permnos) == 111
    assert eligible_requests == 2751
    assert len(queue) == 3654

