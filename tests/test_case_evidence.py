from __future__ import annotations

import csv
import json
import sqlite3
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from case_evidence import (
    RESEARCH_NOTICE,
    add_review,
    export_case,
    ingest_case,
    init_db,
    verify_review_chain,
)

MODEL_DIR = ROOT / "data" / "processed" / "model_demo"
SCORES = MODEL_DIR / "holdout_scores.csv"
FEATURES = ROOT / "data" / "examples" / "model_training_feature_vectors.csv"
CONTROLS = ROOT / "data" / "examples" / "model_training_matched_controls.csv"
BUNDLE = MODEL_DIR / "model_bundle.joblib"
TRAINING_MANIFEST = MODEL_DIR / "training_manifest.json"


def _ingest(tmp_path: Path):
    db = tmp_path / "cases.sqlite"
    result = ingest_case(
        db_path=db,
        case_id="CASE-H001",
        sample_id="H001:TREATED",
        scores_csv=SCORES,
        feature_vectors=FEATURES,
        model_bundle=BUNDLE,
        matched_controls=CONTROLS,
        training_manifest=TRAINING_MANIFEST,
    )
    return db, result


def test_init_creates_immutable_schema(tmp_path: Path):
    db = tmp_path / "cases.sqlite"
    init_db(db)
    with sqlite3.connect(db) as con:
        names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"case_record", "case_timeline", "feature_snapshot", "control_snapshot", "source_artifact", "review_history"}.issubset(names)


def test_ingest_captures_case_features_controls_and_sources(tmp_path: Path):
    db, result = _ingest(tmp_path)
    assert result["feature_count"] > 10
    assert result["control_count"] == 3
    assert result["review_chain_valid"] is True
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM case_record").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM feature_snapshot").fetchone()[0] == result["feature_count"]
        assert con.execute("SELECT COUNT(*) FROM control_snapshot").fetchone()[0] == 3
        assert con.execute("SELECT COUNT(*) FROM source_artifact").fetchone()[0] >= 5


def test_duplicate_case_is_rejected(tmp_path: Path):
    db, _ = _ingest(tmp_path)
    with pytest.raises(ValueError):
        ingest_case(
            db_path=db,
            case_id="CASE-H001",
            sample_id="H001:TREATED",
            scores_csv=SCORES,
            feature_vectors=FEATURES,
            model_bundle=BUNDLE,
            matched_controls=CONTROLS,
            training_manifest=TRAINING_MANIFEST,
        )


def test_evidence_rows_cannot_be_updated_or_deleted(tmp_path: Path):
    db, _ = _ingest(tmp_path)
    with sqlite3.connect(db) as con:
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("UPDATE case_record SET symbol='ZZZ' WHERE case_id='CASE-H001'")
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("DELETE FROM feature_snapshot WHERE case_id='CASE-H001'")


def test_review_history_is_hash_chained_and_append_only(tmp_path: Path):
    db, _ = _ingest(tmp_path)
    add_review(
        db_path=db,
        case_id="CASE-H001",
        reviewer="owner",
        action="review_started",
        disposition="under_review",
        note="synthetic demo review",
        reviewed_at_utc="2026-09-24T08:30:00Z",
    )
    assert verify_review_chain(db, "CASE-H001") is True
    with sqlite3.connect(db) as con:
        rows = con.execute("SELECT previous_record_hash,record_hash FROM review_history WHERE case_id='CASE-H001' ORDER BY review_id").fetchall()
        assert len(rows) == 2
        assert rows[1][0] == rows[0][1]
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("UPDATE review_history SET note='changed' WHERE case_id='CASE-H001'")


def test_export_generates_integrity_manifest_and_zip(tmp_path: Path):
    db, _ = _ingest(tmp_path)
    out = export_case(db_path=db, case_id="CASE-H001", output_dir=tmp_path / "evidence")
    root = Path(out["bundle_dir"])
    integrity = json.loads((root / "integrity_manifest.json").read_text())
    assert len(integrity["bundle_root_sha256"]) == 64
    assert integrity["review_chain_valid"] is True
    assert Path(out["zip_path"]).exists()
    with zipfile.ZipFile(out["zip_path"]) as z:
        names = set(z.namelist())
        assert "CASE-H001/case_summary.json" in names
        assert "CASE-H001/provenance.json" in names


def test_export_does_not_include_ground_truth_or_trading_directives(tmp_path: Path):
    db, _ = _ingest(tmp_path)
    out = export_case(db_path=db, case_id="CASE-H001", output_dir=tmp_path / "evidence")
    root = Path(out["bundle_dir"])
    summary = (root / "case_summary.json").read_text().lower()
    timeline = (root / "timeline.csv").read_text().lower()
    assert '"label"' not in summary
    assert "ground_truth" not in summary
    for bad in ["expected_return", "target_price", "position_size", "order_instruction", "trade_direction"]:
        assert bad not in timeline
    assert RESEARCH_NOTICE.lower() in summary


def test_export_provenance_hashes_model_and_sources_without_embedding_raw_files(tmp_path: Path):
    db, _ = _ingest(tmp_path)
    out = export_case(db_path=db, case_id="CASE-H001", output_dir=tmp_path / "evidence")
    root = Path(out["bundle_dir"])
    provenance = json.loads((root / "provenance.json").read_text())
    assert len(provenance["model_sha256"]) == 64
    assert provenance["raw_sources_embedded"] is False
    assert all(len(s["sha256"]) == 64 for s in provenance["sources"])


def test_controls_include_risk_scores_when_available(tmp_path: Path):
    db, _ = _ingest(tmp_path)
    with sqlite3.connect(db) as con:
        rows = con.execute("SELECT control_symbol,control_risk_score FROM control_snapshot ORDER BY control_rank").fetchall()
    assert len(rows) == 3
    assert all(float(r[1]) >= 0 for r in rows)


def test_case_summary_uses_review_history_for_current_disposition(tmp_path: Path):
    db, _ = _ingest(tmp_path)
    add_review(
        db_path=db,
        case_id="CASE-H001",
        reviewer="owner",
        action="review_completed",
        disposition="closed_no_finding",
        note="synthetic demo only",
        reviewed_at_utc="2026-09-24T08:31:00Z",
    )
    out = export_case(db_path=db, case_id="CASE-H001", output_dir=tmp_path / "evidence")
    summary = json.loads((Path(out["bundle_dir"]) / "case_summary.json").read_text())
    assert summary["current_review_disposition"] == "closed_no_finding"
    assert summary["case"]["initial_status"] == "open_for_review"
