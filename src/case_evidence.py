from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
import sqlite3
import zipfile
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import joblib

SCHEMA_VERSION = "0.8.0"
RESEARCH_NOTICE = (
    "Historical market-surveillance research only; a surveillance score or case file "
    "is not a finding that insider trading, MNPI misuse, or any other violation occurred."
)
PROHIBITED_CASE_OUTPUTS = {
    "buy",
    "sell",
    "trade_direction",
    "expected_return",
    "target_price",
    "position_size",
    "order_instruction",
}


@dataclass(frozen=True)
class CaseRecord:
    case_id: str
    sample_id: str
    event_id: str
    symbol: str
    minute_ts_utc: str
    surveillance_risk_score: float
    surveillance_threshold: float
    flagged: int
    model_sha256: str
    model_schema_version: str
    created_at_utc: str
    research_use_only: int = 1
    initial_status: str = "open_for_review"
    determination_notice: str = RESEARCH_NOTICE


@dataclass(frozen=True)
class TimelineRow:
    case_id: str
    event_ts_utc: str
    event_type: str
    subject_symbol: str
    detail_json: str
    source_role: str
    source_sha256: str
    created_at_utc: str


@dataclass(frozen=True)
class FeatureSnapshot:
    case_id: str
    symbol: str
    minute_ts_utc: str
    feature_name: str
    feature_value: str
    feature_status: str
    source_role: str
    source_sha256: str


@dataclass(frozen=True)
class ControlSnapshot:
    case_id: str
    match_id: str
    control_rank: int
    control_symbol: str
    minute_ts_utc: str
    control_risk_score: str
    source_role: str
    source_sha256: str


@dataclass(frozen=True)
class SourceArtifact:
    case_id: str
    artifact_role: str
    file_name: str
    sha256: str
    size_bytes: int
    captured_at_utc: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _clean(v: str | None) -> str:
    return (v or "").strip()


def _validate_case_id(value: str) -> str:
    case_id = _clean(value)
    if (
        not case_id
        or len(case_id) > 128
        or any(not (ch.isalnum() or ch in "-_") for ch in case_id)
    ):
        raise ValueError("case_id must contain only letters, numbers, '-' or '_' and be at most 128 characters")
    return case_id


def _contained_child(root: Path, name: str) -> Path:
    root = Path(root).resolve()
    child = (root / name).resolve()
    try:
        child.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"refusing path outside output directory: {name!r}") from exc
    return child


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _canonical_json(obj: dict | list) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _parse_ts(v: str) -> str:
    v = _clean(v)
    if not v:
        raise ValueError("blank timestamp")
    dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _ensure_research_only(v: object) -> None:
    if str(v).strip().lower() not in {"1", "true"}:
        raise ValueError("evidence generation requires research_use_only=true")


def connect(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS case_record (
                case_id TEXT PRIMARY KEY,
                sample_id TEXT NOT NULL UNIQUE,
                event_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                minute_ts_utc TEXT NOT NULL,
                surveillance_risk_score REAL NOT NULL CHECK(surveillance_risk_score BETWEEN 0 AND 100),
                surveillance_threshold REAL NOT NULL CHECK(surveillance_threshold BETWEEN 0 AND 1),
                flagged INTEGER NOT NULL CHECK(flagged IN (0,1)),
                model_sha256 TEXT NOT NULL,
                model_schema_version TEXT NOT NULL,
                created_at_utc TEXT NOT NULL,
                research_use_only INTEGER NOT NULL CHECK(research_use_only=1),
                initial_status TEXT NOT NULL,
                determination_notice TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS case_timeline (
                timeline_id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT NOT NULL REFERENCES case_record(case_id),
                event_ts_utc TEXT NOT NULL,
                event_type TEXT NOT NULL,
                subject_symbol TEXT NOT NULL,
                detail_json TEXT NOT NULL,
                source_role TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                created_at_utc TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS feature_snapshot (
                feature_id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT NOT NULL REFERENCES case_record(case_id),
                symbol TEXT NOT NULL,
                minute_ts_utc TEXT NOT NULL,
                feature_name TEXT NOT NULL,
                feature_value TEXT NOT NULL,
                feature_status TEXT NOT NULL,
                source_role TEXT NOT NULL,
                source_sha256 TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS control_snapshot (
                control_id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT NOT NULL REFERENCES case_record(case_id),
                match_id TEXT NOT NULL,
                control_rank INTEGER NOT NULL,
                control_symbol TEXT NOT NULL,
                minute_ts_utc TEXT NOT NULL,
                control_risk_score TEXT NOT NULL,
                source_role TEXT NOT NULL,
                source_sha256 TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS source_artifact (
                source_id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT NOT NULL REFERENCES case_record(case_id),
                artifact_role TEXT NOT NULL,
                file_name TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                captured_at_utc TEXT NOT NULL,
                UNIQUE(case_id, artifact_role, sha256)
            );

            CREATE TABLE IF NOT EXISTS review_history (
                review_id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT NOT NULL REFERENCES case_record(case_id),
                reviewed_at_utc TEXT NOT NULL,
                reviewer TEXT NOT NULL,
                action TEXT NOT NULL,
                disposition TEXT NOT NULL,
                note TEXT NOT NULL,
                previous_record_hash TEXT NOT NULL,
                record_hash TEXT NOT NULL UNIQUE,
                research_use_only INTEGER NOT NULL CHECK(research_use_only=1)
            );

            CREATE INDEX IF NOT EXISTS idx_timeline_case ON case_timeline(case_id, event_ts_utc);
            CREATE INDEX IF NOT EXISTS idx_feature_case ON feature_snapshot(case_id, symbol, minute_ts_utc);
            CREATE INDEX IF NOT EXISTS idx_control_case ON control_snapshot(case_id, control_rank);
            CREATE INDEX IF NOT EXISTS idx_review_case ON review_history(case_id, review_id);
            """
        )
        # Immutable evidence: corrections must be appended as new evidence/review entries,
        # never silently overwrite or delete existing records.
        for table in [
            "case_record",
            "case_timeline",
            "feature_snapshot",
            "control_snapshot",
            "source_artifact",
            "review_history",
        ]:
            con.execute(
                f"""CREATE TRIGGER IF NOT EXISTS no_update_{table}
                BEFORE UPDATE ON {table}
                BEGIN SELECT RAISE(ABORT, 'immutable evidence: UPDATE prohibited'); END;"""
            )
            con.execute(
                f"""CREATE TRIGGER IF NOT EXISTS no_delete_{table}
                BEFORE DELETE ON {table}
                BEGIN SELECT RAISE(ABORT, 'immutable evidence: DELETE prohibited'); END;"""
            )


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        return list(r.fieldnames or []), list(r)


def _find_one(rows: Iterable[dict[str, str]], key: str, value: str) -> dict[str, str]:
    hits = [r for r in rows if _clean(r.get(key)) == value]
    if len(hits) != 1:
        raise ValueError(f"expected exactly one row where {key}={value!r}; found {len(hits)}")
    return hits[0]


def _load_bundle(bundle_path: Path) -> dict:
    bundle = joblib.load(bundle_path)
    required = {"selected_features", "surveillance_threshold", "research_use_only"}
    missing = required.difference(bundle)
    if missing:
        raise ValueError(f"model bundle missing fields: {sorted(missing)}")
    if bundle.get("research_use_only") is not True:
        raise ValueError("case evidence requires research-use-only model bundle")
    threshold = float(bundle["surveillance_threshold"])
    if not 0 <= threshold <= 1:
        raise ValueError("invalid surveillance threshold")
    return bundle


def _score_fields(score_fields: list[str]) -> tuple[str, str]:
    if "flag_at_dev_threshold" in score_fields:
        return "flag_at_dev_threshold", ""
    if "flag_at_frozen_threshold" in score_fields:
        return "flag_at_frozen_threshold", "frozen_threshold"
    raise ValueError("score file has no recognized surveillance-flag field")


def _model_schema_version(training_manifest: Path | None) -> str:
    if training_manifest is None:
        return "unknown"
    obj = json.loads(training_manifest.read_text(encoding="utf-8"))
    return str(obj.get("schema_version") or obj.get("model_schema_version") or "unknown")


def _insert_dataclass(con: sqlite3.Connection, table: str, obj) -> None:
    names = [f.name for f in fields(obj)]
    vals = [getattr(obj, n) for n in names]
    q = ",".join("?" for _ in names)
    con.execute(f"INSERT INTO {table} ({','.join(names)}) VALUES ({q})", vals)


def _add_source(con: sqlite3.Connection, case_id: str, role: str, path: Path, captured: str) -> str:
    sha = _sha256(path)
    _insert_dataclass(
        con,
        "source_artifact",
        SourceArtifact(case_id, role, path.name, sha, path.stat().st_size, captured),
    )
    return sha


def add_review(
    *,
    db_path: Path,
    case_id: str,
    reviewer: str,
    action: str,
    disposition: str,
    note: str = "",
    reviewed_at_utc: str | None = None,
) -> str:
    reviewer, action, disposition = map(_clean, [reviewer, action, disposition])
    if not reviewer or not action or not disposition:
        raise ValueError("reviewer/action/disposition are required")
    case_id = _validate_case_id(case_id)
    reviewed_at_utc = _parse_ts(reviewed_at_utc) if reviewed_at_utc else utc_now()
    with connect(db_path) as con:
        if not con.execute("SELECT 1 FROM case_record WHERE case_id=?", (case_id,)).fetchone():
            raise ValueError(f"unknown case_id={case_id!r}")
        prev = con.execute(
            "SELECT record_hash FROM review_history WHERE case_id=? ORDER BY review_id DESC LIMIT 1",
            (case_id,),
        ).fetchone()
        prev_hash = prev[0] if prev else "GENESIS"
        payload = {
            "case_id": case_id,
            "reviewed_at_utc": reviewed_at_utc,
            "reviewer": reviewer,
            "action": action,
            "disposition": disposition,
            "note": note,
            "previous_record_hash": prev_hash,
            "research_use_only": 1,
        }
        record_hash = _sha_text(_canonical_json(payload))
        con.execute(
            """INSERT INTO review_history
            (case_id, reviewed_at_utc, reviewer, action, disposition, note,
             previous_record_hash, record_hash, research_use_only)
            VALUES (?,?,?,?,?,?,?,?,1)""",
            (
                case_id,
                reviewed_at_utc,
                reviewer,
                action,
                disposition,
                note,
                prev_hash,
                record_hash,
            ),
        )
    return record_hash


def verify_review_chain(db_path: Path, case_id: str) -> bool:
    case_id = _validate_case_id(case_id)
    with connect(db_path) as con:
        rows = con.execute(
            "SELECT * FROM review_history WHERE case_id=? ORDER BY review_id", (case_id,)
        ).fetchall()
    prev = "GENESIS"
    for row in rows:
        if row["previous_record_hash"] != prev:
            return False
        payload = {
            "case_id": row["case_id"],
            "reviewed_at_utc": row["reviewed_at_utc"],
            "reviewer": row["reviewer"],
            "action": row["action"],
            "disposition": row["disposition"],
            "note": row["note"],
            "previous_record_hash": row["previous_record_hash"],
            "research_use_only": 1,
        }
        if _sha_text(_canonical_json(payload)) != row["record_hash"]:
            return False
        prev = row["record_hash"]
    return True


def ingest_case(
    *,
    db_path: Path,
    case_id: str,
    sample_id: str,
    scores_csv: Path,
    feature_vectors: Path,
    model_bundle: Path,
    matched_controls: Path | None = None,
    training_manifest: Path | None = None,
    scorer_manifest: Path | None = None,
) -> dict:
    init_db(db_path)
    case_id, sample_id = _validate_case_id(case_id), _clean(sample_id)
    if not sample_id:
        raise ValueError("sample_id is required")
    captured = utc_now()

    score_fields, score_rows = _read_csv(scores_csv)
    score = _find_one(score_rows, "sample_id", sample_id)
    _ensure_research_only(score.get("research_use_only"))
    flag_field, threshold_field = _score_fields(score_fields)

    bundle = _load_bundle(model_bundle)
    threshold = (
        float(score[threshold_field]) if threshold_field and _clean(score.get(threshold_field))
        else float(bundle["surveillance_threshold"])
    )
    risk = float(score.get("surveillance_risk_score", "nan"))
    if not math.isfinite(risk) or not 0 <= risk <= 100:
        raise ValueError("surveillance risk score must be in [0,100]")
    flagged = int(score[flag_field])
    if flagged not in {0, 1}:
        raise ValueError("flag must be 0/1")
    symbol = _clean(score.get("symbol")).upper()
    ts = _parse_ts(score.get("minute_ts_utc", ""))
    event_id = _clean(score.get("event_id") or score.get("case_id") or sample_id)
    if not symbol:
        raise ValueError("score row missing symbol")

    feature_fields, feature_rows = _read_csv(feature_vectors)
    forbidden = [f for f in feature_fields if f.lower() in PROHIBITED_CASE_OUTPUTS]
    if forbidden:
        raise ValueError(f"feature vectors contain prohibited output fields: {forbidden}")
    feature = [
        r
        for r in feature_rows
        if _clean(r.get("symbol")).upper() == symbol
        and _parse_ts(r.get("minute_ts_utc", "")) == ts
    ]
    if len(feature) != 1:
        raise ValueError(f"expected one feature vector for {symbol}@{ts}; found {len(feature)}")
    feature = feature[0]
    _ensure_research_only(feature.get("research_use_only"))
    selected_features = tuple(bundle["selected_features"])
    missing_features = [f for f in selected_features if f not in feature_fields]
    if missing_features:
        raise ValueError(f"feature vector missing model features: {missing_features}")

    controls: list[dict[str, str]] = []
    if matched_controls is not None:
        _, all_controls = _read_csv(matched_controls)
        controls = [r for r in all_controls if _clean(r.get("event_id")) == event_id]
        controls.sort(key=lambda r: int(r.get("control_rank") or 999999))

    model_sha = _sha256(model_bundle)
    scores_sha = _sha256(scores_csv)
    features_sha = _sha256(feature_vectors)
    control_sha = _sha256(matched_controls) if matched_controls else ""

    record = CaseRecord(
        case_id=case_id,
        sample_id=sample_id,
        event_id=event_id,
        symbol=symbol,
        minute_ts_utc=ts,
        surveillance_risk_score=risk,
        surveillance_threshold=threshold,
        flagged=flagged,
        model_sha256=model_sha,
        model_schema_version=_model_schema_version(training_manifest),
        created_at_utc=captured,
    )

    with connect(db_path) as con:
        if con.execute("SELECT 1 FROM case_record WHERE case_id=? OR sample_id=?", (case_id, sample_id)).fetchone():
            raise ValueError("case_id or sample_id already exists")
        _insert_dataclass(con, "case_record", record)

        # Capture provenance before evidence rows reference hashes.
        _add_source(con, case_id, "scores_csv", scores_csv, captured)
        _add_source(con, case_id, "feature_vectors", feature_vectors, captured)
        _add_source(con, case_id, "model_bundle", model_bundle, captured)
        if matched_controls:
            _add_source(con, case_id, "matched_controls", matched_controls, captured)
        if training_manifest:
            _add_source(con, case_id, "training_manifest", training_manifest, captured)
        if scorer_manifest:
            _add_source(con, case_id, "scorer_manifest", scorer_manifest, captured)

        _insert_dataclass(
            con,
            "case_timeline",
            TimelineRow(
                case_id,
                ts,
                "surveillance_score_recorded",
                symbol,
                _canonical_json(
                    {
                        "surveillance_risk_score": risk,
                        "threshold": threshold,
                        "flagged": flagged,
                        "notice": RESEARCH_NOTICE,
                    }
                ),
                "scores_csv",
                scores_sha,
                captured,
            ),
        )

        feature_status = _clean(feature.get("feature_status") or "unknown")
        ranked: list[tuple[float, str, str]] = []
        for name in selected_features:
            raw = _clean(feature.get(name))
            if raw == "":
                continue
            val = float(raw)
            if not math.isfinite(val):
                continue
            _insert_dataclass(
                con,
                "feature_snapshot",
                FeatureSnapshot(
                    case_id, symbol, ts, name, raw, feature_status, "feature_vectors", features_sha
                ),
            )
            ranked.append((abs(val), name, raw))

        for _, name, raw in sorted(ranked, reverse=True)[:5]:
            _insert_dataclass(
                con,
                "case_timeline",
                TimelineRow(
                    case_id,
                    ts,
                    "top_feature_snapshot",
                    symbol,
                    _canonical_json({"feature": name, "value": raw}),
                    "feature_vectors",
                    features_sha,
                    captured,
                ),
            )

        score_by_symbol: dict[tuple[str, str], str] = {}
        for r in score_rows:
            s = _clean(r.get("symbol")).upper()
            t = _clean(r.get("minute_ts_utc"))
            if s and t:
                try:
                    score_by_symbol[(s, _parse_ts(t))] = _clean(r.get("surveillance_risk_score"))
                except ValueError:
                    pass
        for r in controls:
            cs = _clean(r.get("control_symbol")).upper()
            cts = _parse_ts(r.get("control_minute_ts_utc", ""))
            _insert_dataclass(
                con,
                "control_snapshot",
                ControlSnapshot(
                    case_id=case_id,
                    match_id=_clean(r.get("match_id")),
                    control_rank=int(r.get("control_rank") or 0),
                    control_symbol=cs,
                    minute_ts_utc=cts,
                    control_risk_score=score_by_symbol.get((cs, cts), ""),
                    source_role="matched_controls",
                    source_sha256=control_sha,
                ),
            )

    # Initial review entry is append-only and hash chained.
    add_review(
        db_path=db_path,
        case_id=case_id,
        reviewer="system",
        action="case_created",
        disposition="pending_human_review",
        note=RESEARCH_NOTICE,
        reviewed_at_utc=captured,
    )
    return {
        "case_id": case_id,
        "sample_id": sample_id,
        "symbol": symbol,
        "minute_ts_utc": ts,
        "surveillance_risk_score": risk,
        "surveillance_threshold": threshold,
        "flagged": flagged,
        "feature_count": len(ranked),
        "control_count": len(controls),
        "review_chain_valid": verify_review_chain(db_path, case_id),
        "research_use_only": True,
        "determination_notice": RESEARCH_NOTICE,
    }


def _query_dicts(con: sqlite3.Connection, sql: str, params: tuple) -> list[dict]:
    return [dict(r) for r in con.execute(sql, params).fetchall()]


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    if fieldnames is None:
        fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if fieldnames:
            w.writeheader()
            w.writerows(rows)


def _write_json(path: Path, obj: dict | list) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def export_case(*, db_path: Path, case_id: str, output_dir: Path) -> dict:
    case_id = _validate_case_id(case_id)
    if not verify_review_chain(db_path, case_id):
        raise ValueError("review-history integrity chain is invalid")
    with connect(db_path) as con:
        case_row = con.execute("SELECT * FROM case_record WHERE case_id=?", (case_id,)).fetchone()
        if not case_row:
            raise ValueError(f"unknown case_id={case_id!r}")
        case = dict(case_row)
        timeline = _query_dicts(con, "SELECT * FROM case_timeline WHERE case_id=? ORDER BY event_ts_utc,timeline_id", (case_id,))
        features = _query_dicts(con, "SELECT * FROM feature_snapshot WHERE case_id=? ORDER BY symbol,minute_ts_utc,feature_name", (case_id,))
        controls = _query_dicts(con, "SELECT * FROM control_snapshot WHERE case_id=? ORDER BY control_rank,control_id", (case_id,))
        sources = _query_dicts(con, "SELECT * FROM source_artifact WHERE case_id=? ORDER BY source_id", (case_id,))
        reviews = _query_dicts(con, "SELECT * FROM review_history WHERE case_id=? ORDER BY review_id", (case_id,))

    current_disposition = reviews[-1]["disposition"] if reviews else case["initial_status"]
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_dir = _contained_child(output_dir, case_id)
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    bundle_dir.mkdir(parents=True)

    # Do not export ground-truth labels or trading directives even if an upstream file contained them.
    summary = {
        "schema_version": SCHEMA_VERSION,
        "case": case,
        "current_review_disposition": current_disposition,
        "review_chain_valid": True,
        "research_use_only": True,
        "determination_notice": RESEARCH_NOTICE,
        "prohibited_outputs": sorted(PROHIBITED_CASE_OUTPUTS),
    }
    _write_json(bundle_dir / "case_summary.json", summary)
    _write_csv(bundle_dir / "timeline.csv", timeline)
    _write_csv(bundle_dir / "feature_snapshots.csv", features)
    _write_csv(bundle_dir / "control_snapshots.csv", controls)
    _write_csv(bundle_dir / "source_artifacts.csv", sources)
    _write_csv(bundle_dir / "review_history.csv", reviews)

    provenance = {
        "schema_version": SCHEMA_VERSION,
        "case_id": case_id,
        "model_sha256": case["model_sha256"],
        "model_schema_version": case["model_schema_version"],
        "sources": [
            {
                "artifact_role": s["artifact_role"],
                "file_name": s["file_name"],
                "sha256": s["sha256"],
                "size_bytes": s["size_bytes"],
                "captured_at_utc": s["captured_at_utc"],
            }
            for s in sources
        ],
        "raw_sources_embedded": False,
        "reason_raw_sources_not_embedded": "preserve data entitlements/privacy; hashes provide provenance",
    }
    _write_json(bundle_dir / "provenance.json", provenance)

    (bundle_dir / "README.txt").write_text(
        "PRIVATE SURVEILLANCE RESEARCH EVIDENCE BUNDLE\n\n"
        + RESEARCH_NOTICE
        + "\n\nThis bundle contains derived evidence, hashes, model provenance, matched-control snapshots, "
          "and an append-only review history. Raw licensed/proprietary source files are not embedded.\n",
        encoding="utf-8",
    )

    # Hash every evidence file except integrity_manifest itself, then compute a bundle root.
    file_hashes: dict[str, str] = {}
    for path in sorted(bundle_dir.iterdir()):
        if path.is_file() and path.name != "integrity_manifest.json":
            file_hashes[path.name] = _sha256(path)
    root_material = "".join(f"{name}:{file_hashes[name]}\n" for name in sorted(file_hashes))
    root_sha = _sha_text(root_material)
    integrity = {
        "schema_version": SCHEMA_VERSION,
        "case_id": case_id,
        "generated_at_utc": utc_now(),
        "files": file_hashes,
        "bundle_root_sha256": root_sha,
        "review_chain_valid": True,
    }
    _write_json(bundle_dir / "integrity_manifest.json", integrity)

    zip_path = _contained_child(output_dir, f"{case_id}_evidence.zip")
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for path in sorted(bundle_dir.iterdir()):
            if path.is_file():
                z.write(path, arcname=f"{case_id}/{path.name}")

    return {
        "case_id": case_id,
        "bundle_dir": str(bundle_dir),
        "zip_path": str(zip_path),
        "bundle_root_sha256": root_sha,
        "timeline_rows": len(timeline),
        "feature_rows": len(features),
        "control_rows": len(controls),
        "review_rows": len(reviews),
        "research_use_only": True,
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Private surveillance case database and evidence generator")
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("init")
    a.add_argument("--db", type=Path, required=True)

    a = sub.add_parser("ingest")
    a.add_argument("--db", type=Path, required=True)
    a.add_argument("--case-id", required=True)
    a.add_argument("--sample-id", required=True)
    a.add_argument("--scores-csv", type=Path, required=True)
    a.add_argument("--feature-vectors", type=Path, required=True)
    a.add_argument("--model-bundle", type=Path, required=True)
    a.add_argument("--matched-controls", type=Path)
    a.add_argument("--training-manifest", type=Path)
    a.add_argument("--scorer-manifest", type=Path)

    a = sub.add_parser("review")
    a.add_argument("--db", type=Path, required=True)
    a.add_argument("--case-id", required=True)
    a.add_argument("--reviewer", required=True)
    a.add_argument("--action", required=True)
    a.add_argument("--disposition", required=True)
    a.add_argument("--note", default="")
    a.add_argument("--reviewed-at-utc")

    a = sub.add_parser("export")
    a.add_argument("--db", type=Path, required=True)
    a.add_argument("--case-id", required=True)
    a.add_argument("--output-dir", type=Path, required=True)
    return p


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "init":
        init_db(args.db)
        print(json.dumps({"db": str(args.db), "schema_version": SCHEMA_VERSION}, indent=2))
    elif args.command == "ingest":
        out = ingest_case(
            db_path=args.db,
            case_id=args.case_id,
            sample_id=args.sample_id,
            scores_csv=args.scores_csv,
            feature_vectors=args.feature_vectors,
            model_bundle=args.model_bundle,
            matched_controls=args.matched_controls,
            training_manifest=args.training_manifest,
            scorer_manifest=args.scorer_manifest,
        )
        print(json.dumps(out, indent=2, sort_keys=True))
    elif args.command == "review":
        h = add_review(
            db_path=args.db,
            case_id=args.case_id,
            reviewer=args.reviewer,
            action=args.action,
            disposition=args.disposition,
            note=args.note,
            reviewed_at_utc=args.reviewed_at_utc,
        )
        print(json.dumps({"case_id": args.case_id, "record_hash": h, "chain_valid": verify_review_chain(args.db, args.case_id)}, indent=2))
    elif args.command == "export":
        print(json.dumps(export_case(db_path=args.db, case_id=args.case_id, output_dir=args.output_dir), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
