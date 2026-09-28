from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from surveillance_feature_diagnostics import build_diagnostics, load_feature_rows


def _write(path: Path, fields: list[str], rows: list[dict]):
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def _fixture(tmp_path: Path):
    eval_rows = []
    feature_rows = []
    features = ["signal_a","signal_b","noise"]
    for i in range(16):
        label = 1 if i % 3 == 0 else 0
        year = 2020 if i < 8 else 2021
        family = "family_a" if i % 2 == 0 else "family_b"
        symbol = f"S{i:02d}"
        ts = f"{year}-06-{(i % 8)+1:02d}T18:00:00.000Z"
        score = 85 if label else 15 + (i % 3)
        eval_rows.append({
            "sample_id": f"X{i:02d}",
            "case_id": f"C{i:02d}",
            "case_family": family,
            "mechanism": "synthetic_mechanism",
            "symbol": symbol,
            "minute_ts_utc": ts,
            "label": str(label),
            "truth_role": "synthetic",
            "surveillance_risk_score": str(score),
            "flag_at_frozen_threshold": str(int(score >= 50)),
            "research_use_only": "1",
        })
        a = 3.0 + i * 0.01 if label else 0.2 + i * 0.01
        feature_rows.append({
            "symbol": symbol,
            "minute_ts_utc": ts,
            "signal_a": str(a),
            "signal_b": str(a * 2.0 + 0.001 * i),
            "noise": str((i % 5) * 0.2),
            "relative_minute": str(-30 + (i % 4) * 10),
        })
    ep = tmp_path / "evaluation.csv"
    fp = tmp_path / "features.csv"
    _write(ep, list(eval_rows[0].keys()), eval_rows)
    _write(fp, ["symbol","minute_ts_utc",*features,"relative_minute"], feature_rows)
    return ep, fp, features


def test_diagnostics_builds_factor_stability_and_redundancy_outputs(tmp_path: Path):
    ep, fp, features = _fixture(tmp_path)
    out = tmp_path / "out"
    manifest = build_diagnostics(
        evaluation_rows=ep,
        feature_vectors=fp,
        output_dir=out,
        selected_features=features,
        quantiles=4,
        redundancy_threshold=0.95,
    )
    assert manifest["sample_count"] == 16
    assert manifest["decay_status"] == "AVAILABLE"
    assert manifest["architecture_origin"]["third_party_source_copied_or_vendored"] is False
    for filename in [
        "feature_quantile_lift.csv","feature_temporal_stability.csv",
        "feature_cohort_stability.csv","feature_decay.csv",
        "feature_redundancy.csv","surveillance_score_diagnostics.json",
    ]:
        assert (out / filename).exists()
    redundancy = list(csv.DictReader((out / "feature_redundancy.csv").open()))
    pair = next(r for r in redundancy if {r["feature_a"],r["feature_b"]} == {"signal_a","signal_b"})
    assert int(pair["high_redundancy"]) == 1
    report = json.loads((out / "surveillance_score_diagnostics.json").read_text())
    assert report["overall"]["roc_auc"] == pytest.approx(1.0)
    assert report["overall"]["average_precision"] == pytest.approx(1.0)
    assert set(report["by_year"]) == {"2020","2021"}
    assert set(report["by_case_family"]) == {"family_a","family_b"}


def test_no_relative_minute_is_reported_not_invented(tmp_path: Path):
    ep, fp, features = _fixture(tmp_path)
    rows = list(csv.DictReader(fp.open()))
    fp2 = tmp_path / "features_no_decay.csv"
    _write(fp2, ["symbol","minute_ts_utc",*features], [
        {k:v for k,v in r.items() if k != "relative_minute"} for r in rows
    ])
    manifest = build_diagnostics(
        evaluation_rows=ep,
        feature_vectors=fp2,
        output_dir=tmp_path/"out2",
        selected_features=features,
    )
    assert manifest["decay_status"] == "NOT_AVAILABLE_NO_RELATIVE_MINUTE_INPUT"
    assert list(csv.DictReader((tmp_path/"out2"/"feature_decay.csv").open())) == []


def test_forbidden_lookahead_feature_rejected(tmp_path: Path):
    p = tmp_path / "bad.csv"
    _write(p, ["symbol","minute_ts_utc","future_price"], [{
        "symbol":"X","minute_ts_utc":"2020-01-01T10:00:00Z","future_price":"1"
    }])
    with pytest.raises(ValueError):
        load_feature_rows(p, selected_features=["future_price"])


def test_diagnostics_do_not_create_trading_outputs(tmp_path: Path):
    ep, fp, features = _fixture(tmp_path)
    out = tmp_path / "out"
    manifest = build_diagnostics(
        evaluation_rows=ep, feature_vectors=fp, output_dir=out, selected_features=features
    )
    assert manifest["model_policy"]["retraining_performed"] is False
    assert manifest["model_policy"]["threshold_tuning_performed"] is False
    assert manifest["model_policy"]["diagnostics_may_not_promote_or_activate_a_model"] is True
    generated = "\n".join(
        p.read_text()
        for p in out.iterdir()
        if p.suffix in {".csv",".json"} and p.name != "surveillance_feature_diagnostics_manifest.json"
    ).lower()
    for forbidden in ["buy","sell","expected_return","target_price","position_size","trade_direction"]:
        assert forbidden not in generated
