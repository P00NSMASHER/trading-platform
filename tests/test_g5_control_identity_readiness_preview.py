from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g5_control_identity_readiness_preview as preview


REQ_HEADER = (
    "historical_symbol,trade_date,roles,identity_status,canonical_g2_overlap,"
    "canonical_permno,canonical_gvkey,samplefirms_permno,samplefirms_gvkey,"
    "samplefirms_exact_mapping_status,required_evidence,research_use_only\n"
)

STAGED_HEADER = (
    "historical_symbol,trade_date,permno,market_identifier,evidence_ids,"
    "source_references,authorization_references,research_use_only\n"
)


def _requirements(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "requirements.csv"
    path.write_text(REQ_HEADER + body, encoding="utf-8")
    return path


def _staged(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "staged.csv"
    path.write_text(STAGED_HEADER + body, encoding="utf-8")
    return path


def test_preview_reconciles_canonical_reuse_staged_g5_and_unresolved_g2(
    tmp_path: Path,
):
    requirements = _requirements(
        tmp_path,
        "AAA,2015-01-01,event,REUSE_CANONICAL_G2_VERIFIED_IDENTITY,"
        "CANONICAL_G2_VERIFIED,11111,1,,,NO_EXACT_DATE_MAPPING,,1\n"
        "BBB,2015-01-02,history,OVERLAPS_CANONICAL_G2_IDENTITY_QUEUE,"
        "CANONICAL_G2_UNVERIFIED,22222,2,,,NO_EXACT_DATE_MAPPING,"
        "DATED_STABLE_ID_CROSSWALK,1\n"
        "CCC,2015-01-03,history,PUBLIC_EXACT_MAPPING_AVAILABLE_REQUIRES_ADMISSION,"
        "NONE,,,33333,3,UNIQUE_EXACT_DATE_MAPPING_AVAILABLE,"
        "ADMISSIBLE_DATE_SPECIFIC_STABLE_ID_EVIDENCE,1\n",
    )
    staged = _staged(
        tmp_path,
        "CCC,2015-01-03,33333,CCC,E1,source:1,AUTHORIZED-TEST,1\n",
    )

    summary = preview.build_preview(
        identity_requirements_path=requirements,
        staged_g5_only_path=staged,
        output_path=tmp_path / "preview.csv",
        summary_path=tmp_path / "summary.json",
    )

    assert summary["identity_requirement_count"] == 3
    assert summary["canonical_g2_verified_reuse_count"] == 1
    assert summary["staged_g5_only_verified_count"] == 1
    assert summary["preview_verified_count"] == 2
    assert summary["unresolved_canonical_g2_overlap_count"] == 1
    assert summary["unresolved_g5_only_count"] == 0
    assert summary["unresolved_identity_requirement_count"] == 1
    assert summary["preview_full_history_identity_complete"] is False
    assert summary["canonical_g5_readiness_changed"] is False
    assert summary["release_claimed"] is False

    rows = list(
        csv.DictReader((tmp_path / "preview.csv").open(encoding="utf-8"))
    )
    statuses = {
        (row["historical_symbol"], row["trade_date"]): row[
            "preview_identity_status"
        ]
        for row in rows
    }
    assert statuses[("AAA", "2015-01-01")] == "CANONICAL_G2_VERIFIED_REUSE"
    assert statuses[("BBB", "2015-01-02")] == "UNRESOLVED_CANONICAL_G2_OVERLAP"
    assert statuses[("CCC", "2015-01-03")] == "STAGED_G5_ONLY_AUTHORIZED_EVIDENCE"


def test_g2_overlap_cannot_be_closed_by_g5_staging(tmp_path: Path):
    requirements = _requirements(
        tmp_path,
        "BBB,2015-01-02,history,OVERLAPS_CANONICAL_G2_IDENTITY_QUEUE,"
        "CANONICAL_G2_UNVERIFIED,22222,2,,,NO_EXACT_DATE_MAPPING,"
        "DATED_STABLE_ID_CROSSWALK,1\n",
    )
    staged = _staged(
        tmp_path,
        "BBB,2015-01-02,22222,BBB,E2,source:2,AUTHORIZED-TEST,1\n",
    )

    with pytest.raises(
        preview.G5ControlIdentityReadinessPreviewError,
        match="must use the canonical G2 pipeline",
    ):
        preview.build_preview(
            identity_requirements_path=requirements,
            staged_g5_only_path=staged,
            output_path=tmp_path / "preview.csv",
            summary_path=tmp_path / "summary.json",
        )


def test_staged_permno_must_match_known_g5_hint(tmp_path: Path):
    requirements = _requirements(
        tmp_path,
        "CCC,2015-01-03,history,PUBLIC_EXACT_MAPPING_AVAILABLE_REQUIRES_ADMISSION,"
        "NONE,,,33333,3,UNIQUE_EXACT_DATE_MAPPING_AVAILABLE,"
        "ADMISSIBLE_DATE_SPECIFIC_STABLE_ID_EVIDENCE,1\n",
    )
    staged = _staged(
        tmp_path,
        "CCC,2015-01-03,99999,CCC,E3,source:3,AUTHORIZED-TEST,1\n",
    )

    with pytest.raises(
        preview.G5ControlIdentityReadinessPreviewError,
        match="conflicts with expected hint",
    ):
        preview.build_preview(
            identity_requirements_path=requirements,
            staged_g5_only_path=staged,
            output_path=tmp_path / "preview.csv",
            summary_path=tmp_path / "summary.json",
        )


def test_full_history_preview_can_complete_without_relaxing_canonical_state(
    tmp_path: Path,
):
    requirements = _requirements(
        tmp_path,
        "AAA,2015-01-01,event,REUSE_CANONICAL_G2_VERIFIED_IDENTITY,"
        "CANONICAL_G2_VERIFIED,11111,1,,,NO_EXACT_DATE_MAPPING,,1\n"
        "CCC,2015-01-03,history,NEW_G5_IDENTITY_EVIDENCE_REQUIRED,"
        "NONE,,,,,NO_EXACT_DATE_MAPPING,DATED_STABLE_ID_CROSSWALK,1\n",
    )
    staged = _staged(
        tmp_path,
        "CCC,2015-01-03,33333,CCC,E4,source:4,AUTHORIZED-TEST,1\n",
    )

    summary = preview.build_preview(
        identity_requirements_path=requirements,
        staged_g5_only_path=staged,
        output_path=tmp_path / "preview.csv",
        summary_path=tmp_path / "summary.json",
    )

    assert summary["preview_verified_count"] == 2
    assert summary["unresolved_identity_requirement_count"] == 0
    assert summary["preview_full_history_identity_complete"] is True
    assert summary["canonical_g2_write_performed"] is False
    assert summary["canonical_g5_write_performed"] is False
    assert summary["canonical_g5_readiness_changed"] is False
    assert summary["release_claimed"] is False
