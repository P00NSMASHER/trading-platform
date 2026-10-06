from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import real_data_replay as replay


REQ_FIELDS = [
    "historical_symbol",
    "trade_date",
    "roles",
    "identity_status",
    "canonical_g2_overlap",
    "canonical_permno",
    "canonical_gvkey",
    "samplefirms_permno",
    "samplefirms_gvkey",
    "samplefirms_exact_mapping_status",
    "required_evidence",
    "research_use_only",
]
STAGED_FIELDS = [
    "historical_symbol",
    "trade_date",
    "permno",
    "market_identifier",
    "evidence_ids",
    "source_references",
    "authorization_references",
    "research_use_only",
]


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _identity_spec(tmp_path: Path) -> dict[str, str]:
    requirements = _write_csv(
        tmp_path / "identity_requirements.csv",
        REQ_FIELDS,
        [
            {
                "historical_symbol": "AAA",
                "trade_date": "2015-01-01",
                "roles": "event_point",
                "identity_status": "REUSE_CANONICAL_G2_VERIFIED_IDENTITY",
                "canonical_g2_overlap": "CANONICAL_G2_VERIFIED",
                "canonical_permno": "11111",
                "canonical_gvkey": "1",
                "samplefirms_permno": "",
                "samplefirms_gvkey": "",
                "samplefirms_exact_mapping_status": "NO_EXACT_DATE_MAPPING",
                "required_evidence": "",
                "research_use_only": "1",
            }
        ],
    )
    canonical = tmp_path / "canonical_g2_identity.json"
    canonical.write_text(
        json.dumps(
            {
                "events": [
                    {
                        "historical_symbol": "AAA",
                        "permno": "11111",
                        "verified_required_dates": ["2015-01-01"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    staged = _write_csv(tmp_path / "g5_only_staged.csv", STAGED_FIELDS, [])
    staged_sha = hashlib.sha256(staged.read_bytes()).hexdigest()
    receipt = tmp_path / "g5_identity_staging_receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "research_use_only": True,
                "canonical_g2_write_performed": False,
                "canonical_g5_write_performed": False,
                "counts": {"g5_only_staged_verified_count": 0},
                "output_sha256": {"g5_only_staged_verified": staged_sha},
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
        "market_contract": str(ROOT / "config/historical_market_sources.example.json"),
        "metadata_contract": str(ROOT / "config/metadata_sources.public_progress.json"),
        "output_dir": str(tmp_path / "out"),
    }
    if identity_spec is not None:
        cfg["g5_control_identity"] = identity_spec
    path = tmp_path / "replay.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return path


def test_replay_runs_and_hash_binds_g5_control_identity_gate(tmp_path: Path):
    spec = _identity_spec(tmp_path)
    result = replay.run_replay(_config(tmp_path, spec))

    stage = result["stages"]["g5_control_identity"]
    assert stage["status"] == "READY"
    assert stage["required_symbol_date_count"] == 1
    assert stage["verified_symbol_date_count"] == 1
    assert stage["unresolved_symbol_date_count"] == 0

    recorded = result["inputs"]["g5_control_identity"]
    for key, value in spec.items():
        path = Path(value)
        assert recorded[key]["path"] == str(path)
        assert recorded[key]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()

    assert result["ready_for_non_synthetic_offline_evaluation"] is False
    assert result["evaluation_release_permitted"] is False


def test_legacy_replay_without_g5_identity_preserves_receipt_shape(tmp_path: Path):
    result = replay.run_replay(_config(tmp_path, None))

    assert "g5_control_identity" not in result["stages"]
    assert "g5_control_identity" not in result["inputs"]
    assert result["ready_for_non_synthetic_offline_evaluation"] is False
    assert result["evaluation_release_permitted"] is False


def test_explicit_incomplete_g5_identity_config_fails_closed(tmp_path: Path):
    cfg = _config(tmp_path, {})
    with pytest.raises(FileNotFoundError, match="G5 identity requirements"):
        replay.run_replay(cfg)
