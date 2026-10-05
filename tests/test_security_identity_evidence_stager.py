from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import security_identity_evidence_stager as stager
import security_identity_gate as gate


def _current():
    return (
        gate._read_csv(ROOT / gate.DEFAULT_EVENTS),
        gate._read_csv(ROOT / gate.DEFAULT_REQUIREMENTS),
        gate._read_csv(ROOT / gate.DEFAULT_LISTING),
    )


def _evidence(
    *,
    evidence_id: str,
    permno: str,
    symbol: str,
    trade_date: str,
) -> dict[str, str]:
    return {
        "evidence_id": evidence_id,
        "permno": permno,
        "historical_symbol": symbol,
        "market_identifier": symbol,
        "valid_from": trade_date,
        "valid_through": trade_date,
        "evidence_lane": "LICENSED_STABLE_ID_MASTER",
        "source_reference": "authorized://stable-id-master/test",
        "authorization_reference": "TEST_AUTHORIZATION",
        "research_use_only": "1",
    }


def test_one_evidence_row_stages_exactly_one_baseline_identity():
    events, requirements, listings = _current()
    baseline = gate.build_manifest_from_rows(events, requirements, listings)
    event = next(row for row in baseline["events"] if row["unverified_required_dates"])
    trade_date = event["unverified_required_dates"][0]
    evidence = [
        _evidence(
            evidence_id="ONE",
            permno=event["permno"],
            symbol=event["historical_symbol"],
            trade_date=trade_date,
        )
    ]

    result = stager.build_staging_from_rows(
        events=events,
        requirements=requirements,
        listings=listings,
        evidence_rows=evidence,
    )
    state = result["receipt"]["candidate_state"]

    assert state["event_date_identity_verified_count"] == 174
    assert state["baseline_identity_verified_count"] == 1
    assert state["total_identity_verified_count"] == 175
    assert state["baseline_identity_unverified_count"] == 3653
    assert state["required_symbol_date_count"] == 3828
    assert state["ready_for_non_synthetic_market_join"] is False
    assert result["receipt"]["remaining_acquisition_queue_count"] == 3653
    assert result["receipt"]["canonical_write_performed"] is False
    assert result["receipt"]["coverage_promoted"] is False


def test_full_synthetic_evidence_proves_terminal_empty_queue_contract():
    events, requirements, listings = _current()
    baseline = gate.build_manifest_from_rows(events, requirements, listings)
    evidence = []
    for event in baseline["events"]:
        for trade_date in event["unverified_required_dates"]:
            evidence.append(
                _evidence(
                    evidence_id=f"E-{event['permno']}-{trade_date}",
                    permno=event["permno"],
                    symbol=event["historical_symbol"],
                    trade_date=trade_date,
                )
            )

    assert len(evidence) == 3654
    result = stager.build_staging_from_rows(
        events=events,
        requirements=requirements,
        listings=listings,
        evidence_rows=evidence,
    )
    state = result["receipt"]["candidate_state"]

    assert state["event_date_identity_verified_count"] == 174
    assert state["baseline_identity_verified_count"] == 3654
    assert state["total_identity_verified_count"] == 3828
    assert state["baseline_identity_unverified_count"] == 0
    assert state["ready_for_non_synthetic_market_join"] is True
    assert result["queue"] == []
    assert result["receipt"]["remaining_acquisition_queue_count"] == 0
    assert result["summary"]["state"]["ready_for_non_synthetic_market_join"] is True


def test_duplicate_evidence_ids_fail_closed():
    events, requirements, listings = _current()
    baseline = gate.build_manifest_from_rows(events, requirements, listings)
    event = next(row for row in baseline["events"] if len(row["unverified_required_dates"]) >= 2)
    first, second = event["unverified_required_dates"][:2]
    evidence = [
        _evidence(
            evidence_id="DUPLICATE",
            permno=event["permno"],
            symbol=event["historical_symbol"],
            trade_date=first,
        ),
        _evidence(
            evidence_id="DUPLICATE",
            permno=event["permno"],
            symbol=event["historical_symbol"],
            trade_date=second,
        ),
    ]

    with pytest.raises(gate.SecurityIdentityError, match="unique and nonblank"):
        stager.build_staging_from_rows(
            events=events,
            requirements=requirements,
            listings=listings,
            evidence_rows=evidence,
        )


def test_conflicting_identifiers_for_same_date_fail_closed():
    events, requirements, listings = _current()
    baseline = gate.build_manifest_from_rows(events, requirements, listings)
    event = next(row for row in baseline["events"] if row["unverified_required_dates"])
    trade_date = event["unverified_required_dates"][0]
    first = _evidence(
        evidence_id="ONE",
        permno=event["permno"],
        symbol=event["historical_symbol"],
        trade_date=trade_date,
    )
    second = copy.deepcopy(first)
    second["evidence_id"] = "TWO"
    second["market_identifier"] = event["historical_symbol"] + ".ALT"

    with pytest.raises(gate.SecurityIdentityError, match="conflicting market identifiers"):
        stager.build_staging_from_rows(
            events=events,
            requirements=requirements,
            listings=listings,
            evidence_rows=[first, second],
        )


def test_staging_writer_refuses_canonical_identity_directory(tmp_path: Path):
    events, requirements, listings = _current()
    baseline = gate.build_manifest_from_rows(events, requirements, listings)
    event = next(row for row in baseline["events"] if row["unverified_required_dates"])
    trade_date = event["unverified_required_dates"][0]
    result = stager.build_staging_from_rows(
        events=events,
        requirements=requirements,
        listings=listings,
        evidence_rows=[
            _evidence(
                evidence_id="ONE",
                permno=event["permno"],
                symbol=event["historical_symbol"],
                trade_date=trade_date,
            )
        ],
    )

    with pytest.raises(stager.SecurityIdentityStagingError, match="may not equal"):
        stager.write_staging(result, gate.DEFAULT_OUTPUT.parent)


def test_staging_writer_creates_only_candidate_outputs(tmp_path: Path):
    events, requirements, listings = _current()
    baseline = gate.build_manifest_from_rows(events, requirements, listings)
    event = next(row for row in baseline["events"] if row["unverified_required_dates"])
    trade_date = event["unverified_required_dates"][0]
    result = stager.build_staging_from_rows(
        events=events,
        requirements=requirements,
        listings=listings,
        evidence_rows=[
            _evidence(
                evidence_id="ONE",
                permno=event["permno"],
                symbol=event["historical_symbol"],
                trade_date=trade_date,
            )
        ],
    )

    outputs = stager.write_staging(result, tmp_path / "stage")

    assert set(outputs) == {
        "candidate_manifest",
        "remaining_queue",
        "remaining_summary",
        "receipt",
    }
    assert all(Path(path).exists() for path in outputs.values())
    receipt = Path(outputs["receipt"]).read_text(encoding="utf-8")
    assert '"canonical_write_performed": false' in receipt

def _write_evidence_csv(path: Path, rows: list[dict[str, str]]) -> None:
    import csv
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=gate.IDENTITY_EVIDENCE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def test_build_staging_carries_forward_previously_promoted_evidence(tmp_path: Path):
    events, requirements, listings = _current()
    baseline = gate.build_manifest_from_rows(events, requirements, listings)
    event = next(row for row in baseline["events"] if len(row["unverified_required_dates"]) >= 2)
    first_date, second_date = event["unverified_required_dates"][:2]
    current = gate.build_manifest_from_rows(
        events,
        requirements,
        listings,
        identity_evidence=[
            _evidence(
                evidence_id="PRIOR",
                permno=event["permno"],
                symbol=event["historical_symbol"],
                trade_date=first_date,
            )
        ],
    )
    current_path = tmp_path / "current.json"
    current_path.write_text(gate.render_manifest(current), encoding="utf-8")

    new_path = tmp_path / "new.csv"
    _write_evidence_csv(
        new_path,
        [
            _evidence(
                evidence_id="NEW",
                permno=event["permno"],
                symbol=event["historical_symbol"],
                trade_date=second_date,
            )
        ],
    )

    result = stager.build_staging(
        evidence_paths=[new_path],
        events_path=ROOT / gate.DEFAULT_EVENTS,
        requirements_path=ROOT / gate.DEFAULT_REQUIREMENTS,
        listing_path=ROOT / gate.DEFAULT_LISTING,
        current_manifest_path=current_path,
    )
    state = result["receipt"]["candidate_state"]

    assert state["baseline_identity_verified_count"] == 2
    assert state["baseline_identity_unverified_count"] == 3652
    assert result["receipt"]["prior_canonical_evidence_row_count"] == 1
    assert result["receipt"]["new_evidence_row_count"] == 1
    assert result["receipt"]["evidence_row_count"] == 2
    assert result["receipt"]["evidence_inputs"][0]["role"] == "prior_canonical_identity_manifest"


def test_cumulative_staging_rejects_conflicting_reused_evidence_id(tmp_path: Path):
    events, requirements, listings = _current()
    baseline = gate.build_manifest_from_rows(events, requirements, listings)
    event = next(row for row in baseline["events"] if len(row["unverified_required_dates"]) >= 2)
    first_date, second_date = event["unverified_required_dates"][:2]
    current = gate.build_manifest_from_rows(
        events,
        requirements,
        listings,
        identity_evidence=[
            _evidence(
                evidence_id="SAME",
                permno=event["permno"],
                symbol=event["historical_symbol"],
                trade_date=first_date,
            )
        ],
    )
    current_path = tmp_path / "current.json"
    current_path.write_text(gate.render_manifest(current), encoding="utf-8")
    new_path = tmp_path / "new.csv"
    _write_evidence_csv(
        new_path,
        [
            _evidence(
                evidence_id="SAME",
                permno=event["permno"],
                symbol=event["historical_symbol"],
                trade_date=second_date,
            )
        ],
    )

    with pytest.raises(stager.SecurityIdentityStagingError, match="conflicts"):
        stager.build_staging(
            evidence_paths=[new_path],
            events_path=ROOT / gate.DEFAULT_EVENTS,
            requirements_path=ROOT / gate.DEFAULT_REQUIREMENTS,
            listing_path=ROOT / gate.DEFAULT_LISTING,
            current_manifest_path=current_path,
        )


def test_cumulative_staging_requires_embedded_evidence_for_promoted_state(tmp_path: Path):
    current = json.loads((ROOT / gate.DEFAULT_OUTPUT).read_text(encoding="utf-8"))
    current["state"]["baseline_identity_verified_count"] = 1
    current["state"]["baseline_identity_unverified_count"] = 3653
    current_path = tmp_path / "bad-current.json"
    current_path.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    event = current["events"][0]
    new_path = tmp_path / "new.csv"
    _write_evidence_csv(
        new_path,
        [
            _evidence(
                evidence_id="NEW",
                permno=event["permno"],
                symbol=event["historical_symbol"],
                trade_date=event["unverified_required_dates"][0],
            )
        ],
    )

    with pytest.raises(stager.SecurityIdentityStagingError, match="without embedded evidence"):
        stager.build_staging(
            evidence_paths=[new_path],
            events_path=ROOT / gate.DEFAULT_EVENTS,
            requirements_path=ROOT / gate.DEFAULT_REQUIREMENTS,
            listing_path=ROOT / gate.DEFAULT_LISTING,
            current_manifest_path=current_path,
        )

