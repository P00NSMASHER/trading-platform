from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from model_training_harness import (
    DEFAULT_FEATURES,
    build_samples,
    choose_threshold,
    generate_oof_predictions,
    load_feature_vectors,
    load_matched_controls,
    split_temporal,
    train,
    validate_feature_schema,
)


def _write(path: Path, fields: list[str], rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def _feature_row(symbol: str, ts: str, *, positive: bool, status="full"):
    base = {
        "minute_ts_utc": ts,
        "symbol": symbol,
        "local_date": ts[:10],
        "local_minute": ts[11:16],
        "feature_status": status,
        "source_names": "synthetic_model_fixture",
        "research_use_only": "1",
    }
    for j, name in enumerate(DEFAULT_FEATURES):
        if name.endswith("count_5m") or name.endswith("count_15m") or name.endswith("count_30m") or name == "multivariate_2sigma_count":
            val = 3.0 if positive else 0.0
        elif name.startswith("return_"):
            val = 0.002 * ((j % 3) - 1) + (0.001 if positive else 0.0)
        elif name.startswith("realized_vol_"):
            val = 0.01 + 0.001 * (j % 4)
        elif "volume" in name or "turnover" in name or "spread" in name or "multivariate" in name:
            val = (2.5 + 0.04 * (j % 5)) if positive else (0.15 + 0.02 * (j % 4))
        else:
            val = (0.7 + 0.02 * (j % 4)) if positive else (0.05 + 0.01 * (j % 3))
        base[name] = str(val)
    return base


def _synthetic_files(tmp_path: Path):
    matches = []
    features = []
    event_no = 0
    # Development: 12 treated issuers, two events each across 2011-2014.
    dev_issuers = [f"T{i:02d}" for i in range(12)]
    for year in [2011, 2012, 2013, 2014]:
        for k in range(6):
            issuer = dev_issuers[(event_no // 2) % len(dev_issuers)]
            event_no += 1
            day = 5 + k
            ts = f"{year}-02-{day:02d}T19:{30+k:02d}:00.000Z"
            event_id = f"D{event_no:03d}"
            features.append(_feature_row(issuer, ts, positive=True))
            for rank in range(1, 4):
                control = f"C{event_no:03d}{rank}"
                features.append(_feature_row(control, ts, positive=False))
                matches.append({
                    "match_id": f"M{event_no:03d}{rank}", "event_id": event_id,
                    "treated_symbol": issuer, "treated_minute_ts_utc": ts,
                    "control_rank": str(rank), "control_symbol": control,
                    "control_minute_ts_utc": ts,
                })
    # Holdout: four seen and four unseen treated issuers.
    hold_issuers = dev_issuers[:4] + [f"H{i:02d}" for i in range(4)]
    for k, issuer in enumerate(hold_issuers):
        ts = f"2015-03-{10+k:02d}T19:{35+k:02d}:00.000Z"
        event_id = f"H{k+1:03d}"
        features.append(_feature_row(issuer, ts, positive=True))
        for rank in range(1, 4):
            control = f"HC{k+1:03d}{rank}"
            features.append(_feature_row(control, ts, positive=False))
            matches.append({
                "match_id": f"HM{k+1:03d}{rank}", "event_id": event_id,
                "treated_symbol": issuer, "treated_minute_ts_utc": ts,
                "control_rank": str(rank), "control_symbol": control,
                "control_minute_ts_utc": ts,
            })
    mp = tmp_path / "matched.csv"
    fp = tmp_path / "features.csv"
    _write(mp, list(matches[0].keys()), matches)
    feature_fields = ["minute_ts_utc", "symbol", "local_date", "local_minute", "feature_status"] + list(DEFAULT_FEATURES) + ["source_names", "research_use_only"]
    _write(fp, feature_fields, features)
    return mp, fp


def test_forbidden_lookahead_feature_name_rejected():
    with pytest.raises(ValueError):
        validate_feature_schema(list(DEFAULT_FEATURES) + ["future_price"])
    with pytest.raises(ValueError):
        validate_feature_schema(list(DEFAULT_FEATURES) + ["earnings_surprise"])


def test_sample_builder_creates_one_positive_per_event_and_controls(tmp_path: Path):
    mp, fp = _synthetic_files(tmp_path)
    feats, _ = load_feature_vectors(fp)
    matches = load_matched_controls(mp)
    samples, X = build_samples(matches, feats)
    events = {s.event_id for s in samples}
    assert sum(s.label for s in samples) == len(events)
    assert len(samples) == len(events) * 4
    assert X.shape[0] == len(samples)


def test_temporal_split_keeps_2015_out_of_development(tmp_path: Path):
    mp, fp = _synthetic_files(tmp_path)
    feats, _ = load_feature_vectors(fp)
    samples, X = build_samples(load_matched_controls(mp), feats)
    dev, hold = split_temporal(samples, X, holdout_start_year=2015)
    assert max(samples[i].event_year for i in dev) <= 2014
    assert min(samples[i].event_year for i in hold) >= 2015


def test_grouped_oof_has_no_issuer_overlap(tmp_path: Path):
    mp, fp = _synthetic_files(tmp_path)
    feats, _ = load_feature_vectors(fp)
    samples, X = build_samples(load_matched_controls(mp), feats)
    dev, _ = split_temporal(samples, X, holdout_start_year=2015)
    y = np.array([samples[i].label for i in dev])
    groups = np.array([samples[i].group_issuer for i in dev], dtype=object)
    a, b, audit = generate_oof_predictions(X[dev], y, groups, cv_folds=4, seed=7)
    assert len(a) == len(dev) == len(b)
    assert all(x["group_overlap_count"] == 0 for x in audit)


def test_threshold_respects_false_positive_ceiling():
    y = np.array([1, 1, 0, 0, 0, 0], dtype=int)
    scores = np.array([0.9, 0.8, 0.7, 0.2, 0.1, 0.05])
    threshold, diag = choose_threshold(y, scores, target_fpr=0.0)
    assert diag["development_fpr"] == 0.0
    assert threshold > 0.7


def test_end_to_end_training_outputs_surveillance_only_artifacts(tmp_path: Path):
    mp, fp = _synthetic_files(tmp_path)
    out = tmp_path / "out"
    manifest = train(
        matched_controls=mp,
        feature_vectors=fp,
        output_dir=out,
        holdout_start_year=2015,
        target_fpr=0.10,
        cv_folds=4,
        seed=11,
    )
    assert manifest["validation_policy"]["cv_group_overlap_count"] == 0
    assert manifest["sample_counts"]["holdout_positive"] == 8
    assert manifest["validation_policy"]["unseen_issuer_holdout_rows"] > 0
    assert (out / "model_bundle.joblib").exists()
    assert (out / "training_manifest.json").exists()
    assert (out / "holdout_scores.csv").exists()
    header = (out / "holdout_scores.csv").read_text().splitlines()[0].lower()
    for bad in ["expected_return", "target_price", "position_size", "order_instruction", "trade_direction"]:
        assert bad not in header
    saved = json.loads((out / "training_manifest.json").read_text())
    assert "BUY" in saved["prohibited_outputs"]
    assert saved["deployment_status"].startswith("offline research")


def test_holdout_scores_are_bounded(tmp_path: Path):
    mp, fp = _synthetic_files(tmp_path)
    out = tmp_path / "out"
    train(matched_controls=mp, feature_vectors=fp, output_dir=out, target_fpr=0.10)
    rows = list(csv.DictReader((out / "holdout_scores.csv").open()))
    vals = [float(r["surveillance_risk_score"]) for r in rows]
    assert all(0.0 <= v <= 100.0 for v in vals)


def test_manifest_hashes_inputs(tmp_path: Path):
    mp, fp = _synthetic_files(tmp_path)
    out = tmp_path / "out"
    manifest = train(matched_controls=mp, feature_vectors=fp, output_dir=out, target_fpr=0.10)
    assert len(manifest["inputs"]["matched_controls_sha256"]) == 64
    assert len(manifest["inputs"]["feature_vectors_sha256"]) == 64
