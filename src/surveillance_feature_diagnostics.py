from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from model_training_harness import DEFAULT_FEATURES, FORBIDDEN_INPUT_TERMS

SCHEMA_VERSION = "1.0.0"
PROHIBITED_OUTPUTS = [
    "BUY", "SELL", "expected_return", "target_price", "position_size",
    "order", "execution_instruction", "trade_direction",
]


def _clean(v: str | None) -> str:
    return (v or "").strip()


def _parse_ts(v: str) -> datetime:
    value = _clean(v)
    if not value:
        raise ValueError("blank timestamp")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return dt.astimezone(timezone.utc)


def _ts_key(v: str) -> str:
    return _parse_ts(v).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _float(v: str | None) -> float:
    value = _clean(v)
    if not value:
        return math.nan
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"non-finite numeric value: {value!r}")
    return out


def _fmt(v: float | None, digits: int = 8) -> str:
    if v is None or not math.isfinite(v):
        return ""
    return (f"{v:.{digits}f}").rstrip("0").rstrip(".")


def _safe_div(a: float, b: float) -> float | None:
    if b == 0:
        return None
    return a / b


def _rank_auc(y: np.ndarray, scores: np.ndarray) -> float | None:
    pos = scores[y == 1]
    neg = scores[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return None
    wins = 0.0
    for p in pos:
        wins += float(np.sum(p > neg)) + 0.5 * float(np.sum(p == neg))
    return wins / (len(pos) * len(neg))


def _average_precision(y: np.ndarray, scores: np.ndarray) -> float | None:
    positives = int(np.sum(y == 1))
    if positives == 0:
        return None
    order = np.argsort(-scores, kind="mergesort")
    ys = y[order]
    tp = 0
    total = 0.0
    for rank, label in enumerate(ys, 1):
        if label == 1:
            tp += 1
            total += tp / rank
    return total / positives


def _score_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"sample_count": 0}
    y = np.array([int(r["label"]) for r in rows], dtype=int)
    s = np.array([float(r["score"]) for r in rows], dtype=float)
    flags = np.array([int(r["flag"]) for r in rows], dtype=int)
    tp = int(np.sum((y == 1) & (flags == 1)))
    fp = int(np.sum((y == 0) & (flags == 1)))
    tn = int(np.sum((y == 0) & (flags == 0)))
    fn = int(np.sum((y == 1) & (flags == 0)))
    return {
        "sample_count": len(rows),
        "positive_count": int(np.sum(y == 1)),
        "negative_count": int(np.sum(y == 0)),
        "prevalence": round(float(np.mean(y)), 8),
        "roc_auc": None if _rank_auc(y, s) is None else round(float(_rank_auc(y, s)), 8),
        "average_precision": None if _average_precision(y, s) is None else round(float(_average_precision(y, s)), 8),
        "brier": round(float(np.mean((s - y) ** 2)), 8),
        "flagged_rate": round(float(np.mean(flags)), 8),
        "true_positive_rate": None if tp + fn == 0 else round(tp / (tp + fn), 8),
        "false_positive_rate": None if fp + tn == 0 else round(fp / (fp + tn), 8),
        "precision": None if tp + fp == 0 else round(tp / (tp + fp), 8),
    }


def load_evaluation_rows(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {
            "sample_id", "case_id", "case_family", "mechanism", "symbol",
            "minute_ts_utc", "label", "surveillance_risk_score",
            "flag_at_frozen_threshold", "research_use_only",
        }
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"evaluation rows missing columns: {sorted(missing)}")
        seen: set[str] = set()
        for i, row in enumerate(reader, 2):
            sid = _clean(row.get("sample_id"))
            if not sid or sid in seen:
                raise ValueError(f"evaluation row {i}: missing/duplicate sample_id")
            label = _clean(row.get("label"))
            if label not in {"0", "1"}:
                raise ValueError(f"evaluation row {i}: label must be 0/1")
            if _clean(row.get("research_use_only")).lower() not in {"1", "true"}:
                raise ValueError(f"evaluation row {i}: research_use_only must be true")
            score = _float(row.get("surveillance_risk_score")) / 100.0
            if not 0.0 <= score <= 1.0:
                raise ValueError(f"evaluation row {i}: surveillance score outside [0,100]")
            flag = int(_clean(row.get("flag_at_frozen_threshold")))
            if flag not in {0, 1}:
                raise ValueError(f"evaluation row {i}: invalid flag")
            ts = _ts_key(row.get("minute_ts_utc", ""))
            out.append({
                "sample_id": sid,
                "case_id": _clean(row.get("case_id")),
                "case_family": _clean(row.get("case_family")).lower(),
                "mechanism": _clean(row.get("mechanism")).lower(),
                "symbol": _clean(row.get("symbol")).upper(),
                "minute_ts_utc": ts,
                "year": _parse_ts(ts).year,
                "label": int(label),
                "score": score,
                "flag": flag,
            })
            seen.add(sid)
    if not out:
        raise ValueError("evaluation rows contain no samples")
    return out


def load_feature_rows(
    path: Path,
    *,
    selected_features: Iterable[str] = DEFAULT_FEATURES,
) -> tuple[dict[tuple[str, str], dict[str, Any]], tuple[str, ...]]:
    selected = tuple(selected_features)
    if not selected:
        raise ValueError("selected_features cannot be empty")
    for feature in selected:
        low = feature.lower()
        if any(term in low for term in FORBIDDEN_INPUT_TERMS):
            raise ValueError(f"forbidden/lookahead feature selected: {feature}")
    out: dict[tuple[str, str], dict[str, Any]] = {}
    with Path(path).open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        names = tuple(reader.fieldnames or [])
        required = {"symbol", "minute_ts_utc", *selected}
        missing = required.difference(names)
        if missing:
            raise ValueError(f"feature rows missing columns: {sorted(missing)}")
        for raw in names:
            low = raw.lower()
            if any(term in low for term in FORBIDDEN_INPUT_TERMS):
                raise ValueError(f"forbidden/lookahead feature field: {raw}")
        relative_field = "relative_minute" if "relative_minute" in names else (
            "minutes_to_event" if "minutes_to_event" in names else None
        )
        for i, row in enumerate(reader, 2):
            symbol = _clean(row.get("symbol")).upper()
            ts = _ts_key(row.get("minute_ts_utc", ""))
            if not symbol:
                raise ValueError(f"feature row {i}: blank symbol")
            key = (symbol, ts)
            if key in out:
                raise ValueError(f"duplicate feature vector for {key}")
            values = {name: _float(row.get(name)) for name in selected}
            rel = None
            if relative_field and _clean(row.get(relative_field)):
                rel = int(float(_clean(row.get(relative_field))))
            out[key] = {"values": values, "relative_minute": rel}
    if not out:
        raise ValueError("feature rows contain no vectors")
    return out, selected


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def _join(
    evaluation: list[dict[str, Any]],
    feature_index: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    joined: list[dict[str, Any]] = []
    for row in evaluation:
        key = (row["symbol"], row["minute_ts_utc"])
        fv = feature_index.get(key)
        if fv is None:
            raise ValueError(f"missing feature vector for evaluation sample {row['sample_id']}: {key}")
        joined.append({**row, **fv})
    return joined


def _quantile_rows(joined: list[dict[str, Any]], features: tuple[str, ...], q: int) -> list[dict[str, Any]]:
    if q < 2 or q > 20:
        raise ValueError("quantiles must be between 2 and 20")
    prevalence = sum(r["label"] for r in joined) / len(joined)
    out: list[dict[str, Any]] = []
    for feature in features:
        valid = [(idx, r["values"][feature]) for idx, r in enumerate(joined) if math.isfinite(r["values"][feature])]
        if not valid:
            continue
        ordered = sorted(valid, key=lambda item: (item[1], joined[item[0]]["sample_id"]))
        bins: dict[int, list[tuple[int, float]]] = defaultdict(list)
        n = len(ordered)
        for rank, item in enumerate(ordered):
            bin_no = min(q, (rank * q) // n + 1)
            bins[bin_no].append(item)
        for bin_no in range(1, q + 1):
            items = bins.get(bin_no, [])
            if not items:
                continue
            labels = [joined[i]["label"] for i, _ in items]
            rate = sum(labels) / len(labels)
            vals = [v for _, v in items]
            out.append({
                "feature": feature,
                "quantile": bin_no,
                "sample_count": len(items),
                "mean_feature_value": _fmt(float(np.mean(vals))),
                "positive_rate": _fmt(rate),
                "lift_vs_overall_prevalence": _fmt(_safe_div(rate, prevalence)),
            })
    return out


def _stability_rows(
    joined: list[dict[str, Any]],
    features: tuple[str, ...],
    *,
    dimension: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    values = sorted({r[dimension] for r in joined})
    for feature in features:
        for value in values:
            rows = [r for r in joined if r[dimension] == value and math.isfinite(r["values"][feature])]
            if not rows:
                continue
            pos = [r["values"][feature] for r in rows if r["label"] == 1]
            neg = [r["values"][feature] for r in rows if r["label"] == 0]
            pos_mean = float(np.mean(pos)) if pos else None
            neg_mean = float(np.mean(neg)) if neg else None
            separation = None if pos_mean is None or neg_mean is None else pos_mean - neg_mean
            out.append({
                "feature": feature,
                dimension: value,
                "sample_count": len(rows),
                "positive_count": len(pos),
                "negative_count": len(neg),
                "positive_mean": _fmt(pos_mean),
                "negative_mean": _fmt(neg_mean),
                "positive_minus_negative": _fmt(separation),
            })
    return out


def _decay_rows(joined: list[dict[str, Any]], features: tuple[str, ...]) -> list[dict[str, Any]]:
    if not any(r["relative_minute"] is not None for r in joined):
        return []
    raw: list[dict[str, Any]] = []
    by_feature: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for feature in features:
        minutes = sorted({r["relative_minute"] for r in joined if r["relative_minute"] is not None})
        for minute in minutes:
            rows = [
                r for r in joined
                if r["relative_minute"] == minute and math.isfinite(r["values"][feature])
            ]
            pos = [r["values"][feature] for r in rows if r["label"] == 1]
            neg = [r["values"][feature] for r in rows if r["label"] == 0]
            if not pos or not neg:
                continue
            sep = float(np.mean(pos) - np.mean(neg))
            rec = {
                "feature": feature,
                "relative_minute": minute,
                "sample_count": len(rows),
                "positive_minus_negative": sep,
                "absolute_separation": abs(sep),
            }
            raw.append(rec)
            by_feature[feature].append(rec)
    out: list[dict[str, Any]] = []
    for rec in raw:
        peak = max((x["absolute_separation"] for x in by_feature[rec["feature"]]), default=0.0)
        out.append({
            "feature": rec["feature"],
            "relative_minute": rec["relative_minute"],
            "sample_count": rec["sample_count"],
            "positive_minus_negative": _fmt(rec["positive_minus_negative"]),
            "absolute_separation": _fmt(rec["absolute_separation"]),
            "fraction_of_peak_absolute_separation": _fmt(_safe_div(rec["absolute_separation"], peak)),
        })
    return out


def _redundancy_rows(
    joined: list[dict[str, Any]],
    features: tuple[str, ...],
    threshold: float,
) -> list[dict[str, Any]]:
    if not 0 < threshold <= 1:
        raise ValueError("redundancy_threshold must be in (0,1]")
    out: list[dict[str, Any]] = []
    for i, left in enumerate(features):
        for right in features[i + 1:]:
            pairs = [
                (r["values"][left], r["values"][right]) for r in joined
                if math.isfinite(r["values"][left]) and math.isfinite(r["values"][right])
            ]
            corr = None
            if len(pairs) >= 3:
                x = np.array([a for a, _ in pairs], dtype=float)
                y = np.array([b for _, b in pairs], dtype=float)
                if float(np.std(x)) > 0 and float(np.std(y)) > 0:
                    corr = float(np.corrcoef(x, y)[0, 1])
            out.append({
                "feature_a": left,
                "feature_b": right,
                "sample_count": len(pairs),
                "pearson_correlation": _fmt(corr),
                "absolute_correlation": _fmt(None if corr is None else abs(corr)),
                "high_redundancy": int(corr is not None and abs(corr) >= threshold),
            })
    return out


def _score_report(joined: list[dict[str, Any]]) -> dict[str, Any]:
    by_family = {
        family: _score_metrics([r for r in joined if r["case_family"] == family])
        for family in sorted({r["case_family"] for r in joined})
    }
    by_year = {
        str(year): _score_metrics([r for r in joined if r["year"] == year])
        for year in sorted({r["year"] for r in joined})
    }
    by_mechanism = {
        mech: _score_metrics([r for r in joined if r["mechanism"] == mech])
        for mech in sorted({r["mechanism"] for r in joined})
    }
    return {
        "overall": _score_metrics(joined),
        "by_case_family": by_family,
        "by_year": by_year,
        "by_mechanism": by_mechanism,
    }


def build_diagnostics(
    *,
    evaluation_rows: Path,
    feature_vectors: Path,
    output_dir: Path,
    selected_features: Iterable[str] = DEFAULT_FEATURES,
    quantiles: int = 5,
    redundancy_threshold: float = 0.90,
) -> dict[str, Any]:
    evaluation = load_evaluation_rows(evaluation_rows)
    feature_index, features = load_feature_rows(feature_vectors, selected_features=selected_features)
    joined = _join(evaluation, feature_index)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    quantile = _quantile_rows(joined, features, quantiles)
    temporal = _stability_rows(joined, features, dimension="year")
    cohort = _stability_rows(joined, features, dimension="case_family")
    decay = _decay_rows(joined, features)
    redundancy = _redundancy_rows(joined, features, redundancy_threshold)
    score_report = _score_report(joined)

    _write_csv(
        output_dir / "feature_quantile_lift.csv",
        ["feature","quantile","sample_count","mean_feature_value","positive_rate","lift_vs_overall_prevalence"],
        quantile,
    )
    _write_csv(
        output_dir / "feature_temporal_stability.csv",
        ["feature","year","sample_count","positive_count","negative_count","positive_mean","negative_mean","positive_minus_negative"],
        temporal,
    )
    _write_csv(
        output_dir / "feature_cohort_stability.csv",
        ["feature","case_family","sample_count","positive_count","negative_count","positive_mean","negative_mean","positive_minus_negative"],
        cohort,
    )
    _write_csv(
        output_dir / "feature_decay.csv",
        ["feature","relative_minute","sample_count","positive_minus_negative","absolute_separation","fraction_of_peak_absolute_separation"],
        decay,
    )
    _write_csv(
        output_dir / "feature_redundancy.csv",
        ["feature_a","feature_b","sample_count","pearson_correlation","absolute_correlation","high_redundancy"],
        redundancy,
    )
    (output_dir / "surveillance_score_diagnostics.json").write_text(
        json.dumps(score_report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "purpose": "offline surveillance feature and frozen-score diagnostics",
        "research_use_only": True,
        "sample_count": len(joined),
        "selected_features": list(features),
        "quantiles": quantiles,
        "redundancy_threshold": redundancy_threshold,
        "decay_status": "AVAILABLE" if decay else "NOT_AVAILABLE_NO_RELATIVE_MINUTE_INPUT",
        "inputs": {
            "evaluation_rows": str(evaluation_rows),
            "evaluation_rows_sha256": _sha256(Path(evaluation_rows)),
            "feature_vectors": str(feature_vectors),
            "feature_vectors_sha256": _sha256(Path(feature_vectors)),
        },
        "outputs": {
            "feature_quantile_lift": "feature_quantile_lift.csv",
            "feature_temporal_stability": "feature_temporal_stability.csv",
            "feature_cohort_stability": "feature_cohort_stability.csv",
            "feature_decay": "feature_decay.csv",
            "feature_redundancy": "feature_redundancy.csv",
            "surveillance_score_diagnostics": "surveillance_score_diagnostics.json",
        },
        "architecture_origin": {
            "concepts": [
                "factor quantile analysis", "temporal stability", "cohort stability",
                "signal decay", "feature redundancy", "risk/performance attribution",
            ],
            "inspiration": ["Alphalens", "Pyfolio", "ffn"],
            "third_party_source_copied_or_vendored": False,
        },
        "model_policy": {
            "retraining_performed": False,
            "threshold_tuning_performed": False,
            "diagnostics_may_not_promote_or_activate_a_model": True,
        },
        "prohibited_outputs": PROHIBITED_OUTPUTS,
        "interpretation_warning": "Diagnostics measure historical surveillance discrimination/stability only; they are not expected-return, trading, or evidence-of-intent metrics.",
    }
    (output_dir / "surveillance_feature_diagnostics_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def _args():
    p = argparse.ArgumentParser(description="Offline surveillance feature diagnostics")
    p.add_argument("--evaluation-rows", type=Path, required=True)
    p.add_argument("--feature-vectors", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--quantiles", type=int, default=5)
    p.add_argument("--redundancy-threshold", type=float, default=0.90)
    return p.parse_args()


if __name__ == "__main__":
    args = _args()
    print(json.dumps(build_diagnostics(
        evaluation_rows=args.evaluation_rows,
        feature_vectors=args.feature_vectors,
        output_dir=args.output_dir,
        quantiles=args.quantiles,
        redundancy_threshold=args.redundancy_threshold,
    ), indent=2))
