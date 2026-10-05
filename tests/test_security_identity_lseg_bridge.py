from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import security_identity_lseg_bridge as bridge


def _events():
    return [
        {
            "event_id": "E1",
            "permno": "38659",
            "historical_symbol": "GNTX",
        },
        {
            "event_id": "E2",
            "permno": "75654",
            "historical_symbol": "CGNX",
        },
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
        "selected_ric": "GNTX.O",
        "validation_status": "validated_single_candidate",
        "trade_lane_observed": "True",
        "quote_lane_observed": "False",
    }


def test_bridge_emits_only_validated_single_candidate_rows():
    valid = _valid_row()
    ambiguous = {
        **valid,
        "historical_symbol": "CGNX",
        "selected_ric": "",
        "validation_status": "ambiguous_multiple_candidates_observed",
    }
    rows = bridge.build_dated_evidence([ambiguous, valid], _summary(), _events())

    assert rows == [
        {
            "permno": "38659",
            "historical_symbol": "GNTX",
            "trade_date": "2013-10-01",
            "market_identifier": "GNTX.O",
            "source_family": "authorized_historical_lseg_timesales",
            "source_reference": "lseg-timesales-receipt:authorized-timesales-2013-10-01.csv.gz",
            "source_sha256": "a" * 64,
            "validation_status": "VALIDATED_DATE_SPECIFIC_STABLE_ID",
            "research_use_only": "1",
        }
    ]


def test_bridge_rejects_validated_row_without_trade_or_quote_observation():
    row = _valid_row()
    row["trade_lane_observed"] = "False"
    row["quote_lane_observed"] = "False"

    with pytest.raises(bridge.SecurityIdentityBridgeError, match="no observed trade/quote lane"):
        bridge.build_dated_evidence([row], _summary(), _events())


def test_bridge_rejects_unknown_symbol_and_date_mismatch():
    row = _valid_row()
    row["historical_symbol"] = "NOPE"
    with pytest.raises(bridge.SecurityIdentityBridgeError, match="unknown historical_symbol"):
        bridge.build_dated_evidence([row], _summary(), _events())

    row = _valid_row()
    row["trade_date"] = "2013-10-02"
    with pytest.raises(bridge.SecurityIdentityBridgeError, match="does not match validator summary"):
        bridge.build_dated_evidence([row], _summary(), _events())


def test_bridge_requires_hash_backed_plain_filename_receipt():
    bad = _summary()
    bad["input_receipt"]["sha256"] = "bad"
    with pytest.raises(bridge.SecurityIdentityBridgeError, match="lowercase SHA-256"):
        bridge.build_dated_evidence([_valid_row()], bad, _events())

    bad = _summary()
    bad["input_receipt"]["path_name"] = "../licensed.csv"
    with pytest.raises(bridge.SecurityIdentityBridgeError, match="plain nonblank filename"):
        bridge.build_dated_evidence([_valid_row()], bad, _events())


def test_bridge_rejects_conflicting_duplicate_permno_date():
    first = _valid_row()
    second = copy.deepcopy(first)
    second["selected_ric"] = "GNTX.N"

    with pytest.raises(bridge.SecurityIdentityBridgeError, match="conflicting validated evidence"):
        bridge.build_dated_evidence([first, second], _summary(), _events())


def test_render_csv_is_deterministic():
    rows = bridge.build_dated_evidence([_valid_row()], _summary(), _events())
    rendered = bridge.render_csv(rows)
    assert rendered.startswith(
        "permno,historical_symbol,trade_date,market_identifier,source_family,"
    )
    assert rendered.count("\n") == 2
    assert "38659,GNTX,2013-10-01,GNTX.O" in rendered
