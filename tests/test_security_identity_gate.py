from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import security_identity_gate as sig


MANIFEST = ROOT / "data/processed/security_identity_real/security_identity_manifest.json"


def _current():
    return (
        sig._read_csv(ROOT / sig.DEFAULT_EVENTS),
        sig._read_csv(ROOT / sig.DEFAULT_REQUIREMENTS),
        sig._read_csv(ROOT / sig.DEFAULT_LISTING),
    )


def test_committed_security_identity_manifest_reproduces_byte_for_byte():
    assert sig.render_manifest(sig.build_manifest()) == MANIFEST.read_text(encoding="utf-8")


def test_current_universe_is_collision_free_but_baseline_identity_is_not_yet_proven():
    manifest = sig.build_manifest()
    state = manifest["state"]
    assert state["event_count"] == 174
    assert state["unique_permno_count"] == 146
    assert state["unique_historical_symbol_count"] == 146
    assert state["required_symbol_date_count"] == 3828
    assert state["event_date_identity_verified_count"] == 174
    assert state["baseline_identity_unverified_count"] == 3654
    assert state["symbol_to_multiple_permno_collision_count"] == 0
    assert state["permno_to_multiple_symbol_collision_count"] == 0
    assert state["ready_for_non_synthetic_market_join"] is False


def test_every_event_carries_permno_and_event_date_listing_evidence():
    manifest = sig.build_manifest()
    assert len(manifest["events"]) == 174
    for row in manifest["events"]:
        assert row["permno"]
        assert row["historical_symbol"]
        assert row["event_date"] in row["verified_required_dates"]
        assert row["primary_exchange"] in {"XNYS", "XNAS", "XASE"}
        assert row["event_date_listing_evidence"]["source_reference"]
        assert row["identity_status"] == "POINT_IN_TIME_SECURITY_MASTER_REQUIRED"


def test_symbol_reuse_across_multiple_permnos_fails_closed():
    events, requirements, listings = _current()
    bad = copy.deepcopy(events)
    bad[1]["historical_symbol"] = bad[0]["historical_symbol"]
    with pytest.raises(sig.SecurityIdentityError, match="multiple PERMNOs"):
        sig.build_manifest_from_rows(bad, requirements, listings)


def test_permno_alias_without_dated_evidence_fails_closed():
    events, requirements, listings = _current()
    bad = copy.deepcopy(events)
    bad[1]["permno"] = bad[0]["permno"]
    with pytest.raises(sig.SecurityIdentityError, match="multiple historical symbols"):
        sig.build_manifest_from_rows(bad, requirements, listings)


def test_requirement_symbol_mismatch_fails_closed():
    events, requirements, listings = _current()
    bad = copy.deepcopy(requirements)
    bad[0]["historical_symbol"] = "WRONG"
    with pytest.raises(sig.SecurityIdentityError, match="does not match event"):
        sig.build_manifest_from_rows(events, bad, listings)


def test_future_requirement_date_fails_closed():
    events, requirements, listings = _current()
    bad = copy.deepcopy(requirements)
    event_id = bad[0]["event_ids"]
    event = next(row for row in events if row["event_id"] == event_id)
    bad[0]["trade_date"] = "2099-01-01"
    with pytest.raises(sig.SecurityIdentityError, match="is after event date"):
        sig.build_manifest_from_rows(events, bad, listings)


def test_event_date_listing_symbol_mismatch_fails_closed():
    events, requirements, listings = _current()
    bad = copy.deepcopy(listings)
    bad[0]["historical_symbol"] = "WRONG"
    with pytest.raises(sig.SecurityIdentityError, match="historical_symbol mismatch"):
        sig.build_manifest_from_rows(events, requirements, bad)


def test_no_current_ticker_or_inferred_alias_shortcut_is_allowed():
    manifest = sig.build_manifest()
    prohibited = set(manifest["completion_contract"]["prohibited_shortcuts"])
    assert "current_ticker_substitution" in prohibited
    assert "inferred_corporate_action_alias" in prohibited
    assert "symbol_only_join_when_stable_identity_is_unproven" in prohibited

def _evidence_for(manifest: dict, event: dict, trade_date: str, **overrides) -> dict[str, str]:
    row = {
        "evidence_id": f"EVID-{event['permno']}-{trade_date}",
        "permno": event["permno"],
        "historical_symbol": event["historical_symbol"],
        "market_identifier": event["historical_symbol"],
        "valid_from": trade_date,
        "valid_through": trade_date,
        "evidence_lane": "LICENSED_STABLE_ID_MASTER",
        "source_reference": "authorized://stable-id-master/test-record",
        "authorization_reference": "TEST_AUTHORIZATION",
        "research_use_only": "1",
    }
    row.update(overrides)
    return row


def test_authorized_dated_identity_evidence_closes_only_covered_baseline_date():
    events, requirements, listings = _current()
    baseline = sig.build_manifest_from_rows(events, requirements, listings)
    event = next(row for row in baseline["events"] if row["unverified_required_dates"])
    trade_date = event["unverified_required_dates"][0]
    evidence = [_evidence_for(baseline, event, trade_date)]

    manifest = sig.build_manifest_from_rows(
        events,
        requirements,
        listings,
        identity_evidence=evidence,
    )
    resolved = next(row for row in manifest["events"] if row["event_id"] == event["event_id"])

    assert trade_date in resolved["verified_required_dates"]
    assert trade_date not in resolved["unverified_required_dates"]
    assert resolved["baseline_identity_evidence"][trade_date][0]["evidence_id"] == evidence[0]["evidence_id"]
    assert manifest["state"]["baseline_identity_verified_count"] == 1
    assert manifest["state"]["baseline_identity_unverified_count"] == 3653
    assert manifest["state"]["identity_evidence_row_count"] == 1
    assert manifest["state"]["ready_for_non_synthetic_market_join"] is False


def test_undated_or_unauthorized_identity_evidence_fails_closed():
    events, requirements, listings = _current()
    baseline = sig.build_manifest_from_rows(events, requirements, listings)
    event = next(row for row in baseline["events"] if row["unverified_required_dates"])
    trade_date = event["unverified_required_dates"][0]

    bad_undated = [_evidence_for(baseline, event, trade_date, valid_from="")]
    with pytest.raises(sig.SecurityIdentityError, match="missing required fields"):
        sig.build_manifest_from_rows(
            events,
            requirements,
            listings,
            identity_evidence=bad_undated,
        )

    bad_lane = [
        _evidence_for(
            baseline,
            event,
            trade_date,
            evidence_lane="PUBLIC_CORPORATE_ACTION_CORROBORATION",
        )
    ]
    with pytest.raises(sig.SecurityIdentityError, match="not closing-authorized"):
        sig.build_manifest_from_rows(
            events,
            requirements,
            listings,
            identity_evidence=bad_lane,
        )


def test_conflicting_dated_market_identifiers_fail_closed():
    events, requirements, listings = _current()
    baseline = sig.build_manifest_from_rows(events, requirements, listings)
    event = next(row for row in baseline["events"] if row["unverified_required_dates"])
    trade_date = event["unverified_required_dates"][0]
    evidence = [
        _evidence_for(
            baseline,
            event,
            trade_date,
            evidence_id="EVID-A",
            market_identifier="RIC.ONE",
        ),
        _evidence_for(
            baseline,
            event,
            trade_date,
            evidence_id="EVID-B",
            market_identifier="RIC.TWO",
            evidence_lane="AUTHORIZED_MARKET_SECURITY_MASTER",
        ),
    ]

    with pytest.raises(sig.SecurityIdentityError, match="conflicting market identifiers"):
        sig.build_manifest_from_rows(
            events,
            requirements,
            listings,
            identity_evidence=evidence,
        )


def test_default_manifest_remains_fail_closed_without_identity_evidence():
    manifest = sig.build_manifest()
    assert "identity_evidence" not in manifest["sources"]
    assert "baseline_identity_verified_count" not in manifest["state"]
    assert manifest["state"]["baseline_identity_unverified_count"] == 3654

