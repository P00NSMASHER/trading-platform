from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import real_data_replay as replay


REQ_HEADER = (
    "historical_symbol,trade_date,roles,identity_status,canonical_g2_overlap,"
    "canonical_permno,canonical_gvkey,samplefirms_permno,samplefirms_gvkey,"
    "samplefirms_exact_mapping_status,required_evidence,research_use_only\n"
)
STAGED_HEADER = (
    "historical_symbol,trade_date,permno,market_identifier,evidence_ids,"
    "source_references,authorization_references,research_use_only\n"
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _identity_fixture(
    tmp_path: Path,
    *,
    include_g2_overlap: bool = True,
) -> dict[str, str]:
    requirements = tmp_path / "requirements.csv"
    requirements.write_text(
        REQ_HEADER
        + "AAA,2015-01-01,event_point,REUSE_CANONICAL_G2_VERIFIED_IDENTITY,"
        "CANONICAL_G2_VERIFIED,11111,1,,,NO_EXACT_DATE_MAPPING,,1\n"
        + "AAA,2015-01-02,prior_close,OVERLAPS_CANONICAL_G2_IDENTITY_QUEUE,"
        "CANONICAL_G2_UNVERIFIED,11111,1,,,NO_EXACT_DATE_MAPPING,"
        "DATED_STABLE_ID_CROSSWALK,1\n"
        + "BBB,2015-01-03,event_point,PUBLIC_EXACT_MAPPING_AVAILABLE_REQUIRES_ADMISSION,"
        "NONE,,,22222,2,UNIQUE_EXACT_DATE_MAPPING_AVAILABLE,"
        "ADMISSIBLE_DATE_SPECIFIC_STABLE_ID_EVIDENCE,1\n",
        encoding="utf-8",
    )

    verified = ["2015-01-01"]
    if include_g2_overlap:
        verified.append("2015-01-02")
    canonical = tmp_path / "canonical_g2_identity.json"
    canonical.write_text(
        json.dumps(
            {
                "events": [
                    {
                        "historical_symbol": "AAA",
                        "permno": "11111",
                        "verified_required_dates": verified,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    staged = tmp_path / "g5_staged.csv"
    staged.write_text(
        STAGED_HEADER
        + "BBB,2015-01-03,22222,BBB,E-G5,stocknames:test,AUTHORIZED-TEST,1\n",
        encoding="utf-8",
    )
    receipt = tmp_path / "g5_staging_receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "research_use_only": True,
                "canonical_g2_write_performed": False,
                "canonical_g5_write_performed": False,
                "counts": {"g5_only_staged_verified_count": 1},
                "output_sha256": {
                    "g5_only_staged_verified": _sha(staged),
                },
            }
        ),
        encoding="utf-8",
    )
    return {
        "identity_requirements": str(requirements),
        "canonical_g2_identity_manifest": str(canonical),
        "g5_only_staged_identity": str(staged),
        "g5_identity_staging_receipt": str(receipt),
    }


def _config(tmp_path: Path, identity_spec: dict[str, str] | None) -> Path:
    cfg = {
        "schema_version": "1",
        "events": str(ROOT / "data/processed/historical_events.csv"),
        "market_contract": str(
            ROOT / "config/historical_market_sources.example.json"
        ),
        "metadata_contract": str(
            ROOT / "config/metadata_sources.public_progress.json"
        ),
        "output_dir": str(tmp_path / "out"),
        "graph_db": str(
            ROOT
            / "data/processed/historical_graph_real/historical_cross_event_graph.sqlite"
        ),
    }
    if identity_spec is not None:
        cfg["g5_control_identity"] = identity_spec
    path = tmp_path / "replay.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return path


def test_replay_builds_ready_g5_control_identity_stage(tmp_path: Path):
    cfg = _config(tmp_path, _identity_fixture(tmp_path))
    result = replay.run_replay(cfg)

    stage = result["stages"]["g5_control_identity"]
    assert stage["status"] == "READY"
    assert stage["required_symbol_date_count"] == 3
    assert stage["verified_symbol_date_count"] == 3
    assert stage["unresolved_symbol_date_count"] == 0
    assert stage["canonical_g2_overlap_verified_count"] == 1
    assert stage["g5_only_verified_count"] == 1

    receipt = (
        tmp_path
        / "out"
        / "g5_control_identity"
        / "g5_control_identity_gate.json"
    )
    assert receipt.exists()
    inputs = result["inputs"]["g5_control_identity"]
    assert inputs is not None
    assert inputs["identity_requirements"]["sha256"] == _sha(
        Path(inputs["identity_requirements"]["path"])
    )
    assert inputs["g5_only_staged_identity"]["sha256"] == _sha(
        Path(inputs["g5_only_staged_identity"]["path"])
    )

    # The synthetic market contract still blocks release. A ready identity gate
    # is necessary but never sufficient for real evaluation.
    assert result["ready_for_non_synthetic_offline_evaluation"] is False
    assert result["evaluation_release_permitted"] is False


def test_unverified_g2_overlap_keeps_replay_identity_stage_blocked(
    tmp_path: Path,
):
    cfg = _config(
        tmp_path,
        _identity_fixture(tmp_path, include_g2_overlap=False),
    )
    result = replay.run_replay(cfg)

    stage = result["stages"]["g5_control_identity"]
    assert stage["status"] == "BLOCKED"
    assert stage["required_symbol_date_count"] == 3
    assert stage["verified_symbol_date_count"] == 2
    assert stage["unresolved_symbol_date_count"] == 1
    assert result["ready_for_non_synthetic_offline_evaluation"] is False


def test_missing_identity_config_is_explicit_dependency_blocker(
    tmp_path: Path,
):
    cfg = _config(tmp_path, None)
    result = replay.run_replay(cfg)

    assert result["stages"]["g5_control_identity"] == {
        "status": "DEPENDENCY_BLOCKED",
        "reason": "g5_control_identity_not_supplied",
    }
    assert result["inputs"]["g5_control_identity"] is None
    assert result["ready_for_non_synthetic_offline_evaluation"] is False


def test_identity_config_requires_existing_hash_bound_inputs(tmp_path: Path):
    spec = _identity_fixture(tmp_path)
    spec["g5_only_staged_identity"] = str(tmp_path / "missing.csv")
    cfg = _config(tmp_path, spec)

    with pytest.raises(FileNotFoundError, match="G5-only staged identity"):
        replay.run_replay(cfg)


def test_identity_config_must_be_an_object(tmp_path: Path):
    cfg = _config(tmp_path, None)
    raw = json.loads(cfg.read_text(encoding="utf-8"))
    raw["g5_control_identity"] = ["not", "an", "object"]
    cfg.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="g5_control_identity must be an object"):
        replay.run_replay(cfg)
