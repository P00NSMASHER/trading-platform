from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import security_identity_gate as sig
import security_identity_lseg_bridge as bridge


def _events():
    return [
        {"event_id": "E1", "permno": "38659", "historical_symbol": "GNTX"},
        {"event_id": "E2", "permno": "75654", "historical_symbol": "CGNX"},
    ]


def _summary():
    return {
        "schema_version": "1",
        "trade_date": "2013-10-01",
        "input_receipt": {
            "path_name": "authorized-timesales-2013-10-01.csv.gz",
            "size_bytes": 12345,
            "sha256": "a" * 64,
        },
    }


def _valid_row():
    return {
        "trade_date": "2013-10-01",
        "historical_symbol": "GNTX",
        "candidate_rics": ["GNTX.O"],
        "selected_ric": "GNTX.O",
        "validation_status": "validated_single_candidate",
        "trade_lane_observed": True,
        "quote_lane_observed": False,
    }


def test_bridge_emits_exact_day_authorized_identity_evidence():
    ambiguous = {
        **_valid_row(),
        "historical_symbol": "CGNX",
        "candidate_rics": ["CGNX.O", "CGNX.OQ"],
        "selected_ric": "",
        "validation_status": "ambiguous_multiple_candidates_observed",
    }
    rows = bridge.build_identity_evidence(
        [ambiguous, _valid_row()],
        _summary(),
        _events(),
        authorization_reference="TEST_AUTHORIZATION",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["permno"] == "38659"
    assert row["historical_symbol"] == "GNTX"
    assert row["market_identifier"] == "GNTX.O"
    assert row["valid_from"] == "2013-10-01"
    assert row["valid_through"] == "2013-10-01"
    assert row["evidence_lane"] == "AUTHORIZED_MARKET_SECURITY_MASTER"
    assert row["authorization_reference"] == "TEST_AUTHORIZATION"
    assert row["source_reference"].endswith("#sha256=" + "a" * 64)
    assert row["evidence_id"].startswith("LSEG-SID-")


def test_bridge_rejects_validated_row_without_observed_trade_or_quote():
    row = _valid_row()
    row["trade_lane_observed"] = False
    row["quote_lane_observed"] = False
    with pytest.raises(bridge.LsegIdentityBridgeError, match="no observed trade/quote lane"):
        bridge.build_identity_evidence(
            [row], _summary(), _events(), authorization_reference="AUTH"
        )


def test_bridge_rejects_unknown_symbol_date_mismatch_and_non_candidate_selection():
    row = _valid_row()
    row["historical_symbol"] = "NOPE"
    with pytest.raises(bridge.LsegIdentityBridgeError, match="unknown historical_symbol"):
        bridge.build_identity_evidence(
            [row], _summary(), _events(), authorization_reference="AUTH"
        )

    row = _valid_row()
    row["trade_date"] = "2013-10-02"
    with pytest.raises(bridge.LsegIdentityBridgeError, match="does not match validator summary"):
        bridge.build_identity_evidence(
            [row], _summary(), _events(), authorization_reference="AUTH"
        )

    row = _valid_row()
    row["selected_ric"] = "GNTX.N"
    with pytest.raises(bridge.LsegIdentityBridgeError, match="not in candidate_rics"):
        bridge.build_identity_evidence(
            [row], _summary(), _events(), authorization_reference="AUTH"
        )


def test_bridge_requires_hash_backed_receipt_and_authorization_reference():
    bad = _summary()
    bad["input_receipt"]["sha256"] = "bad"
    with pytest.raises(bridge.LsegIdentityBridgeError, match="lowercase SHA-256"):
        bridge.build_identity_evidence(
            [_valid_row()], bad, _events(), authorization_reference="AUTH"
        )

    bad = _summary()
    bad["input_receipt"]["path_name"] = "../licensed.csv"
    with pytest.raises(bridge.LsegIdentityBridgeError, match="plain nonblank filename"):
        bridge.build_identity_evidence(
            [_valid_row()], bad, _events(), authorization_reference="AUTH"
        )

    with pytest.raises(bridge.LsegIdentityBridgeError, match="authorization_reference is required"):
        bridge.build_identity_evidence(
            [_valid_row()], _summary(), _events(), authorization_reference=""
        )


def test_bridge_rejects_conflicting_duplicate_permno_date():
    first = _valid_row()
    second = copy.deepcopy(first)
    second["candidate_rics"] = ["GNTX.N"]
    second["selected_ric"] = "GNTX.N"
    with pytest.raises(bridge.LsegIdentityBridgeError, match="conflicting validated evidence"):
        bridge.build_identity_evidence(
            [first, second], _summary(), _events(), authorization_reference="AUTH"
        )


def test_bridge_output_is_accepted_by_current_stable_identity_gate():
    events, requirements, listings = (
        sig._read_csv(ROOT / sig.DEFAULT_EVENTS),
        sig._read_csv(ROOT / sig.DEFAULT_REQUIREMENTS),
        sig._read_csv(ROOT / sig.DEFAULT_LISTING),
    )
    baseline = sig.build_manifest_from_rows(events, requirements, listings)
    target = next(row for row in baseline["events"] if row["unverified_required_dates"])
    trade_date = target["unverified_required_dates"][0]

    validation = [{
        "trade_date": trade_date,
        "historical_symbol": target["historical_symbol"],
        "candidate_rics": [target["historical_symbol"] + ".TEST"],
        "selected_ric": target["historical_symbol"] + ".TEST",
        "validation_status": "validated_single_candidate",
        "trade_lane_observed": True,
        "quote_lane_observed": False,
    }]
    summary = {
        "trade_date": trade_date,
        "input_receipt": {
            "path_name": "authorized-day.csv.gz",
            "size_bytes": 100,
            "sha256": "b" * 64,
        },
    }

    evidence = bridge.build_identity_evidence(
        validation,
        summary,
        events,
        authorization_reference="TEST_AUTHORIZATION",
    )
    promoted = sig.build_manifest_from_rows(
        events,
        requirements,
        listings,
        identity_evidence=evidence,
    )
    assert promoted["state"]["baseline_identity_verified_count"] == 1
    assert promoted["state"]["baseline_identity_unverified_count"] == 3653


def test_render_csv_matches_canonical_identity_evidence_schema():
    rows = bridge.build_identity_evidence(
        [_valid_row()],
        _summary(),
        _events(),
        authorization_reference="TEST_AUTHORIZATION",
    )
    rendered = bridge.render_csv(rows)
    assert rendered.splitlines()[0].split(",") == sig.IDENTITY_EVIDENCE_FIELDS
    assert rendered.count("\n") == 2
