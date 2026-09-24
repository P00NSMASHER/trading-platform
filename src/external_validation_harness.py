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

from model_training_harness import (
    DEFAULT_FEATURES,
    FORBIDDEN_INPUT_TERMS,
    PROHIBITED_OUTPUTS,
    STATUS_RANK,
    calibrate,
    evaluate,
)

SCHEMA_VERSION = "0.7.0"

ALLOWED_FAMILIES = {
    "edgar_hack",
    "fda_regulatory",
    "cross_security",
    "ma_tip",
    "other_adjudicated",
    "synthetic_demo",
}

PROHIBITED_REGISTRY_FIELDS = {
    "label",
    "target",
    "class",
    "outcome",
    "future_price",
    "expected_return",
    "trade_direction",
    "position_size",
    "target_price",
}


@dataclass(frozen=True)
class ExternalScore:
    sample_id: str
    case_id: str
    case_family: str
    mechanism: str
    symbol: str
    minute_ts_utc: str
    surveillance_risk_score: str
    flag_at_frozen_threshold: int
    frozen_threshold: str
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


def _write_dataclass_csv(path: Path, rows: list) -> None:
    if not rows:
        raise ValueError("no rows to write")
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[x.name for x in fields(rows[0])])
        writer.writeheader()
        for row in rows:
            writer.writerow({x.name: getattr(row, x.name) for x in fields(row)})


def _write_dict_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def load_frozen_bundle(path: Path) -> dict:
    bundle = joblib.load(path)
    required = {
        "selected_features",
        "elastic_net",
        "boosted_model",
        "calibrator",
        "blend_weights",
        "surveillance_threshold",
        "research_use_only",
    }
    missing = required.difference(bundle)
    if missing:
        raise ValueError(f"model bundle missing fields: {sorted(missing)}")
    if bundle.get("research_use_only") is not True:
        raise ValueError("external validation requires a research-use-only frozen model bundle")
    selected = tuple(bundle["selected_features"])
    if not selected:
        raise ValueError("frozen bundle has no selected features")
    threshold = float(bundle["surveillance_threshold"])
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("frozen surveillance threshold must be in [0,1]")
    weights = tuple(float(x) for x in bundle["blend_weights"])
    if len(weights) != 2 or not math.isclose(sum(weights), 1.0, rel_tol=0, abs_tol=1e-9):
        raise ValueError("blend_weights must contain two values summing to 1")
    return bundle


def validate_registry_schema(fieldnames: Iterable[str]) -> None:
    names = {n.strip() for n in fieldnames}
    required = {
        "sample_id",
        "case_id",
        "case_family",
        "mechanism",
        "symbol",
        "minute_ts_utc",
        "adjudication_status",
        "source_reference",
        "research_use_only",
    }
    missing = required.difference(names)
    if missing:
        raise ValueError(f"external registry missing columns: {sorted(missing)}")
    lowered = {n.lower() for n in names}
    bad = sorted(lowered.intersection(PROHIBITED_REGISTRY_FIELDS))
    if bad:
        raise ValueError(f"blind scoring registry must not contain ground truth/outcome fields: {bad}")


def load_registry(path: Path) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        validate_registry_schema(reader.fieldnames or [])
        for i, row in enumerate(reader, 2):
            sample_id = _clean(row.get("sample_id"))
            case_id = _clean(row.get("case_id"))
            family = _clean(row.get("case_family")).lower()
            mechanism = _clean(row.get("mechanism")).lower()
            symbol = _clean(row.get("symbol")).upper()
            ts = _ts_key(_parse_ts(row.get("minute_ts_utc", "")))
            if not sample_id or sample_id in seen:
                raise ValueError(f"registry row {i}: missing/duplicate sample_id")
            if not case_id or not symbol or not mechanism:
                raise ValueError(f"registry row {i}: missing case_id/symbol/mechanism")
            if family not in ALLOWED_FAMILIES:
                raise ValueError(f"registry row {i}: unsupported case_family={family!r}")
            if _clean(row.get("adjudication_status")).lower() not in {
                "adjudicated", "charged", "settled", "guilty_plea", "jury_liability", "synthetic"
            }:
                raise ValueError(f"registry row {i}: invalid adjudication_status")
            if _clean(row.get("research_use_only")) not in {"1", "true", "True"}:
                raise ValueError(f"registry row {i}: research_use_only must be true")
            out.append({
                **row,
                "sample_id": sample_id,
                "case_id": case_id,
                "case_family": family,
                "mechanism": mechanism,
                "symbol": symbol,
                "minute_ts_utc": ts,
            })
            seen.add(sample_id)
    if not out:
        raise ValueError("external registry contains no rows")
    return out


def _parse_float(v: str | None) -> float:
    v = _clean(v)
    if not v:
        return math.nan
    out = float(v)
    if not math.isfinite(out):
        raise ValueError(f"non-finite feature value {v!r}")
    return out


def load_external_features(
    path: Path,
    *,
    selected_features: Iterable[str],
    min_status: str = "partial",
) -> dict[tuple[str, str], dict]:
    if min_status not in STATUS_RANK:
        raise ValueError(f"invalid min_status={min_status!r}")
    selected = tuple(selected_features)
    out: dict[tuple[str, str], dict] = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        names = tuple(reader.fieldnames or [])
        required = {"minute_ts_utc", "symbol", "feature_status"}
        missing = required.difference(names)
        if missing:
            raise ValueError(f"external feature file missing columns: {sorted(missing)}")
        for raw in names:
            low = raw.lower()
            if any(term in low for term in FORBIDDEN_INPUT_TERMS):
                raise ValueError(f"forbidden/lookahead field in external features: {raw}")
        feature_missing = [x for x in selected if x not in names]
        if feature_missing:
            raise ValueError(f"external feature file missing frozen-model features: {feature_missing}")
        for i, row in enumerate(reader, 2):
            symbol = _clean(row.get("symbol")).upper()
            ts = _ts_key(_parse_ts(row.get("minute_ts_utc", "")))
            status = _clean(row.get("feature_status")).lower()
            if not symbol or status not in STATUS_RANK:
                raise ValueError(f"feature row {i}: invalid symbol/status")
            if STATUS_RANK[status] < STATUS_RANK[min_status]:
                continue
            key = (symbol, ts)
            if key in out:
                raise ValueError(f"duplicate external feature vector for {key}")
            out[key] = {
                "feature_status": status,
                "values": np.array([_parse_float(row.get(x)) for x in selected], dtype=float),
            }
    return out


def score_external(
    *,
    model_bundle: Path,
    registry: Path,
    feature_vectors: Path,
    output_dir: Path,
    min_status: str = "partial",
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_hash_before = _sha256(model_bundle)
    bundle = load_frozen_bundle(model_bundle)
    selected = tuple(bundle["selected_features"])
    rows = load_registry(registry)
    features = load_external_features(
        feature_vectors, selected_features=selected, min_status=min_status
    )

    X: list[np.ndarray] = []
    retained: list[dict] = []
    for row in rows:
        key = (row["symbol"], row["minute_ts_utc"])
        fv = features.get(key)
        if fv is None:
            raise ValueError(f"missing external feature vector for {row['sample_id']}: {key}")
        X.append(fv["values"])
        retained.append(row)
    matrix = np.vstack(X)

    # IMPORTANT: validation-only path. No fit/partial_fit/threshold selection is performed here.
    elastic_scores = bundle["elastic_net"].predict_proba(matrix)[:, 1]
    boosted_scores = bundle["boosted_model"].predict_proba(matrix)[:, 1]
    w1, w2 = (float(x) for x in bundle["blend_weights"])
    raw = w1 * elastic_scores + w2 * boosted_scores
    calibrated = calibrate(bundle["calibrator"], raw)
    threshold = float(bundle["surveillance_threshold"])

    scores: list[ExternalScore] = []
    for row, score in zip(retained, calibrated):
        scores.append(ExternalScore(
            sample_id=row["sample_id"],
            case_id=row["case_id"],
            case_family=row["case_family"],
            mechanism=row["mechanism"],
            symbol=row["symbol"],
            minute_ts_utc=row["minute_ts_utc"],
            surveillance_risk_score=_fmt(100.0 * float(score), 6),
            flag_at_frozen_threshold=int(float(score) >= threshold),
            frozen_threshold=_fmt(threshold, 10),
        ))
    _write_dataclass_csv(output_dir / "external_scores.csv", scores)

    bundle_hash_after = _sha256(model_bundle)
    if bundle_hash_before != bundle_hash_after:
        raise AssertionError("frozen model bundle changed during external scoring")

    family_counts: dict[str, int] = {}
    for row in retained:
        family_counts[row["case_family"]] = family_counts.get(row["case_family"], 0) + 1

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "purpose": "blind external validation of frozen historical market-surveillance model",
        "research_use_only": True,
        "frozen_model_policy": {
            "model_bundle_sha256_before": bundle_hash_before,
            "model_bundle_sha256_after": bundle_hash_after,
            "bundle_unchanged": bundle_hash_before == bundle_hash_after,
            "retraining_performed": False,
            "recalibration_performed": False,
            "threshold_tuning_performed": False,
            "threshold_source": "frozen Step-6 model bundle",
            "frozen_threshold": threshold,
            "selected_features_source": "frozen Step-6 model bundle",
        },
        "blindness_policy": {
            "ground_truth_loaded_during_scoring": False,
            "registry_forbids_label_outcome_fields": True,
            "future_prices_rejected": True,
            "future_earnings_information_rejected": True,
            "enforcement_outcomes_rejected_as_features": True,
        },
        "inputs": {
            "model_bundle": str(model_bundle),
            "registry": str(registry),
            "registry_sha256": _sha256(registry),
            "feature_vectors": str(feature_vectors),
            "feature_vectors_sha256": _sha256(feature_vectors),
        },
        "sample_counts": {
            "total": len(retained),
            "by_case_family": family_counts,
        },
        "outputs": {"external_scores": "external_scores.csv"},
        "prohibited_outputs": PROHIBITED_OUTPUTS,
        "interpretation_warning": "A surveillance score prioritizes historical anomaly review and is not a probability that a crime occurred.",
    }
    (output_dir / "external_scoring_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def load_ground_truth(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {"sample_id", "label", "truth_role"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"ground truth file missing columns: {sorted(missing)}")
        for i, row in enumerate(reader, 2):
            sid = _clean(row.get("sample_id"))
            label_raw = _clean(row.get("label"))
            if not sid or sid in out or label_raw not in {"0", "1"}:
                raise ValueError(f"ground truth row {i}: invalid/duplicate sample_id or label")
            out[sid] = {**row, "sample_id": sid, "label": int(label_raw)}
    if not out:
        raise ValueError("ground truth file contains no rows")
    return out


def evaluate_external(
    *,
    scores_csv: Path,
    ground_truth: Path,
    output_dir: Path,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    truth = load_ground_truth(ground_truth)
    scored: list[dict] = []
    with scores_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {
            "sample_id", "case_id", "case_family", "mechanism", "symbol",
            "minute_ts_utc", "surveillance_risk_score", "frozen_threshold",
        }
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"scores file missing columns: {sorted(missing)}")
        for row in reader:
            sid = _clean(row.get("sample_id"))
            if sid not in truth:
                raise ValueError(f"no sealed ground truth for scored sample {sid}")
            scored.append({
                **row,
                "label": truth[sid]["label"],
                "truth_role": truth[sid].get("truth_role", ""),
                "score": float(row["surveillance_risk_score"]) / 100.0,
                "threshold": float(row["frozen_threshold"]),
            })
    if set(truth) != {r["sample_id"] for r in scored}:
        missing_scores = sorted(set(truth) - {r["sample_id"] for r in scored})
        raise ValueError(f"ground truth contains unscored samples: {missing_scores[:5]}")
    thresholds = {r["threshold"] for r in scored}
    if len(thresholds) != 1:
        raise ValueError("scores contain inconsistent frozen thresholds")
    threshold = next(iter(thresholds))

    def metrics(rows: list[dict]) -> dict:
        y = np.array([r["label"] for r in rows], dtype=int)
        s = np.array([r["score"] for r in rows], dtype=float)
        return evaluate(y, s, threshold)

    by_family: dict[str, dict] = {}
    for family in sorted({r["case_family"] for r in scored}):
        by_family[family] = metrics([r for r in scored if r["case_family"] == family])
    by_mechanism: dict[str, dict] = {}
    for mech in sorted({r["mechanism"] for r in scored}):
        by_mechanism[mech] = metrics([r for r in scored if r["mechanism"] == mech])

    joined_rows = []
    for r in scored:
        joined_rows.append({
            "sample_id": r["sample_id"],
            "case_id": r["case_id"],
            "case_family": r["case_family"],
            "mechanism": r["mechanism"],
            "symbol": r["symbol"],
            "minute_ts_utc": r["minute_ts_utc"],
            "label": r["label"],
            "truth_role": r["truth_role"],
            "surveillance_risk_score": r["surveillance_risk_score"],
            "flag_at_frozen_threshold": int(r["score"] >= threshold),
            "research_use_only": 1,
        })
    _write_dict_csv(
        output_dir / "external_evaluation_rows.csv",
        joined_rows,
        [
            "sample_id", "case_id", "case_family", "mechanism", "symbol",
            "minute_ts_utc", "label", "truth_role", "surveillance_risk_score",
            "flag_at_frozen_threshold", "research_use_only",
        ],
    )

    report = {
        "schema_version": SCHEMA_VERSION,
        "purpose": "post-score evaluation against sealed adjudicated-case ground truth",
        "research_use_only": True,
        "scoring_was_blind": True,
        "model_retraining_performed": False,
        "threshold_tuning_performed": False,
        "frozen_threshold": threshold,
        "inputs": {
            "scores_csv": str(scores_csv),
            "scores_sha256": _sha256(scores_csv),
            "ground_truth": str(ground_truth),
            "ground_truth_sha256": _sha256(ground_truth),
        },
        "metrics": {
            "overall": metrics(scored),
            "by_case_family": by_family,
            "by_mechanism": by_mechanism,
        },
        "outputs": {"evaluation_rows": "external_evaluation_rows.csv"},
        "interpretation_warning": "External validation measures anomaly detection against historical adjudicated cases; it does not establish criminal intent or identify MNPI content.",
    }
    (output_dir / "external_validation_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _args():
    p = argparse.ArgumentParser(description="Blind external validation of frozen historical surveillance model")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("score", help="score external cases without loading ground truth")
    s.add_argument("--model-bundle", type=Path, required=True)
    s.add_argument("--registry", type=Path, required=True)
    s.add_argument("--feature-vectors", type=Path, required=True)
    s.add_argument("--output-dir", type=Path, required=True)
    s.add_argument("--min-status", choices=sorted(STATUS_RANK), default="partial")

    e = sub.add_parser("evaluate", help="join sealed ground truth after scoring")
    e.add_argument("--scores-csv", type=Path, required=True)
    e.add_argument("--ground-truth", type=Path, required=True)
    e.add_argument("--output-dir", type=Path, required=True)
    return p.parse_args()


if __name__ == "__main__":
    args = _args()
    if args.cmd == "score":
        result = score_external(
            model_bundle=args.model_bundle,
            registry=args.registry,
            feature_vectors=args.feature_vectors,
            output_dir=args.output_dir,
            min_status=args.min_status,
        )
    else:
        result = evaluate_external(
            scores_csv=args.scores_csv,
            ground_truth=args.ground_truth,
            output_dir=args.output_dir,
        )
    print(json.dumps(result, indent=2))
