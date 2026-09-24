from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import joblib
import numpy as np
from sklearn.calibration import calibration_curve
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

SCHEMA_VERSION = "0.6.0"

# Explicit allowlist: all are point-in-time outputs of Step 4.
DEFAULT_FEATURES = (
    "full_history_fraction",
    "equity_volume_z",
    "equity_turnover_z",
    "equity_spread_z",
    "option_volume_z",
    "option_dollar_volume_z",
    "equity_volume_ratio",
    "option_volume_ratio",
    "call_put_imbalance",
    "option_contracts_per_100_equity_shares",
    "return_1m",
    "return_5m",
    "return_15m",
    "return_30m",
    "realized_vol_5m",
    "realized_vol_15m",
    "realized_vol_30m",
    "equity_volume_peak_z_5m",
    "equity_volume_peak_z_15m",
    "equity_volume_peak_z_30m",
    "equity_volume_anomaly_count_5m",
    "equity_volume_anomaly_count_15m",
    "equity_volume_anomaly_count_30m",
    "equity_volume_z_slope_5m",
    "equity_volume_z_slope_15m",
    "equity_volume_z_slope_30m",
    "equity_volume_acceleration_5m",
    "spread_widen_count_5m",
    "option_volume_anomaly_count_5m",
    "multivariate_l2",
    "multivariate_2sigma_count",
    "multivariate_change_5m",
)

FORBIDDEN_INPUT_TERMS = (
    "future",
    "next_day",
    "nextday",
    "post_event",
    "postevent",
    "earnings_surprise",
    "unreleased",
    "public_announcement",
    "enforcement",
    "prosecution",
    "hacked_flag",
    "sec_documented_trade",
    "expected_return",
    "target_price",
    "position_size",
    "trade_direction",
)

PROHIBITED_OUTPUTS = [
    "BUY",
    "SELL",
    "LONG/SHORT recommendation",
    "expected return",
    "target price",
    "position size",
    "order instruction",
]

STATUS_RANK = {"insufficient": 0, "partial": 1, "full": 2}


@dataclass(frozen=True)
class TrainingSample:
    sample_id: str
    event_id: str
    group_issuer: str
    symbol: str
    minute_ts_utc: str
    event_year: int
    label: int
    sample_role: str
    feature_status: str


@dataclass(frozen=True)
class HoldoutScore:
    sample_id: str
    event_id: str
    group_issuer: str
    symbol: str
    minute_ts_utc: str
    event_year: int
    label: int
    sample_role: str
    surveillance_risk_score: str
    flag_at_dev_threshold: int
    research_use_only: int = 1


def _clean(v: str | None) -> str:
    return (v or "").strip()


def _parse_ts(v: str) -> datetime:
    v = _clean(v)
    if not v:
        raise ValueError("blank timestamp")
    dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"timestamp must include timezone: {v!r}")
    return dt.astimezone(timezone.utc)


def _ts_key(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_float(v: str | None) -> float:
    v = _clean(v)
    if not v:
        return math.nan
    try:
        out = float(v)
    except Exception as exc:
        raise ValueError(f"invalid feature value {v!r}") from exc
    if not math.isfinite(out):
        raise ValueError(f"non-finite feature value {v!r}")
    return out


def _fmt(v: float | None, digits: int = 10) -> str:
    if v is None or not math.isfinite(v):
        return ""
    return (f"{v:.{digits}f}").rstrip("0").rstrip(".")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_feature_schema(fieldnames: Iterable[str], selected_features: Iterable[str] = DEFAULT_FEATURES) -> tuple[str, ...]:
    names = tuple(fieldnames)
    lower = [n.lower() for n in names]
    for raw, low in zip(names, lower):
        if any(term in low for term in FORBIDDEN_INPUT_TERMS):
            raise ValueError(f"forbidden/lookahead field in feature file: {raw}")
    selected = tuple(selected_features)
    missing = [f for f in selected if f not in names]
    if missing:
        raise ValueError(f"feature file missing selected features: {missing}")
    return selected


def load_feature_vectors(path: Path, *, min_status: str = "partial", selected_features: Iterable[str] = DEFAULT_FEATURES):
    if min_status not in STATUS_RANK:
        raise ValueError(f"invalid min_status={min_status!r}")
    out: dict[tuple[str, str], dict] = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {"minute_ts_utc", "symbol", "feature_status"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"feature file missing required columns: {sorted(missing)}")
        selected = validate_feature_schema(reader.fieldnames or [], selected_features)
        for i, row in enumerate(reader, 2):
            symbol = _clean(row.get("symbol")).upper()
            dt = _parse_ts(row.get("minute_ts_utc", ""))
            status = _clean(row.get("feature_status")).lower()
            if not symbol or status not in STATUS_RANK:
                raise ValueError(f"feature row {i}: invalid symbol/status")
            if STATUS_RANK[status] < STATUS_RANK[min_status]:
                continue
            key = (symbol, _ts_key(dt))
            if key in out:
                raise ValueError(f"duplicate feature vector for {key}")
            out[key] = {
                "symbol": symbol,
                "minute_ts_utc": key[1],
                "feature_status": status,
                "values": np.array([_parse_float(row.get(name)) for name in selected], dtype=float),
            }
    return out, selected


def load_matched_controls(path: Path) -> list[dict]:
    out = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {
            "event_id", "treated_symbol", "treated_minute_ts_utc",
            "control_symbol", "control_minute_ts_utc",
        }
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"matched-control file missing columns: {sorted(missing)}")
        for i, row in enumerate(reader, 2):
            event_id = _clean(row.get("event_id"))
            treated = _clean(row.get("treated_symbol")).upper()
            control = _clean(row.get("control_symbol")).upper()
            tts = _ts_key(_parse_ts(row.get("treated_minute_ts_utc", "")))
            cts = _ts_key(_parse_ts(row.get("control_minute_ts_utc", "")))
            if not event_id or not treated or not control or treated == control:
                raise ValueError(f"matched-control row {i}: invalid ids/symbols")
            out.append({
                **row,
                "event_id": event_id,
                "treated_symbol": treated,
                "control_symbol": control,
                "treated_minute_ts_utc": tts,
                "control_minute_ts_utc": cts,
            })
    if not out:
        raise ValueError("matched-control file contains no rows")
    return out


def build_samples(matches: list[dict], features: dict[tuple[str, str], dict]):
    samples: list[TrainingSample] = []
    X: list[np.ndarray] = []
    seen_positive: set[str] = set()
    seen_control_ids: set[str] = set()

    for row in matches:
        event_id = row["event_id"]
        treated_symbol = row["treated_symbol"]
        treated_ts = row["treated_minute_ts_utc"]
        control_symbol = row["control_symbol"]
        control_ts = row["control_minute_ts_utc"]
        year = _parse_ts(treated_ts).year

        if event_id not in seen_positive:
            fv = features.get((treated_symbol, treated_ts))
            if fv is None:
                raise ValueError(f"missing treated feature vector for event {event_id}: {treated_symbol} {treated_ts}")
            samples.append(TrainingSample(
                sample_id=f"{event_id}:TREATED",
                event_id=event_id,
                group_issuer=treated_symbol,
                symbol=treated_symbol,
                minute_ts_utc=treated_ts,
                event_year=year,
                label=1,
                sample_role="treated",
                feature_status=fv["feature_status"],
            ))
            X.append(fv["values"])
            seen_positive.add(event_id)

        cid = _clean(row.get("match_id")) or f"{event_id}:{control_symbol}:{control_ts}"
        if cid in seen_control_ids:
            raise ValueError(f"duplicate control sample id {cid}")
        fv = features.get((control_symbol, control_ts))
        if fv is None:
            raise ValueError(f"missing control feature vector for event {event_id}: {control_symbol} {control_ts}")
        samples.append(TrainingSample(
            sample_id=f"{event_id}:CONTROL:{cid}",
            event_id=event_id,
            group_issuer=treated_symbol,  # controls travel with their treated issuer during CV
            symbol=control_symbol,
            minute_ts_utc=control_ts,
            event_year=year,
            label=0,
            sample_role="matched_control",
            feature_status=fv["feature_status"],
        ))
        X.append(fv["values"])
        seen_control_ids.add(cid)

    if not samples:
        raise ValueError("no training samples constructed")
    return samples, np.vstack(X)


def split_temporal(samples: list[TrainingSample], X: np.ndarray, holdout_start_year: int = 2015):
    years = np.array([s.event_year for s in samples])
    dev_idx = np.flatnonzero(years < holdout_start_year)
    test_idx = np.flatnonzero(years >= holdout_start_year)
    if len(dev_idx) == 0 or len(test_idx) == 0:
        raise ValueError("temporal split requires both development and holdout samples")
    return dev_idx, test_idx


def _make_models(seed: int):
    elastic = Pipeline([
        ("imputer", SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True)),
        ("scaler", StandardScaler()),
        ("model", LogisticRegression(
            solver="saga", l1_ratio=0.25, C=0.5,
            class_weight="balanced", max_iter=5000, random_state=seed,
        )),
    ])
    boosted = Pipeline([
        ("imputer", SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True)),
        ("model", HistGradientBoostingClassifier(
            max_depth=3, max_iter=160, learning_rate=0.05,
            l2_regularization=1.0, class_weight="balanced", random_state=seed,
        )),
    ])
    return elastic, boosted


def _valid_fold_count(groups: np.ndarray, requested: int) -> int:
    n = len(set(groups.tolist()))
    folds = min(requested, n)
    if folds < 2:
        raise ValueError("at least two unique treated issuers are required for grouped CV")
    return folds


def generate_oof_predictions(X: np.ndarray, y: np.ndarray, groups: np.ndarray, *, cv_folds: int = 4, seed: int = 17):
    folds = _valid_fold_count(groups, cv_folds)
    splitter = StratifiedGroupKFold(n_splits=folds, shuffle=True, random_state=seed)
    oof_elastic = np.full(len(y), np.nan)
    oof_boosted = np.full(len(y), np.nan)
    audit = []

    for fold, (tr, va) in enumerate(splitter.split(X, y, groups), start=1):
        tr_groups = set(groups[tr].tolist())
        va_groups = set(groups[va].tolist())
        overlap = sorted(tr_groups.intersection(va_groups))
        if overlap:
            raise AssertionError(f"group leakage in fold {fold}: {overlap}")
        if len(set(y[tr].tolist())) < 2 or len(set(y[va].tolist())) < 2:
            raise ValueError(f"fold {fold} lacks both classes")

        elastic, boosted = _make_models(seed + fold)
        elastic.fit(X[tr], y[tr])
        boosted.fit(X[tr], y[tr])
        oof_elastic[va] = elastic.predict_proba(X[va])[:, 1]
        oof_boosted[va] = boosted.predict_proba(X[va])[:, 1]
        audit.append({
            "fold": fold,
            "train_rows": int(len(tr)),
            "validation_rows": int(len(va)),
            "train_group_count": len(tr_groups),
            "validation_group_count": len(va_groups),
            "group_overlap_count": 0,
            "validation_positive_count": int(y[va].sum()),
            "validation_negative_count": int((1 - y[va]).sum()),
        })

    if np.isnan(oof_elastic).any() or np.isnan(oof_boosted).any():
        raise AssertionError("OOF prediction coverage is incomplete")
    return oof_elastic, oof_boosted, audit


def fit_calibrator(y: np.ndarray, blended_scores: np.ndarray):
    if len(set(y.tolist())) < 2:
        raise ValueError("calibration requires both classes")
    calibrator = LogisticRegression(solver="lbfgs", C=1e6, max_iter=1000)
    calibrator.fit(blended_scores.reshape(-1, 1), y)
    return calibrator


def calibrate(calibrator, raw_scores: np.ndarray) -> np.ndarray:
    return calibrator.predict_proba(np.asarray(raw_scores).reshape(-1, 1))[:, 1]


def choose_threshold(y: np.ndarray, scores: np.ndarray, target_fpr: float = 0.05) -> tuple[float, dict]:
    if not (0 <= target_fpr < 1):
        raise ValueError("target_fpr must be in [0,1)")
    candidates = sorted(set(float(x) for x in scores), reverse=True)
    candidates = [math.nextafter(max(candidates), math.inf)] + candidates
    best = None
    for threshold in candidates:
        pred = scores >= threshold
        neg = y == 0
        pos = y == 1
        fp = int(np.sum(pred & neg))
        tn = int(np.sum((~pred) & neg))
        tp = int(np.sum(pred & pos))
        fn = int(np.sum((~pred) & pos))
        fpr = fp / (fp + tn) if fp + tn else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        if fpr <= target_fpr + 1e-12:
            item = (rec, -threshold, threshold, fpr, fp, tp)
            if best is None or item > best:
                best = item
    if best is None:
        raise AssertionError("no valid threshold candidate")
    return float(best[2]), {
        "target_fpr": target_fpr,
        "development_recall": best[0],
        "development_fpr": best[3],
        "development_false_positives": best[4],
        "development_true_positives": best[5],
    }


def evaluate(y: np.ndarray, scores: np.ndarray, threshold: float) -> dict:
    y = np.asarray(y, dtype=int)
    scores = np.asarray(scores, dtype=float)
    out = {
        "n": int(len(y)),
        "positives": int(y.sum()),
        "negatives": int((1 - y).sum()),
    }
    if len(y) == 0 or len(set(y.tolist())) < 2:
        out.update({
            "average_precision": None,
            "roc_auc": None,
            "brier": None,
            "log_loss": None,
        })
    else:
        clipped = np.clip(scores, 1e-9, 1 - 1e-9)
        out.update({
            "average_precision": float(average_precision_score(y, scores)),
            "roc_auc": float(roc_auc_score(y, scores)),
            "brier": float(brier_score_loss(y, scores)),
            "log_loss": float(log_loss(y, clipped, labels=[0, 1])),
        })
    pred = scores >= threshold
    neg = y == 0
    pos = y == 1
    fp = int(np.sum(pred & neg))
    tn = int(np.sum((~pred) & neg))
    tp = int(np.sum(pred & pos))
    fn = int(np.sum((~pred) & pos))
    out.update({
        "threshold": float(threshold),
        "recall_at_threshold": tp / (tp + fn) if tp + fn else None,
        "false_positive_rate": fp / (fp + tn) if fp + tn else None,
        "alerts_per_100_matched_controls": 100.0 * fp / (fp + tn) if fp + tn else None,
        "true_positives": tp,
        "false_positives": fp,
    })
    return out


def _elastic_coefficients(elastic: Pipeline, selected_features: tuple[str, ...]) -> list[dict]:
    imputer = elastic.named_steps["imputer"]
    scaler = elastic.named_steps["scaler"]
    model = elastic.named_steps["model"]
    base_names = list(imputer.get_feature_names_out(selected_features))
    if len(base_names) != len(model.coef_[0]):
        # Scaler preserves dimensions; this should never differ.
        raise AssertionError("coefficient name/shape mismatch")
    return sorted(
        ({"feature": n, "coefficient": float(c)} for n, c in zip(base_names, model.coef_[0])),
        key=lambda r: abs(r["coefficient"]),
        reverse=True,
    )


def _write_dataclass_csv(path: Path, rows: list) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[x.name for x in fields(rows[0])])
        writer.writeheader()
        for row in rows:
            writer.writerow({x.name: getattr(row, x.name) for x in fields(row)})


def _write_dict_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def train(
    *,
    matched_controls: Path,
    feature_vectors: Path,
    output_dir: Path,
    holdout_start_year: int = 2015,
    target_fpr: float = 0.05,
    cv_folds: int = 4,
    seed: int = 17,
    min_status: str = "partial",
    selected_features: Iterable[str] = DEFAULT_FEATURES,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    features, selected = load_feature_vectors(
        feature_vectors, min_status=min_status, selected_features=selected_features
    )
    matches = load_matched_controls(matched_controls)
    samples, X = build_samples(matches, features)
    y = np.array([s.label for s in samples], dtype=int)
    groups = np.array([s.group_issuer for s in samples], dtype=object)
    dev_idx, holdout_idx = split_temporal(samples, X, holdout_start_year)

    X_dev, y_dev, groups_dev = X[dev_idx], y[dev_idx], groups[dev_idx]
    X_hold, y_hold = X[holdout_idx], y[holdout_idx]

    oof_a, oof_b, cv_audit = generate_oof_predictions(
        X_dev, y_dev, groups_dev, cv_folds=cv_folds, seed=seed
    )
    oof_blend = 0.5 * oof_a + 0.5 * oof_b
    calibrator = fit_calibrator(y_dev, oof_blend)
    oof_cal = calibrate(calibrator, oof_blend)
    threshold, threshold_diag = choose_threshold(y_dev, oof_cal, target_fpr=target_fpr)

    elastic, boosted = _make_models(seed)
    elastic.fit(X_dev, y_dev)
    boosted.fit(X_dev, y_dev)
    hold_a = elastic.predict_proba(X_hold)[:, 1]
    hold_b = boosted.predict_proba(X_hold)[:, 1]
    hold_raw = 0.5 * hold_a + 0.5 * hold_b
    hold_cal = calibrate(calibrator, hold_raw)

    dev_metrics = evaluate(y_dev, oof_cal, threshold)
    hold_metrics = evaluate(y_hold, hold_cal, threshold)

    dev_issuers = set(groups_dev.tolist())
    unseen_mask = np.array([samples[i].group_issuer not in dev_issuers for i in holdout_idx], dtype=bool)
    unseen_metrics = evaluate(y_hold[unseen_mask], hold_cal[unseen_mask], threshold) if unseen_mask.any() else {
        "n": 0, "positives": 0, "negatives": 0,
        "average_precision": None, "roc_auc": None, "brier": None, "log_loss": None,
        "threshold": threshold, "recall_at_threshold": None, "false_positive_rate": None,
        "alerts_per_100_matched_controls": None, "true_positives": 0, "false_positives": 0,
    }

    scores: list[HoldoutScore] = []
    for idx, score in zip(holdout_idx, hold_cal):
        s = samples[idx]
        scores.append(HoldoutScore(
            sample_id=s.sample_id,
            event_id=s.event_id,
            group_issuer=s.group_issuer,
            symbol=s.symbol,
            minute_ts_utc=s.minute_ts_utc,
            event_year=s.event_year,
            label=s.label,
            sample_role=s.sample_role,
            surveillance_risk_score=_fmt(100.0 * float(score), 6),
            flag_at_dev_threshold=int(score >= threshold),
        ))
    _write_dataclass_csv(output_dir / "holdout_scores.csv", scores)

    coeffs = _elastic_coefficients(elastic, selected)
    _write_dict_csv(output_dir / "elastic_net_coefficients.csv", coeffs, ["feature", "coefficient"])
    (output_dir / "cv_split_audit.json").write_text(json.dumps(cv_audit, indent=2), encoding="utf-8")

    bundle = {
        "schema_version": SCHEMA_VERSION,
        "selected_features": selected,
        "elastic_net": elastic,
        "boosted_model": boosted,
        "calibrator": calibrator,
        "blend_weights": (0.5, 0.5),
        "surveillance_threshold": threshold,
        "holdout_start_year": holdout_start_year,
        "research_use_only": True,
    }
    joblib.dump(bundle, output_dir / "model_bundle.joblib")

    # Calibration bins are diagnostic only and use development OOF predictions.
    try:
        frac_pos, mean_pred = calibration_curve(y_dev, oof_cal, n_bins=5, strategy="quantile")
        cal_rows = [
            {"mean_predicted_probability": _fmt(float(p), 8), "observed_positive_fraction": _fmt(float(o), 8)}
            for p, o in zip(mean_pred, frac_pos)
        ]
    except Exception:
        cal_rows = []
    _write_dict_csv(
        output_dir / "development_calibration.csv", cal_rows,
        ["mean_predicted_probability", "observed_positive_fraction"],
    )

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "purpose": "historical informed-trading market-surveillance research",
        "research_use_only": True,
        "inputs": {
            "matched_controls": str(matched_controls),
            "matched_controls_sha256": _sha256(matched_controls),
            "feature_vectors": str(feature_vectors),
            "feature_vectors_sha256": _sha256(feature_vectors),
        },
        "feature_policy": {
            "selected_features": list(selected),
            "lookahead_fields_rejected": True,
            "future_prices_rejected": True,
            "future_earnings_information_rejected": True,
            "enforcement_outcomes_rejected_as_features": True,
        },
        "validation_policy": {
            "holdout_start_year": holdout_start_year,
            "development_years": sorted(set(s.event_year for i, s in enumerate(samples) if i in set(dev_idx.tolist()))),
            "holdout_years": sorted(set(s.event_year for i, s in enumerate(samples) if i in set(holdout_idx.tolist()))),
            "grouping_unit": "treated issuer; treated event and matched controls stay together",
            "cv_folds": len(cv_audit),
            "cv_group_overlap_count": sum(x["group_overlap_count"] for x in cv_audit),
            "unseen_issuer_holdout_rows": int(unseen_mask.sum()),
        },
        "model": {
            "elastic_net": "median imputation + missing indicators + standardization + elastic-net logistic regression",
            "boosted": "median imputation + missing indicators + shallow histogram gradient boosting",
            "blend_weights": [0.5, 0.5],
            "calibration": "Platt/logistic calibration fit only on grouped out-of-fold development predictions",
            "threshold_selection": "chosen only on development OOF predictions at configured false-positive-rate ceiling",
            "target_fpr": target_fpr,
            "selected_threshold": threshold,
            "threshold_diagnostics": threshold_diag,
        },
        "sample_counts": {
            "total": len(samples),
            "development": int(len(dev_idx)),
            "holdout": int(len(holdout_idx)),
            "development_positive": int(y_dev.sum()),
            "development_negative": int((1 - y_dev).sum()),
            "holdout_positive": int(y_hold.sum()),
            "holdout_negative": int((1 - y_hold).sum()),
            "unique_treated_issuers_development": len(set(groups_dev.tolist())),
        },
        "metrics": {
            "development_oof": dev_metrics,
            "temporal_holdout": hold_metrics,
            "temporal_holdout_unseen_treated_issuers": unseen_metrics,
        },
        "outputs": {
            "model_bundle": "model_bundle.joblib",
            "holdout_scores": "holdout_scores.csv",
            "elastic_net_coefficients": "elastic_net_coefficients.csv",
            "development_calibration": "development_calibration.csv",
            "cv_split_audit": "cv_split_audit.json",
        },
        "prohibited_outputs": PROHIBITED_OUTPUTS,
        "deployment_status": "offline research artifact; no market feed, broker, notification, or execution integration",
        "interpretation_warning": "A surveillance score is an anomaly-prioritization signal, not a probability that a crime occurred.",
    }
    (output_dir / "training_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def _args():
    p = argparse.ArgumentParser(description="Train offline historical market-surveillance detector")
    p.add_argument("--matched-controls", type=Path, required=True)
    p.add_argument("--feature-vectors", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--holdout-start-year", type=int, default=2015)
    p.add_argument("--target-fpr", type=float, default=0.05)
    p.add_argument("--cv-folds", type=int, default=4)
    p.add_argument("--seed", type=int, default=17)
    p.add_argument("--min-status", choices=sorted(STATUS_RANK), default="partial")
    return p.parse_args()


if __name__ == "__main__":
    args = _args()
    result = train(
        matched_controls=args.matched_controls,
        feature_vectors=args.feature_vectors,
        output_dir=args.output_dir,
        holdout_start_year=args.holdout_start_year,
        target_fpr=args.target_fpr,
        cv_folds=args.cv_folds,
        seed=args.seed,
        min_status=args.min_status,
    )
    print(json.dumps(result, indent=2))
