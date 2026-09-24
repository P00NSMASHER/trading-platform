from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import joblib
import numpy as np

import model_training_harness as mt

SCHEMA_VERSION = "0.13.0"

GRAPH_FEATURES = (
    "related_security_count",
    "direct_related_security_count",
    "second_hop_related_security_count",
    "confidence_weighted_breadth",
    "max_path_confidence",
    "mean_path_confidence",
    "related_feature_count",
    "anomalous_related_count",
    "anomalous_related_fraction",
    "synchronized_equity_volume_anomaly_count",
    "synchronized_option_volume_anomaly_count",
    "synchronized_spread_widen_count",
    "max_related_multivariate_l2",
    "mean_related_multivariate_l2",
    "confidence_weighted_peer_anomaly",
    "propagation_strength",
    "min_anomalous_hop",
    "mean_anomalous_hop",
    "prior_visible_case_count",
    "prior_case_similarity_max",
    "prior_case_similarity_mean",
)

FORBIDDEN_GRAPH_TERMS = (
    "future",
    "next_day",
    "nextday",
    "post_event",
    "postevent",
    "earnings_surprise",
    "unreleased",
    "enforcement_outcome",
    "prosecution_outcome",
    "expected_return",
    "target_price",
    "position_size",
    "trade_direction",
    "order_instruction",
    "credential",
    "secret_value",
    "private_content",
)

PROHIBITED_OUTPUTS = list(mt.PROHIBITED_OUTPUTS)


@dataclass(frozen=True)
class ComparisonScore:
    sample_id: str
    event_id: str
    group_issuer: str
    symbol: str
    minute_ts_utc: str
    event_year: int
    label: int
    sample_role: str
    champion_risk_score: str
    challenger_risk_score: str
    base_ablation_risk_score: str
    challenger_flag: int
    champion_flag: int
    research_use_only: int = 1


def _clean(v: str | None) -> str:
    return (v or "").strip()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _fmt(v: float | None, digits: int = 10) -> str:
    if v is None or not math.isfinite(v):
        return ""
    return (f"{v:.{digits}f}").rstrip("0").rstrip(".")


def _ts_key(v: str) -> str:
    return mt._ts_key(mt._parse_ts(v))


def validate_graph_schema(fieldnames: Iterable[str], selected_features: Iterable[str] = GRAPH_FEATURES) -> tuple[str, ...]:
    names = tuple(fieldnames)
    for raw in names:
        low = raw.lower()
        if any(term in low for term in FORBIDDEN_GRAPH_TERMS):
            raise ValueError(f"forbidden/lookahead graph field: {raw}")
    selected = tuple(selected_features)
    missing = [name for name in selected if name not in names]
    if missing:
        raise ValueError(f"graph feature file missing selected fields: {missing}")
    return selected


def load_graph_features(path: Path, *, selected_features: Iterable[str] = GRAPH_FEATURES) -> tuple[dict[tuple[str, str], dict], tuple[str, ...]]:
    out: dict[tuple[str, str], dict] = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {
            "minute_ts_utc", "symbol", "visibility_mode", "graph_feature_status",
            "research_use_only",
        }
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"graph feature file missing required columns: {sorted(missing)}")
        selected = validate_graph_schema(reader.fieldnames or [], selected_features)
        for i, row in enumerate(reader, 2):
            symbol = _clean(row.get("symbol")).upper()
            ts = _ts_key(row.get("minute_ts_utc", ""))
            mode = _clean(row.get("visibility_mode")).lower()
            status = _clean(row.get("graph_feature_status")).lower()
            research_only = _clean(row.get("research_use_only"))
            if not symbol:
                raise ValueError(f"graph row {i}: blank symbol")
            if mode != "live_surveillance":
                raise ValueError(f"graph row {i}: only live_surveillance vectors may train challenger")
            if status not in {"full", "partial"}:
                raise ValueError(f"graph row {i}: graph status must be full/partial")
            if research_only not in {"1", "true", "True"}:
                raise ValueError(f"graph row {i}: research_use_only must be true")
            key = (symbol, ts)
            if key in out:
                raise ValueError(f"duplicate graph feature vector for {key}")
            vals = np.array([mt._parse_float(row.get(name)) for name in selected], dtype=float)
            out[key] = {
                "symbol": symbol,
                "minute_ts_utc": ts,
                "visibility_mode": mode,
                "graph_feature_status": status,
                "values": vals,
            }
    if not out:
        raise ValueError("graph feature file contains no usable rows")
    return out, selected


def _graph_matrix(samples: list[mt.TrainingSample], graph: dict[tuple[str, str], dict]) -> np.ndarray:
    rows: list[np.ndarray] = []
    for s in samples:
        key = (s.symbol.upper(), s.minute_ts_utc)
        row = graph.get(key)
        if row is None:
            raise ValueError(f"missing graph vector for sample {s.sample_id}: {key}")
        rows.append(row["values"])
    return np.vstack(rows)


def _score_pair(bundle: dict, X: np.ndarray) -> np.ndarray:
    w = tuple(bundle.get("blend_weights", (0.5, 0.5)))
    p1 = bundle["elastic_net"].predict_proba(X)[:, 1]
    p2 = bundle["boosted_model"].predict_proba(X)[:, 1]
    raw = float(w[0]) * p1 + float(w[1]) * p2
    return mt.calibrate(bundle["calibrator"], raw)


def _fit_candidate(X_dev: np.ndarray, y_dev: np.ndarray, groups_dev: np.ndarray, *, cv_folds: int, seed: int, target_fpr: float):
    o1, o2, audit = mt.generate_oof_predictions(X_dev, y_dev, groups_dev, cv_folds=cv_folds, seed=seed)
    raw_oof = 0.5 * o1 + 0.5 * o2
    calibrator = mt.fit_calibrator(y_dev, raw_oof)
    oof = mt.calibrate(calibrator, raw_oof)
    threshold, threshold_diag = mt.choose_threshold(y_dev, oof, target_fpr=target_fpr)
    elastic, boosted = mt._make_models(seed + 1000)
    elastic.fit(X_dev, y_dev)
    boosted.fit(X_dev, y_dev)
    return {
        "elastic_net": elastic,
        "boosted_model": boosted,
        "calibrator": calibrator,
        "blend_weights": (0.5, 0.5),
        "threshold": threshold,
        "threshold_diagnostics": threshold_diag,
        "oof_scores": oof,
        "cv_audit": audit,
    }


def _score_candidate(candidate: dict, X: np.ndarray) -> np.ndarray:
    p1 = candidate["elastic_net"].predict_proba(X)[:, 1]
    p2 = candidate["boosted_model"].predict_proba(X)[:, 1]
    raw = 0.5 * p1 + 0.5 * p2
    return mt.calibrate(candidate["calibrator"], raw)


def _is_synthetic_feature_file(path: Path) -> bool:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if "source_names" not in (reader.fieldnames or []):
            return False
        for row in reader:
            if "synthetic" in _clean(row.get("source_names")).lower():
                return True
    return False


def _metric_delta(full: dict, other: dict, key: str) -> float | None:
    a, b = full.get(key), other.get(key)
    if a is None or b is None:
        return None
    return float(a) - float(b)


def _promotion_decision(
    *,
    champion: dict,
    challenger: dict,
    challenger_unseen: dict,
    champion_unseen: dict,
    base_ablation: dict,
    target_fpr: float,
    synthetic: bool,
    min_ap_gain: float,
    min_graph_ap_gain: float,
    max_fpr_increase: float,
    max_brier_increase: float,
) -> dict:
    reasons: list[str] = []
    checks: dict[str, bool] = {}

    cap = min(target_fpr, (champion.get("false_positive_rate") or 0.0) + max_fpr_increase)
    ch_ap = challenger.get("average_precision")
    champ_ap = champion.get("average_precision")
    base_ap = base_ablation.get("average_precision")
    ch_fpr = challenger.get("false_positive_rate")
    ch_brier = challenger.get("brier")
    champ_brier = champion.get("brier")
    unseen_ap = challenger_unseen.get("average_precision")
    champ_unseen_ap = champion_unseen.get("average_precision")

    checks["temporal_ap_gain"] = bool(ch_ap is not None and champ_ap is not None and ch_ap >= champ_ap + min_ap_gain)
    checks["graph_ablation_gain"] = bool(ch_ap is not None and base_ap is not None and ch_ap >= base_ap + min_graph_ap_gain)
    checks["false_alert_guardrail"] = bool(ch_fpr is not None and ch_fpr <= cap + 1e-12)
    checks["brier_guardrail"] = bool(ch_brier is not None and champ_brier is not None and ch_brier <= champ_brier + max_brier_increase)
    checks["unseen_issuer_not_worse"] = bool(
        unseen_ap is not None and champ_unseen_ap is not None and unseen_ap + 1e-12 >= champ_unseen_ap
    )

    for name, ok in checks.items():
        if not ok:
            reasons.append(f"failed:{name}")
    if synthetic:
        reasons.append("blocked:synthetic_fixture")

    eligible = all(checks.values()) and not synthetic
    return {
        "eligible_for_human_promotion_review": bool(eligible),
        "active_model_changed": False,
        "automatic_promotion_permitted": False,
        "checks": checks,
        "guardrails": {
            "target_fpr": target_fpr,
            "effective_fpr_cap": cap,
            "min_temporal_average_precision_gain": min_ap_gain,
            "min_graph_ablation_average_precision_gain": min_graph_ap_gain,
            "max_false_positive_rate_increase": max_fpr_increase,
            "max_brier_increase": max_brier_increase,
        },
        "reasons": reasons or ["eligible_for_human_review_only"],
        "warning": "Promotion eligibility is a research gate, not evidence of real-world market-abuse detection performance.",
    }


def train_challenger(
    *,
    matched_controls: Path,
    base_feature_vectors: Path,
    graph_feature_vectors: Path,
    champion_bundle: Path,
    output_dir: Path,
    holdout_start_year: int = 2015,
    target_fpr: float = 0.05,
    cv_folds: int = 4,
    seed: int = 29,
    min_status: str = "partial",
    min_ap_gain: float = 0.02,
    min_graph_ap_gain: float = 0.01,
    max_fpr_increase: float = 0.01,
    max_brier_increase: float = 0.01,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    champion_hash_before = _sha256(champion_bundle)
    champion = joblib.load(champion_bundle)
    if not champion.get("research_use_only", False):
        raise ValueError("champion bundle must be research_use_only")

    base, base_names = mt.load_feature_vectors(
        base_feature_vectors, min_status=min_status, selected_features=tuple(champion["selected_features"])
    )
    matches = mt.load_matched_controls(matched_controls)
    samples, X_base = mt.build_samples(matches, base)
    graph, graph_names = load_graph_features(graph_feature_vectors)
    X_graph = _graph_matrix(samples, graph)
    X_full = np.hstack([X_base, X_graph])

    y = np.array([s.label for s in samples], dtype=int)
    groups = np.array([s.group_issuer for s in samples], dtype=object)
    dev_idx, hold_idx = mt.split_temporal(samples, X_full, holdout_start_year=holdout_start_year)
    y_dev, y_hold = y[dev_idx], y[hold_idx]
    groups_dev = groups[dev_idx]

    challenger = _fit_candidate(
        X_full[dev_idx], y_dev, groups_dev, cv_folds=cv_folds, seed=seed, target_fpr=target_fpr
    )
    ablation = _fit_candidate(
        X_base[dev_idx], y_dev, groups_dev, cv_folds=cv_folds, seed=seed + 77, target_fpr=target_fpr
    )

    challenger_hold = _score_candidate(challenger, X_full[hold_idx])
    ablation_hold = _score_candidate(ablation, X_base[hold_idx])
    champion_hold = _score_pair(champion, X_base[hold_idx])

    challenger_metrics = mt.evaluate(y_hold, challenger_hold, challenger["threshold"])
    ablation_metrics = mt.evaluate(y_hold, ablation_hold, ablation["threshold"])
    champion_metrics = mt.evaluate(y_hold, champion_hold, float(champion["surveillance_threshold"]))

    dev_issuers = set(groups[dev_idx].tolist())
    unseen_mask = np.array([samples[i].group_issuer not in dev_issuers for i in hold_idx], dtype=bool)
    if unseen_mask.any():
        challenger_unseen = mt.evaluate(y_hold[unseen_mask], challenger_hold[unseen_mask], challenger["threshold"])
        ablation_unseen = mt.evaluate(y_hold[unseen_mask], ablation_hold[unseen_mask], ablation["threshold"])
        champion_unseen = mt.evaluate(y_hold[unseen_mask], champion_hold[unseen_mask], float(champion["surveillance_threshold"]))
    else:
        challenger_unseen = mt.evaluate(np.array([], dtype=int), np.array([], dtype=float), challenger["threshold"])
        ablation_unseen = mt.evaluate(np.array([], dtype=int), np.array([], dtype=float), ablation["threshold"])
        champion_unseen = mt.evaluate(np.array([], dtype=int), np.array([], dtype=float), float(champion["surveillance_threshold"]))

    synthetic = _is_synthetic_feature_file(base_feature_vectors)
    promotion = _promotion_decision(
        champion=champion_metrics,
        challenger=challenger_metrics,
        challenger_unseen=challenger_unseen,
        champion_unseen=champion_unseen,
        base_ablation=ablation_metrics,
        target_fpr=target_fpr,
        synthetic=synthetic,
        min_ap_gain=min_ap_gain,
        min_graph_ap_gain=min_graph_ap_gain,
        max_fpr_increase=max_fpr_increase,
        max_brier_increase=max_brier_increase,
    )

    bundle = {
        "schema_version": SCHEMA_VERSION,
        "base_features": tuple(base_names),
        "graph_features": tuple(graph_names),
        "selected_features": tuple(base_names) + tuple(graph_names),
        "elastic_net": challenger["elastic_net"],
        "boosted_model": challenger["boosted_model"],
        "calibrator": challenger["calibrator"],
        "blend_weights": (0.5, 0.5),
        "surveillance_threshold": challenger["threshold"],
        "holdout_start_year": holdout_start_year,
        "visibility_mode_required": "live_surveillance",
        "research_use_only": True,
        "active_model": False,
    }
    challenger_path = output_dir / "challenger_model_bundle.joblib"
    joblib.dump(bundle, challenger_path)

    score_rows: list[ComparisonScore] = []
    for j, idx in enumerate(hold_idx):
        s = samples[idx]
        score_rows.append(ComparisonScore(
            sample_id=s.sample_id,
            event_id=s.event_id,
            group_issuer=s.group_issuer,
            symbol=s.symbol,
            minute_ts_utc=s.minute_ts_utc,
            event_year=s.event_year,
            label=s.label,
            sample_role=s.sample_role,
            champion_risk_score=_fmt(100 * champion_hold[j], 6),
            challenger_risk_score=_fmt(100 * challenger_hold[j], 6),
            base_ablation_risk_score=_fmt(100 * ablation_hold[j], 6),
            challenger_flag=int(challenger_hold[j] >= challenger["threshold"]),
            champion_flag=int(champion_hold[j] >= float(champion["surveillance_threshold"])),
        ))
    mt._write_dataclass_csv(output_dir / "holdout_comparison_scores.csv", score_rows)

    combined_names = tuple(base_names) + tuple(graph_names)
    coeffs = mt._elastic_coefficients(challenger["elastic_net"], combined_names)
    mt._write_dict_csv(output_dir / "challenger_elastic_coefficients.csv", coeffs, ["feature", "coefficient"])
    graph_coeffs = [r for r in coeffs if r["feature"] in set(graph_names)]
    mt._write_dict_csv(output_dir / "graph_feature_coefficients.csv", graph_coeffs, ["feature", "coefficient"])

    cv_audit = {
        "challenger": challenger["cv_audit"],
        "base_ablation": ablation["cv_audit"],
        "all_group_overlap_counts_zero": all(
            r["group_overlap_count"] == 0 for r in challenger["cv_audit"] + ablation["cv_audit"]
        ),
    }
    (output_dir / "cv_split_audit.json").write_text(json.dumps(cv_audit, indent=2), encoding="utf-8")
    (output_dir / "promotion_decision.json").write_text(json.dumps(promotion, indent=2), encoding="utf-8")

    champion_hash_after = _sha256(champion_bundle)
    if champion_hash_after != champion_hash_before:
        raise AssertionError("champion model changed during challenger training")

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "purpose": "graph-aware historical informed-trading market-surveillance challenger research",
        "research_use_only": True,
        "inputs": {
            "matched_controls": str(matched_controls),
            "matched_controls_sha256": _sha256(matched_controls),
            "base_feature_vectors": str(base_feature_vectors),
            "base_feature_vectors_sha256": _sha256(base_feature_vectors),
            "graph_feature_vectors": str(graph_feature_vectors),
            "graph_feature_vectors_sha256": _sha256(graph_feature_vectors),
            "champion_bundle": str(champion_bundle),
            "champion_bundle_sha256_before": champion_hash_before,
            "champion_bundle_sha256_after": champion_hash_after,
        },
        "feature_policy": {
            "base_features": list(base_names),
            "graph_features": list(graph_names),
            "graph_visibility_mode_required": "live_surveillance",
            "later_public_enforcement_facts_rejected_from_historical_live_scoring": True,
            "forensic_mode_vectors_rejected": True,
            "future_and_trading_fields_rejected": True,
        },
        "validation_policy": {
            "holdout_start_year": holdout_start_year,
            "cv_folds": cv_folds,
            "grouping_unit": "treated issuer; treated event and matched controls stay together",
            "challenger_cv_group_overlap_count": sum(r["group_overlap_count"] for r in challenger["cv_audit"]),
            "base_ablation_cv_group_overlap_count": sum(r["group_overlap_count"] for r in ablation["cv_audit"]),
            "unseen_issuer_holdout_rows": int(unseen_mask.sum()),
        },
        "metrics": {
            "champion_temporal_holdout": champion_metrics,
            "challenger_temporal_holdout": challenger_metrics,
            "base_ablation_temporal_holdout": ablation_metrics,
            "champion_unseen_issuer_holdout": champion_unseen,
            "challenger_unseen_issuer_holdout": challenger_unseen,
            "base_ablation_unseen_issuer_holdout": ablation_unseen,
            "challenger_minus_champion": {
                "average_precision": _metric_delta(challenger_metrics, champion_metrics, "average_precision"),
                "brier": _metric_delta(challenger_metrics, champion_metrics, "brier"),
                "false_positive_rate": _metric_delta(challenger_metrics, champion_metrics, "false_positive_rate"),
            },
            "graph_increment_over_base_ablation": {
                "average_precision": _metric_delta(challenger_metrics, ablation_metrics, "average_precision"),
                "brier": _metric_delta(challenger_metrics, ablation_metrics, "brier"),
                "false_positive_rate": _metric_delta(challenger_metrics, ablation_metrics, "false_positive_rate"),
            },
        },
        "promotion": promotion,
        "synthetic_fixture_detected": synthetic,
        "active_champion_modified": False,
        "outputs": {
            "challenger_model_bundle": challenger_path.name,
            "holdout_comparison_scores": "holdout_comparison_scores.csv",
            "challenger_elastic_coefficients": "challenger_elastic_coefficients.csv",
            "graph_feature_coefficients": "graph_feature_coefficients.csv",
            "cv_split_audit": "cv_split_audit.json",
            "promotion_decision": "promotion_decision.json",
        },
        "prohibited_outputs": PROHIBITED_OUTPUTS,
        "deployment_status": "offline challenger artifact only; champion remains active/frozen; no market feed, broker, notification, or execution integration",
        "interpretation_warning": "A surveillance score prioritizes anomalous behavior for review and is not a probability that a crime occurred.",
    }
    (output_dir / "challenger_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    p = argparse.ArgumentParser(description="Train and evaluate a graph-aware surveillance challenger without changing champion")
    p.add_argument("--matched-controls", type=Path, required=True)
    p.add_argument("--base-features", type=Path, required=True)
    p.add_argument("--graph-features", type=Path, required=True)
    p.add_argument("--champion-bundle", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--holdout-start-year", type=int, default=2015)
    p.add_argument("--target-fpr", type=float, default=0.05)
    p.add_argument("--cv-folds", type=int, default=4)
    p.add_argument("--seed", type=int, default=29)
    args = p.parse_args()
    manifest = train_challenger(
        matched_controls=args.matched_controls,
        base_feature_vectors=args.base_features,
        graph_feature_vectors=args.graph_features,
        champion_bundle=args.champion_bundle,
        output_dir=args.output_dir,
        holdout_start_year=args.holdout_start_year,
        target_fpr=args.target_fpr,
        cv_folds=args.cv_folds,
        seed=args.seed,
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
