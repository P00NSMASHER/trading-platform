from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g5_control_identity_evidence_stager as stager


QUEUE_HEADER = (
    "historical_symbol,trade_date,identity_status,canonical_g2_overlap,"
    "canonical_permno,samplefirms_permno,research_use_only\n"
)

EVIDENCE_HEADER = (
    "evidence_id,permno,historical_symbol,market_identifier,valid_from,"
    "valid_through,evidence_lane,source_reference,authorization_reference,"
    "research_use_only\n"
)


def _queue(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "queue.csv"
    path.write_text(QUEUE_HEADER + body, encoding="utf-8")
    return path


def _evidence(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "evidence.csv"
    path.write_text(EVIDENCE_HEADER + body, encoding="utf-8")
    return path


def test_g5_only_evidence_stages_without_mutating_g2_overlap(tmp_path: Path):
    queue = _queue(
        tmp_path,
        "AAA,2015-01-02,OVERLAPS_CANONICAL_G2_IDENTITY_QUEUE,"
        "CANONICAL_G2_UNVERIFIED,12345,,1\n"
        "BBB,2015-01-03,PUBLIC_EXACT_MAPPING_AVAILABLE_REQUIRES_ADMISSION,"
        "NONE,,67890,1\n",
    )
    evidence = _evidence(
        tmp_path,
        "E1,12345,AAA,AAA,2015-01-02,2015-01-02,LICENSED_STABLE_ID_MASTER,"
        "stocknames-sha256:" + "a" * 64 + ",AUTHORIZED-TEST,1\n"
        "E2,67890,BBB,BBB,2015-01-03,2015-01-03,LICENSED_STABLE_ID_MASTER,"
        "stocknames-sha256:" + "a" * 64 + ",AUTHORIZED-TEST,1\n",
    )

    out = tmp_path / "out"
    receipt = stager.build(
        identity_queue_path=queue,
        evidence_path=evidence,
        output_dir=out,
    )

    assert receipt["counts"] == {
        "identity_queue_count": 2,
        "canonical_g2_overlap_requirement_count": 1,
        "g5_only_requirement_count": 1,
        "g5_only_staged_verified_count": 1,
        "g5_only_remaining_count": 0,
        "g2_forward_evidence_row_count": 1,
        "input_evidence_row_count": 2,
    }
    assert receipt["canonical_g2_write_performed"] is False
    assert receipt["canonical_g5_write_performed"] is False
    assert receipt["coverage_promoted"] is False
    assert receipt["overall_g5_identity_ready_claimed"] is False

    staged = list(
        csv.DictReader(
            (out / "g5_control_identity_staged_verified.csv").open(
                encoding="utf-8"
            )
        )
    )
    forwarded = list(
        csv.DictReader(
            (out / "g5_control_identity_g2_forward_evidence.csv").open(
                encoding="utf-8"
            )
        )
    )
    assert [(row["historical_symbol"], row["trade_date"]) for row in staged] == [
        ("BBB", "2015-01-03")
    ]
    assert [row["evidence_id"] for row in forwarded] == ["E1"]


def test_g5_only_authorized_evidence_can_establish_permno_without_prior_hint(
    tmp_path: Path,
):
    queue = _queue(
        tmp_path,
        "CCC,2015-01-05,NEW_G5_IDENTITY_EVIDENCE_REQUIRED,NONE,,,1\n",
    )
    evidence = _evidence(
        tmp_path,
        "E3,24680,CCC,CCC,2015-01-01,2015-01-10,"
        "AUTHORIZED_MARKET_SECURITY_MASTER,security-master:abc,AUTHORIZED-TEST,1\n",
    )

    out = tmp_path / "out"
    receipt = stager.build(
        identity_queue_path=queue,
        evidence_path=evidence,
        output_dir=out,
    )
    staged = list(
        csv.DictReader(
            (out / "g5_control_identity_staged_verified.csv").open(
                encoding="utf-8"
            )
        )
    )
    assert receipt["counts"]["g5_only_staged_verified_count"] == 1
    assert staged[0]["permno"] == "24680"
    assert staged[0]["market_identifier"] == "CCC"


def test_known_permno_hint_conflict_fails_closed(tmp_path: Path):
    queue = _queue(
        tmp_path,
        "BBB,2015-01-03,PUBLIC_EXACT_MAPPING_AVAILABLE_REQUIRES_ADMISSION,"
        "NONE,,67890,1\n",
    )
    evidence = _evidence(
        tmp_path,
        "E4,99999,BBB,BBB,2015-01-03,2015-01-03,LICENSED_STABLE_ID_MASTER,"
        "stocknames-sha256:" + "b" * 64 + ",AUTHORIZED-TEST,1\n",
    )

    with pytest.raises(
        stager.G5ControlIdentityEvidenceStagingError,
        match="conflicts with expected hint",
    ):
        stager.build(
            identity_queue_path=queue,
            evidence_path=evidence,
            output_dir=tmp_path / "out",
        )


def test_evidence_outside_g5_queue_fails_closed(tmp_path: Path):
    queue = _queue(
        tmp_path,
        "BBB,2015-01-03,NEW_G5_IDENTITY_EVIDENCE_REQUIRED,NONE,,,1\n",
    )
    evidence = _evidence(
        tmp_path,
        "E5,67890,ZZZ,ZZZ,2015-01-03,2015-01-03,LICENSED_STABLE_ID_MASTER,"
        "stocknames-sha256:" + "c" * 64 + ",AUTHORIZED-TEST,1\n",
    )

    with pytest.raises(
        stager.G5ControlIdentityEvidenceStagingError,
        match="does not match any unresolved G5 identity requirement",
    ):
        stager.build(
            identity_queue_path=queue,
            evidence_path=evidence,
            output_dir=tmp_path / "out",
        )


def test_conflicting_authorized_permnos_for_same_g5_requirement_fail_closed(
    tmp_path: Path,
):
    queue = _queue(
        tmp_path,
        "DDD,2015-01-07,NEW_G5_IDENTITY_EVIDENCE_REQUIRED,NONE,,,1\n",
    )
    evidence = _evidence(
        tmp_path,
        "E6,11111,DDD,DDD,2015-01-07,2015-01-07,LICENSED_STABLE_ID_MASTER,"
        "security-master:one,AUTHORIZED-TEST,1\n"
        "E7,22222,DDD,DDD,2015-01-07,2015-01-07,AUTHORIZED_MARKET_SECURITY_MASTER,"
        "security-master:two,AUTHORIZED-TEST,1\n",
    )

    with pytest.raises(
        stager.G5ControlIdentityEvidenceStagingError,
        match="conflicting authorized PERMNO evidence",
    ):
        stager.build(
            identity_queue_path=queue,
            evidence_path=evidence,
            output_dir=tmp_path / "out",
        )


def test_interval_evidence_may_close_multiple_g5_only_required_dates(tmp_path: Path):
    queue = _queue(
        tmp_path,
        "EEE,2015-01-05,NEW_G5_IDENTITY_EVIDENCE_REQUIRED,NONE,,,1\n"
        "EEE,2015-01-06,NEW_G5_IDENTITY_EVIDENCE_REQUIRED,NONE,,,1\n",
    )
    evidence = _evidence(
        tmp_path,
        "E8,33333,EEE,EEE,2015-01-01,2015-01-31,LICENSED_STABLE_ID_MASTER,"
        "security-master:eee,AUTHORIZED-TEST,1\n",
    )

    out = tmp_path / "out"
    receipt = stager.build(
        identity_queue_path=queue,
        evidence_path=evidence,
        output_dir=out,
    )
    assert receipt["counts"]["g5_only_staged_verified_count"] == 2
    assert receipt["counts"]["g5_only_remaining_count"] == 0
    assert receipt["g5_only_identity_staging_complete"] is True
