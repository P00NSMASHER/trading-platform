from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import joblib
import pytest

import graph_challenger_harness as gc
import model_training_harness as mt


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, fields: list[str], rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(rows)


def _graph_file_for_base(tmp_path: Path, base_feature_file: Path, matches_file: Path) -> Path:
    matches = list(csv.DictReader(matches_file.open()))
    treated = {(r["treated_symbol"], mt._ts_key(mt._parse_ts(r["treated_minute_ts_utc"]))) for r in matches}
    rows = []
    base_rows = list(csv.DictReader(base_feature_file.open()))
    for i, r in enumerate(base_rows):
        key = (r["symbol"], mt._ts_key(mt._parse_ts(r["minute_ts_utc"])))
        positive = key in treated
        row = {
            "minute_ts_utc": key[1], "symbol": r["symbol"], "security_id": f"SEC:{r['symbol']}",
            "visibility_mode": "live_surveillance", "graph_feature_status": "full", "seed_feature_status": r["feature_status"],
            "graph_db_sha256": "a"*64, "feature_input_sha256": "b"*64, "research_use_only": "1",
        }
        for j, name in enumerate(gc.GRAPH_FEATURES):
            if name in {"min_anomalous_hop", "mean_anomalous_hop"}:
                val = 1.0 if positive else 2.0
            elif name in {"prior_visible_case_count", "prior_case_similarity_max", "prior_case_similarity_mean"}:
                val = 0.0
            elif "count" in name:
                val = 2.0 + (j % 2) if positive else 0.0
            elif "fraction" in name or "confidence" in name or "similarity" in name:
                val = 0.8 if positive else 0.1
            else:
                val = 3.0 + 0.05*(j % 3) if positive else 0.2 + 0.01*(j % 3)
            row[name] = str(val)
        rows.append(row)
    fields = ["minute_ts_utc","symbol","security_id","visibility_mode","graph_feature_status","seed_feature_status"] + list(gc.GRAPH_FEATURES) + ["graph_db_sha256","feature_input_sha256","research_use_only"]
    path = tmp_path / "graph.csv"
    _write(path, fields, rows)
    return path


def _inputs(tmp_path: Path):
    # Reuse the Step-6 synthetic fixture helper to preserve exactly the same time/group semantics.
    from test_model_training_harness import _synthetic_files
    mp, fp = _synthetic_files(tmp_path)
    gp = _graph_file_for_base(tmp_path, fp, mp)
    champion_dir = tmp_path / "champion"
    mt.train(matched_controls=mp, feature_vectors=fp, output_dir=champion_dir, target_fpr=0.10, seed=11)
    return mp, fp, gp, champion_dir / "model_bundle.joblib"


def test_graph_schema_rejects_forensic_vectors(tmp_path: Path):
    mp, fp, gp, cb = _inputs(tmp_path)
    rows = list(csv.DictReader(gp.open()))
    rows[0]["visibility_mode"] = "historical_forensics"
    fields = list(rows[0].keys())
    bad = tmp_path / "bad.csv"; _write(bad, fields, rows)
    with pytest.raises(ValueError, match="live_surveillance"):
        gc.load_graph_features(bad)


def test_graph_schema_rejects_future_field():
    with pytest.raises(ValueError):
        gc.validate_graph_schema(list(gc.GRAPH_FEATURES) + ["future_case_result"])


def test_graph_matrix_requires_every_training_sample(tmp_path: Path):
    mp, fp, gp, cb = _inputs(tmp_path)
    graph, _ = gc.load_graph_features(gp)
    graph.pop(next(iter(graph)))
    base, _ = mt.load_feature_vectors(fp)
    samples, _ = mt.build_samples(mt.load_matched_controls(mp), base)
    with pytest.raises(ValueError, match="missing graph vector"):
        gc._graph_matrix(samples, graph)


def test_challenger_preserves_champion_and_blocks_synthetic_promotion(tmp_path: Path):
    mp, fp, gp, cb = _inputs(tmp_path)
    before = _sha(cb)
    out = tmp_path / "out"
    manifest = gc.train_challenger(
        matched_controls=mp, base_feature_vectors=fp, graph_feature_vectors=gp,
        champion_bundle=cb, output_dir=out, target_fpr=0.10, seed=31,
        min_ap_gain=0.0, min_graph_ap_gain=0.0,
    )
    after = _sha(cb)
    assert before == after
    assert manifest["active_champion_modified"] is False
    assert manifest["promotion"]["active_model_changed"] is False
    assert manifest["promotion"]["automatic_promotion_permitted"] is False
    assert manifest["promotion"]["eligible_for_human_promotion_review"] is False
    assert "blocked:synthetic_fixture" in manifest["promotion"]["reasons"]


def test_grouped_cv_has_zero_overlap_for_challenger_and_ablation(tmp_path: Path):
    mp, fp, gp, cb = _inputs(tmp_path)
    out = tmp_path / "out"
    manifest = gc.train_challenger(
        matched_controls=mp, base_feature_vectors=fp, graph_feature_vectors=gp,
        champion_bundle=cb, output_dir=out, target_fpr=0.10,
    )
    assert manifest["validation_policy"]["challenger_cv_group_overlap_count"] == 0
    assert manifest["validation_policy"]["base_ablation_cv_group_overlap_count"] == 0
    audit = json.loads((out / "cv_split_audit.json").read_text())
    assert audit["all_group_overlap_counts_zero"] is True


def test_holdout_comparison_contains_only_surveillance_outputs(tmp_path: Path):
    mp, fp, gp, cb = _inputs(tmp_path)
    out = tmp_path / "out"
    gc.train_challenger(
        matched_controls=mp, base_feature_vectors=fp, graph_feature_vectors=gp,
        champion_bundle=cb, output_dir=out, target_fpr=0.10,
    )
    header = (out / "holdout_comparison_scores.csv").read_text().splitlines()[0].lower()
    for bad in ["expected_return", "target_price", "position_size", "trade_direction", "order_instruction"]:
        assert bad not in header
    assert "challenger_risk_score" in header and "champion_risk_score" in header


def test_bundle_is_challenger_only_and_research_only(tmp_path: Path):
    mp, fp, gp, cb = _inputs(tmp_path)
    out = tmp_path / "out"
    gc.train_challenger(
        matched_controls=mp, base_feature_vectors=fp, graph_feature_vectors=gp,
        champion_bundle=cb, output_dir=out, target_fpr=0.10,
    )
    b = joblib.load(out / "challenger_model_bundle.joblib")
    assert b["research_use_only"] is True
    assert b["active_model"] is False
    assert b["visibility_mode_required"] == "live_surveillance"
    assert set(gc.GRAPH_FEATURES).issubset(set(b["selected_features"]))


def test_manifest_reports_graph_ablation_and_unseen_issuer_metrics(tmp_path: Path):
    mp, fp, gp, cb = _inputs(tmp_path)
    out = tmp_path / "out"
    manifest = gc.train_challenger(
        matched_controls=mp, base_feature_vectors=fp, graph_feature_vectors=gp,
        champion_bundle=cb, output_dir=out, target_fpr=0.10,
    )
    assert "graph_increment_over_base_ablation" in manifest["metrics"]
    assert "challenger_unseen_issuer_holdout" in manifest["metrics"]
    assert manifest["validation_policy"]["unseen_issuer_holdout_rows"] > 0


def test_promotion_gate_rejects_false_alert_increase():
    champ = {"average_precision": .7, "false_positive_rate": .01, "brier": .1}
    ch = {"average_precision": .8, "false_positive_rate": .2, "brier": .09}
    base = {"average_precision": .72, "false_positive_rate": .02, "brier": .1}
    unseen = {"average_precision": .8}; champ_unseen = {"average_precision": .7}
    d = gc._promotion_decision(
        champion=champ, challenger=ch, challenger_unseen=unseen, champion_unseen=champ_unseen,
        base_ablation=base, target_fpr=.05, synthetic=False, min_ap_gain=.02,
        min_graph_ap_gain=.01, max_fpr_increase=.01, max_brier_increase=.01,
    )
    assert d["eligible_for_human_promotion_review"] is False
    assert d["checks"]["false_alert_guardrail"] is False
