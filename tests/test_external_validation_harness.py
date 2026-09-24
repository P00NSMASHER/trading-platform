from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

import joblib
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from external_validation_harness import (
    evaluate_external,
    load_frozen_bundle,
    load_registry,
    score_external,
    validate_registry_schema,
)
from model_training_harness import DEFAULT_FEATURES, train


def _write(path: Path, fields: list[str], rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _feature_row(symbol: str, ts: str, *, positive: bool):
    row = {
        "minute_ts_utc": ts,
        "symbol": symbol,
        "feature_status": "full",
        "research_use_only": "1",
    }
    for j, name in enumerate(DEFAULT_FEATURES):
        if "count" in name:
            val = 2.5 if positive else 0.1
        elif name.startswith("return_"):
            val = 0.001 if positive else 0.0
        elif name.startswith("realized_vol_"):
            val = 0.012
        elif "volume" in name or "turnover" in name or "spread" in name or "multivariate" in name:
            val = 2.4 + (j % 3) * 0.05 if positive else 0.15 + (j % 2) * 0.02
        else:
            val = 0.65 if positive else 0.05
        row[name] = str(val)
    return row


def _make_training_fixture(tmp_path: Path):
    matches = []
    features = []
    event_no = 0
    dev_issuers = [f"T{i:02d}" for i in range(12)]
    for year in [2011, 2012, 2013, 2014]:
        for k in range(6):
            issuer = dev_issuers[(event_no // 2) % len(dev_issuers)]
            event_no += 1
            ts = f"{year}-02-{5+k:02d}T19:{30+k:02d}:00.000Z"
            event_id = f"D{event_no:03d}"
            features.append(_feature_row(issuer, ts, positive=True))
            for rank in range(1, 4):
                c = f"C{event_no:03d}{rank}"
                features.append(_feature_row(c, ts, positive=False))
                matches.append({
                    "match_id": f"M{event_no:03d}{rank}",
                    "event_id": event_id,
                    "treated_symbol": issuer,
                    "treated_minute_ts_utc": ts,
                    "control_rank": str(rank),
                    "control_symbol": c,
                    "control_minute_ts_utc": ts,
                })
    for k in range(8):
        issuer = dev_issuers[k % 4] if k < 4 else f"H{k:02d}"
        ts = f"2015-03-{10+k:02d}T19:{35+k:02d}:00.000Z"
        event_id = f"H{k:03d}"
        features.append(_feature_row(issuer, ts, positive=True))
        for rank in range(1, 4):
            c = f"HC{k:03d}{rank}"
            features.append(_feature_row(c, ts, positive=False))
            matches.append({
                "match_id": f"HM{k:03d}{rank}",
                "event_id": event_id,
                "treated_symbol": issuer,
                "treated_minute_ts_utc": ts,
                "control_rank": str(rank),
                "control_symbol": c,
                "control_minute_ts_utc": ts,
            })
    mp = tmp_path / "matched.csv"
    fp = tmp_path / "train_features.csv"
    _write(mp, list(matches[0].keys()), matches)
    fields = ["minute_ts_utc", "symbol", "feature_status"] + list(DEFAULT_FEATURES) + ["research_use_only"]
    _write(fp, fields, features)
    out = tmp_path / "trained"
    train(matched_controls=mp, feature_vectors=fp, output_dir=out, target_fpr=0.10, cv_folds=4)
    return out / "model_bundle.joblib"


def _external_fixture(tmp_path: Path):
    registry = []
    truth = []
    features = []
    families = [
        ("edgar_hack", "stolen_filing"),
        ("fda_regulatory", "regulatory_decision"),
        ("cross_security", "peer_security"),
    ]
    n = 0
    for family, mechanism in families:
        for case_num in range(2):
            case_id = f"{family.upper()}_{case_num+1}"
            ts = f"2018-06-{10+n:02d}T18:3{case_num}:00.000Z"
            treated = f"X{n:02d}T"
            sid = f"{case_id}:T"
            registry.append({
                "sample_id": sid, "case_id": case_id, "case_family": family,
                "mechanism": mechanism, "symbol": treated, "minute_ts_utc": ts,
                "adjudication_status": "synthetic", "source_reference": "synthetic_fixture",
                "research_use_only": "1",
            })
            truth.append({"sample_id": sid, "label": "1", "truth_role": "adjudicated_treated"})
            features.append(_feature_row(treated, ts, positive=True))
            for cnum in range(3):
                c = f"X{n:02d}C{cnum}"
                csid = f"{case_id}:C{cnum}"
                registry.append({
                    "sample_id": csid, "case_id": case_id, "case_family": family,
                    "mechanism": mechanism, "symbol": c, "minute_ts_utc": ts,
                    "adjudication_status": "synthetic", "source_reference": "synthetic_fixture",
                    "research_use_only": "1",
                })
                truth.append({"sample_id": csid, "label": "0", "truth_role": "matched_control"})
                features.append(_feature_row(c, ts, positive=False))
            n += 1
    rp = tmp_path / "registry.csv"
    gp = tmp_path / "truth.csv"
    fp = tmp_path / "external_features.csv"
    _write(rp, list(registry[0].keys()), registry)
    _write(gp, list(truth[0].keys()), truth)
    fields = ["minute_ts_utc", "symbol", "feature_status"] + list(DEFAULT_FEATURES) + ["research_use_only"]
    _write(fp, fields, features)
    return rp, fp, gp


def test_registry_rejects_labels():
    with pytest.raises(ValueError):
        validate_registry_schema([
            "sample_id", "case_id", "case_family", "mechanism", "symbol", "minute_ts_utc",
            "adjudication_status", "source_reference", "research_use_only", "label",
        ])


def test_registry_loads_without_ground_truth(tmp_path: Path):
    rp, _, _ = _external_fixture(tmp_path)
    rows = load_registry(rp)
    assert rows
    assert all("label" not in r for r in rows)


def test_frozen_bundle_requires_research_only(tmp_path: Path):
    bundle_path = _make_training_fixture(tmp_path)
    b = joblib.load(bundle_path)
    b["research_use_only"] = False
    bad = tmp_path / "bad.joblib"
    joblib.dump(b, bad)
    with pytest.raises(ValueError):
        load_frozen_bundle(bad)


def test_blind_scoring_does_not_change_bundle(tmp_path: Path):
    bundle = _make_training_fixture(tmp_path)
    rp, fp, _ = _external_fixture(tmp_path)
    before = _sha(bundle)
    out = tmp_path / "score"
    manifest = score_external(model_bundle=bundle, registry=rp, feature_vectors=fp, output_dir=out)
    after = _sha(bundle)
    assert before == after
    assert manifest["frozen_model_policy"]["retraining_performed"] is False
    assert manifest["frozen_model_policy"]["threshold_tuning_performed"] is False
    assert manifest["blindness_policy"]["ground_truth_loaded_during_scoring"] is False
    assert (out / "external_scores.csv").exists()


def test_external_scores_have_no_trading_outputs(tmp_path: Path):
    bundle = _make_training_fixture(tmp_path)
    rp, fp, _ = _external_fixture(tmp_path)
    out = tmp_path / "score"
    score_external(model_bundle=bundle, registry=rp, feature_vectors=fp, output_dir=out)
    header = (out / "external_scores.csv").read_text().splitlines()[0].lower()
    for bad in ["buy", "sell", "expected_return", "target_price", "position_size", "trade_direction"]:
        assert bad not in header


def test_external_evaluation_uses_frozen_threshold(tmp_path: Path):
    bundle = _make_training_fixture(tmp_path)
    rp, fp, gp = _external_fixture(tmp_path)
    score_dir = tmp_path / "score"
    score_external(model_bundle=bundle, registry=rp, feature_vectors=fp, output_dir=score_dir)
    eval_dir = tmp_path / "eval"
    report = evaluate_external(
        scores_csv=score_dir / "external_scores.csv",
        ground_truth=gp,
        output_dir=eval_dir,
    )
    frozen = load_frozen_bundle(bundle)["surveillance_threshold"]
    assert report["frozen_threshold"] == pytest.approx(float(frozen))
    assert report["threshold_tuning_performed"] is False
    assert set(report["metrics"]["by_case_family"]) == {"edgar_hack", "fda_regulatory", "cross_security"}
    assert (eval_dir / "external_validation_report.json").exists()


def test_ground_truth_is_joined_only_after_scoring(tmp_path: Path):
    bundle = _make_training_fixture(tmp_path)
    rp, fp, gp = _external_fixture(tmp_path)
    score_dir = tmp_path / "score"
    score_external(model_bundle=bundle, registry=rp, feature_vectors=fp, output_dir=score_dir)
    score_header = (score_dir / "external_scores.csv").read_text().splitlines()[0]
    assert "label" not in score_header
    report = evaluate_external(scores_csv=score_dir / "external_scores.csv", ground_truth=gp, output_dir=tmp_path / "eval")
    assert report["scoring_was_blind"] is True


def test_external_feature_lookahead_field_rejected(tmp_path: Path):
    bundle = _make_training_fixture(tmp_path)
    rp, fp, _ = _external_fixture(tmp_path)
    rows = list(csv.DictReader(fp.open()))
    fields = list(rows[0].keys()) + ["future_price"]
    for r in rows:
        r["future_price"] = "100"
    bad = tmp_path / "bad_features.csv"
    _write(bad, fields, rows)
    with pytest.raises(ValueError):
        score_external(model_bundle=bundle, registry=rp, feature_vectors=bad, output_dir=tmp_path / "badscore")
