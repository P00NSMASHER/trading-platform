from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

SCHEMA_VERSION = "0.5.0"

DEFAULT_NUMERIC_COVARIATES = (
    "market_cap",
    "price",
    "trailing_21d_vol",
    "normal_minute_volume",
    "normal_minute_turnover",
    "normal_relative_spread",
    "option_liquidity",
    "institutional_ownership",
    "analyst_coverage",
    "borrow_cost",
    "pre_event_return",
)

LOG_COVARIATES = {
    "market_cap",
    "price",
    "normal_minute_volume",
    "normal_minute_turnover",
    "normal_relative_spread",
    "option_liquidity",
    "analyst_coverage",
}

FORBIDDEN_MATCH_TERMS = (
    "future",
    "next_day",
    "nextday",
    "post_event",
    "postevent",
    "announcement_reaction",
    "earnings_surprise",
    "unreleased",
    "enforcement",
    "prosecution",
    "sec_documented_trade",
    "hacked_flag",
    "actual",
    "expected_return",
    "target_price",
)

STATUS_RANK = {"insufficient": 0, "partial": 1, "full": 2}


@dataclass(frozen=True)
class MatchedControl:
    match_id: str
    event_id: str
    treated_symbol: str
    treated_minute_ts_utc: str
    control_rank: int
    control_symbol: str
    control_minute_ts_utc: str
    local_date: str
    local_minute: str
    same_sector: int
    scheduled_event_match: int
    candidate_pool_size: int
    numeric_covariates_used: int
    match_distance: str
    max_component_z: str
    match_quality: str
    treated_feature_status: str
    control_feature_status: str
    metadata_source_names: str
    research_use_only: int = 1


@dataclass(frozen=True)
class EventMatchSummary:
    event_id: str
    treated_symbol: str
    treated_minute_ts_utc: str
    local_date: str
    local_minute: str
    candidate_pool_size: int
    matched_control_count: int
    event_status: str
    mean_match_distance: str
    max_match_distance: str
    max_component_z: str
    research_use_only: int = 1


def _clean(v: str | None) -> str:
    return (v or "").strip()


def _parse_float(v: str | None) -> float | None:
    v = _clean(v)
    if not v:
        return None
    try:
        out = float(v)
    except Exception as exc:
        raise ValueError(f"invalid numeric value {v!r}") from exc
    if not math.isfinite(out):
        raise ValueError(f"non-finite numeric value {v!r}")
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


def _parse_aware_ts(v: str) -> datetime:
    v = _clean(v)
    if not v:
        raise ValueError("blank timestamp")
    dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"timestamp must include timezone: {v!r}")
    return dt.astimezone(timezone.utc)


def _event_ts(v: str, event_timezone: str) -> datetime:
    v = _clean(v)
    if not v:
        raise ValueError("blank event timestamp")
    dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(event_timezone))
    return dt.astimezone(timezone.utc)


def _ts_key(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _bool_token(v: str | None) -> str:
    x = _clean(v).lower()
    if x in {"1", "true", "yes", "y"}:
        return "1"
    if x in {"0", "false", "no", "n"}:
        return "0"
    return ""


def _transform(name: str, value: float) -> float:
    if name in LOG_COVARIATES:
        if value < 0:
            raise ValueError(f"{name} must be non-negative for log transform")
        return math.log1p(value)
    return value


def validate_covariates(covariates: Iterable[str]) -> tuple[str, ...]:
    out = []
    for raw in covariates:
        name = _clean(raw)
        if not name:
            continue
        low = name.lower()
        if any(term in low for term in FORBIDDEN_MATCH_TERMS):
            raise ValueError(f"forbidden/lookahead matching covariate: {name}")
        if name not in DEFAULT_NUMERIC_COVARIATES:
            raise ValueError(f"unsupported matching covariate: {name}")
        if name not in out:
            out.append(name)
    if not out:
        raise ValueError("at least one numeric matching covariate is required")
    return tuple(out)


def load_events(path: Path, event_timezone: str = "America/New_York") -> list[dict]:
    out = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {"event_id", "historical_symbol", "first_documented_illicit_trade_ts"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"events file missing columns: {sorted(missing)}")
        for i, row in enumerate(reader, 2):
            symbol = _clean(row.get("historical_symbol")).upper()
            if not symbol:
                raise ValueError(f"event row {i}: blank historical_symbol")
            dt = _event_ts(row.get("first_documented_illicit_trade_ts", ""), event_timezone)
            local = dt.astimezone(ZoneInfo(event_timezone))
            out.append({
                **row,
                "event_id": _clean(row.get("event_id")),
                "historical_symbol": symbol,
                "_event_dt": dt,
                "_event_ts_key": _ts_key(dt),
                "_local_date": local.date().isoformat(),
                "_local_minute": local.strftime("%H:%M"),
            })
    return out


def load_features(path: Path, *, min_status: str = "partial") -> tuple[dict[tuple[str, str, str], dict], dict[tuple[str, str], list[dict]]]:
    if min_status not in STATUS_RANK:
        raise ValueError(f"unknown min feature status {min_status!r}")
    exact = {}
    by_local = defaultdict(list)
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {"minute_ts_utc", "symbol", "local_date", "local_minute", "feature_status"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"feature file missing columns: {sorted(missing)}")
        for i, row in enumerate(reader, 2):
            symbol = _clean(row.get("symbol")).upper()
            dt = _parse_aware_ts(row.get("minute_ts_utc", ""))
            status = _clean(row.get("feature_status")).lower()
            if status not in STATUS_RANK:
                raise ValueError(f"feature row {i}: invalid status {status!r}")
            if STATUS_RANK[status] < STATUS_RANK[min_status]:
                continue
            norm = {**row, "symbol": symbol, "minute_ts_utc": _ts_key(dt), "feature_status": status, "_dt": dt}
            exact[(symbol, norm["local_date"], norm["local_minute"])] = norm
            by_local[(norm["local_date"], norm["local_minute"])].append(norm)
    return exact, dict(by_local)


def load_metadata(path: Path, covariates: tuple[str, ...]) -> dict[str, list[dict]]:
    out = defaultdict(list)
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {"symbol", "effective_ts_utc"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"metadata file missing columns: {sorted(missing)}")
        fields_in_file = set(reader.fieldnames or [])
        for c in covariates:
            if c not in fields_in_file:
                raise ValueError(f"metadata file missing requested covariate: {c}")
        for i, row in enumerate(reader, 2):
            symbol = _clean(row.get("symbol")).upper()
            if not symbol:
                raise ValueError(f"metadata row {i}: blank symbol")
            dt = _parse_aware_ts(row.get("effective_ts_utc", ""))
            vals = {}
            for c in covariates:
                vals[c] = _parse_float(row.get(c))
            norm = {
                **row,
                "symbol": symbol,
                "effective_ts_utc": _ts_key(dt),
                "_dt": dt,
                "_values": vals,
                "_sector": _clean(row.get("sector")),
                "_index_bucket": _clean(row.get("index_bucket")),
                "_scheduled": _bool_token(row.get("scheduled_event_flag")),
                "_source_name": _clean(row.get("source_name")) or "point_in_time_metadata",
            }
            out[symbol].append(norm)
    for rows in out.values():
        rows.sort(key=lambda r: r["_dt"])
    return dict(out)


def latest_metadata(metadata: dict[str, list[dict]], symbol: str, asof: datetime) -> dict | None:
    rows = metadata.get(symbol, [])
    latest = None
    for row in rows:
        if row["_dt"] <= asof:
            latest = row
        else:
            break
    return latest


def load_exclusions(path: Path | None) -> list[dict]:
    if path is None:
        return []
    out = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {"symbol", "start_ts_utc", "end_ts_utc"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"exclusions file missing columns: {sorted(missing)}")
        for row in reader:
            out.append({
                "symbol": _clean(row.get("symbol")).upper(),
                "start": _parse_aware_ts(row.get("start_ts_utc", "")),
                "end": _parse_aware_ts(row.get("end_ts_utc", "")),
                "reason": _clean(row.get("reason")),
            })
    return out


def _excluded(symbol: str, ts: datetime, exclusions: list[dict]) -> bool:
    return any(e["symbol"] == symbol and e["start"] <= ts <= e["end"] for e in exclusions)


def _robust_scale(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    med = statistics.median(values)
    mad = statistics.median(abs(v - med) for v in values)
    if mad > 0:
        return 1.4826 * mad
    try:
        s = statistics.stdev(values)
    except statistics.StatisticsError:
        s = 0.0
    return s if s > 0 else None


def _positive_event_dates(events: list[dict]) -> set[tuple[str, str]]:
    return {(e["historical_symbol"], e["_local_date"]) for e in events}


def _numeric_distance(
    treated: dict,
    candidates: list[dict],
    covariates: tuple[str, ...],
    max_component_z: float,
) -> list[tuple[dict, float, float, int]]:
    transformed = {c: [] for c in covariates}
    tvals = {}
    for c in covariates:
        tv = treated["_values"].get(c)
        if tv is None:
            continue
        tvt = _transform(c, tv)
        tvals[c] = tvt
        transformed[c].append(tvt)
        for cand in candidates:
            cv = cand["metadata"]["_values"].get(c)
            if cv is not None:
                transformed[c].append(_transform(c, cv))
    scales = {c: _robust_scale(vals) for c, vals in transformed.items() if vals}

    ranked = []
    for cand in candidates:
        components = []
        rejected = False
        for c, tv in tvals.items():
            cv_raw = cand["metadata"]["_values"].get(c)
            if cv_raw is None:
                continue
            cv = _transform(c, cv_raw)
            scale = scales.get(c)
            if scale is None:
                if abs(cv - tv) <= 1e-12:
                    z = 0.0
                else:
                    rejected = True
                    break
            else:
                z = abs(cv - tv) / scale
            if z > max_component_z:
                rejected = True
                break
            components.append(z)
        if rejected or not components:
            continue
        distance = math.sqrt(sum(z * z for z in components) / len(components))
        ranked.append((cand, distance, max(components), len(components)))
    ranked.sort(key=lambda x: (x[1], x[2], x[0]["feature"]["symbol"]))
    return ranked


def _quality(distance: float, max_z: float) -> str:
    if distance <= 1.0 and max_z <= 1.5:
        return "good"
    if distance <= 1.5 and max_z <= 2.5:
        return "acceptable"
    return "weak"


def _match_id(event_id: str, symbol: str, ts_key: str) -> str:
    raw = f"{event_id}|{symbol}|{ts_key}".encode("utf-8")
    return "MC-" + hashlib.sha256(raw).hexdigest()[:16].upper()


def generate_matches(
    *,
    events: list[dict],
    features_by_local: dict[tuple[str, str], list[dict]],
    features_exact: dict[tuple[str, str, str], dict],
    metadata: dict[str, list[dict]],
    covariates: tuple[str, ...],
    controls_per_event: int = 3,
    min_controls: int = 3,
    max_component_z: float = 2.5,
    require_same_sector: bool = True,
    match_scheduled_event: bool = True,
    exclusions: list[dict] | None = None,
) -> tuple[list[MatchedControl], list[EventMatchSummary], list[dict]]:
    if controls_per_event < 1 or min_controls < 1 or min_controls > controls_per_event:
        raise ValueError("invalid controls_per_event/min_controls")
    if max_component_z <= 0:
        raise ValueError("max_component_z must be positive")
    exclusions = exclusions or []
    positives = _positive_event_dates(events)

    matches: list[MatchedControl] = []
    summaries: list[EventMatchSummary] = []
    eligible_for_balance: list[dict] = []

    for event in events:
        event_id = event["event_id"]
        treated_symbol = event["historical_symbol"]
        ts = event["_event_dt"]
        local_key = (event["_local_date"], event["_local_minute"])
        treated_feature = features_exact.get((treated_symbol, *local_key))
        treated_meta = latest_metadata(metadata, treated_symbol, ts)

        if treated_feature is None:
            summaries.append(EventMatchSummary(event_id, treated_symbol, event["_event_ts_key"], *local_key, 0, 0, "missing_treated_features", "", "", ""))
            continue
        if treated_meta is None:
            summaries.append(EventMatchSummary(event_id, treated_symbol, event["_event_ts_key"], *local_key, 0, 0, "missing_treated_metadata", "", "", ""))
            continue

        pool = []
        for feature in features_by_local.get(local_key, []):
            symbol = feature["symbol"]
            if symbol == treated_symbol:
                continue
            if (symbol, event["_local_date"]) in positives:
                continue
            if _excluded(symbol, ts, exclusions):
                continue
            meta = latest_metadata(metadata, symbol, ts)
            if meta is None:
                continue
            if require_same_sector and treated_meta["_sector"] and meta["_sector"] != treated_meta["_sector"]:
                continue
            if treated_meta["_index_bucket"] and meta["_index_bucket"] and meta["_index_bucket"] != treated_meta["_index_bucket"]:
                continue
            if match_scheduled_event and treated_meta["_scheduled"] and meta["_scheduled"] != treated_meta["_scheduled"]:
                continue
            pool.append({"feature": feature, "metadata": meta})
            eligible_for_balance.append({"event_id": event_id, "role": "candidate", "metadata": meta, "treated_metadata": treated_meta})

        ranked = _numeric_distance(treated_meta, pool, covariates, max_component_z)
        candidate_pool_size = len(ranked)
        if candidate_pool_size < min_controls:
            summaries.append(EventMatchSummary(event_id, treated_symbol, event["_event_ts_key"], *local_key, candidate_pool_size, 0, "insufficient_controls", "", "", ""))
            continue

        chosen = ranked[:controls_per_event]
        distances = []
        component_maxes = []
        for rank, (cand, distance, component_z, n_used) in enumerate(chosen, 1):
            feature = cand["feature"]
            meta = cand["metadata"]
            distances.append(distance)
            component_maxes.append(component_z)
            matches.append(MatchedControl(
                match_id=_match_id(event_id, feature["symbol"], feature["minute_ts_utc"]),
                event_id=event_id,
                treated_symbol=treated_symbol,
                treated_minute_ts_utc=treated_feature["minute_ts_utc"],
                control_rank=rank,
                control_symbol=feature["symbol"],
                control_minute_ts_utc=feature["minute_ts_utc"],
                local_date=event["_local_date"],
                local_minute=event["_local_minute"],
                same_sector=int(bool(treated_meta["_sector"]) and meta["_sector"] == treated_meta["_sector"]),
                scheduled_event_match=int(bool(treated_meta["_scheduled"]) and meta["_scheduled"] == treated_meta["_scheduled"]),
                candidate_pool_size=candidate_pool_size,
                numeric_covariates_used=n_used,
                match_distance=_fmt(distance),
                max_component_z=_fmt(component_z),
                match_quality=_quality(distance, component_z),
                treated_feature_status=treated_feature["feature_status"],
                control_feature_status=feature["feature_status"],
                metadata_source_names=";".join(sorted({treated_meta["_source_name"], meta["_source_name"]})),
            ))
            eligible_for_balance.append({"event_id": event_id, "role": "matched", "metadata": meta, "treated_metadata": treated_meta})

        summaries.append(EventMatchSummary(
            event_id=event_id,
            treated_symbol=treated_symbol,
            treated_minute_ts_utc=treated_feature["minute_ts_utc"],
            local_date=event["_local_date"],
            local_minute=event["_local_minute"],
            candidate_pool_size=candidate_pool_size,
            matched_control_count=len(chosen),
            event_status="matched",
            mean_match_distance=_fmt(statistics.mean(distances)),
            max_match_distance=_fmt(max(distances)),
            max_component_z=_fmt(max(component_maxes)),
        ))

    return matches, summaries, eligible_for_balance


def _smd(treated: list[float], control: list[float]) -> float | None:
    if not treated or not control:
        return None
    tm, cm = statistics.mean(treated), statistics.mean(control)
    if len(treated) > 1:
        tv = statistics.variance(treated)
    else:
        tv = 0.0
    if len(control) > 1:
        cv = statistics.variance(control)
    else:
        cv = 0.0
    pooled = math.sqrt((tv + cv) / 2.0)
    if pooled == 0:
        return 0.0 if abs(tm - cm) <= 1e-12 else None
    return (tm - cm) / pooled


def balance_diagnostics(records: list[dict], covariates: tuple[str, ...]) -> list[dict]:
    # Each event contributes its treated value once. Candidate/matched controls contribute their own values.
    treated_by_event = {}
    before = defaultdict(list)
    after = defaultdict(list)
    for rec in records:
        event_id = rec["event_id"]
        treated_by_event[event_id] = rec["treated_metadata"]
        bucket = before if rec["role"] == "candidate" else after
        for c in covariates:
            v = rec["metadata"]["_values"].get(c)
            if v is not None:
                bucket[c].append(_transform(c, v))
    out = []
    for c in covariates:
        treated = []
        for meta in treated_by_event.values():
            v = meta["_values"].get(c)
            if v is not None:
                treated.append(_transform(c, v))
        b = before.get(c, [])
        a = after.get(c, [])
        out.append({
            "covariate": c,
            "treated_n": len(treated),
            "candidate_n": len(b),
            "matched_n": len(a),
            "treated_mean_transformed": _fmt(statistics.mean(treated) if treated else None),
            "candidate_mean_transformed": _fmt(statistics.mean(b) if b else None),
            "matched_mean_transformed": _fmt(statistics.mean(a) if a else None),
            "smd_before": _fmt(_smd(treated, b)),
            "smd_after": _fmt(_smd(treated, a)),
            "preferred_abs_smd_max": "0.1",
            "maximum_abs_smd": "0.2",
            "research_use_only": 1,
        })
    return out


def _write_dataclasses(rows: Iterable[object], path: Path) -> None:
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    names = [f.name for f in fields(rows[0])]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=names)
        w.writeheader()
        for row in rows:
            w.writerow(asdict(row))


def _write_dicts(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def build(
    *,
    events_path: Path,
    feature_vectors: Path,
    metadata_path: Path,
    output_dir: Path,
    event_timezone: str = "America/New_York",
    controls_per_event: int = 3,
    min_controls: int = 3,
    max_component_z: float = 2.5,
    require_same_sector: bool = True,
    match_scheduled_event: bool = True,
    min_feature_status: str = "partial",
    covariates: tuple[str, ...] = DEFAULT_NUMERIC_COVARIATES,
    exclusions_path: Path | None = None,
) -> dict:
    covariates = validate_covariates(covariates)
    events = load_events(events_path, event_timezone)
    features_exact, features_by_local = load_features(feature_vectors, min_status=min_feature_status)
    metadata = load_metadata(metadata_path, covariates)
    exclusions = load_exclusions(exclusions_path)

    matches, summaries, raw_balance = generate_matches(
        events=events,
        features_by_local=features_by_local,
        features_exact=features_exact,
        metadata=metadata,
        covariates=covariates,
        controls_per_event=controls_per_event,
        min_controls=min_controls,
        max_component_z=max_component_z,
        require_same_sector=require_same_sector,
        match_scheduled_event=match_scheduled_event,
        exclusions=exclusions,
    )
    balance = balance_diagnostics(raw_balance, covariates)

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_dataclasses(matches, output_dir / "matched_controls.csv")
    _write_dataclasses(summaries, output_dir / "match_events.csv")
    _write_dicts(balance, output_dir / "match_balance.csv")

    status_counts = defaultdict(int)
    for row in summaries:
        status_counts[row.event_status] += 1
    quality_counts = defaultdict(int)
    for row in matches:
        quality_counts[row.match_quality] += 1

    inputs = [
        {"kind": "historical_events", "path": str(events_path), "sha256": _sha256(events_path)},
        {"kind": "feature_vectors", "path": str(feature_vectors), "sha256": _sha256(feature_vectors)},
        {"kind": "point_in_time_metadata", "path": str(metadata_path), "sha256": _sha256(metadata_path)},
    ]
    if exclusions_path is not None:
        inputs.append({"kind": "control_exclusions", "path": str(exclusions_path), "sha256": _sha256(exclusions_path)})

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "purpose": "Point-in-time matched-control construction for historical market-surveillance research; not a trading signal.",
        "matching_policy": {
            "controls_per_event": controls_per_event,
            "minimum_controls": min_controls,
            "same_local_date_and_minute_required": True,
            "same_sector_required_when_available": require_same_sector,
            "same_index_bucket_required_when_both_available": True,
            "same_scheduled_event_status_required_when_available": match_scheduled_event,
            "known_positive_event_controls_excluded": True,
            "min_feature_status": min_feature_status,
            "max_standardized_component_distance": max_component_z,
            "numeric_covariates": list(covariates),
            "distance": "Root-mean-square robust standardized pre-event covariate distance; market-cap/price/liquidity-like covariates use log1p transforms.",
        },
        "lookahead_policy": (
            "Control selection uses only metadata effective at or before the treated event timestamp. "
            "Step-4 anomaly features are used only to confirm window availability and are never used in the match distance. "
            "Future prices, announcement reactions, earnings surprises, enforcement outcomes, hacked/prosecuted labels for candidate selection, and unreleased content are prohibited."
        ),
        "inputs": inputs,
        "outputs": {
            "event_count": len(events),
            "matched_control_rows": len(matches),
            "event_status_counts": dict(sorted(status_counts.items())),
            "match_quality_counts": dict(sorted(quality_counts.items())),
            "balance_rows": len(balance),
        },
        "balance_policy": {"preferred_abs_smd_max": 0.10, "maximum_abs_smd": 0.20},
        "prohibited_outputs": ["BUY", "SELL", "bullish", "bearish", "expected_return", "target_price", "position_size", "order"],
    }
    (output_dir / "match_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    p = argparse.ArgumentParser(description="Build point-in-time matched controls for historical surveillance events.")
    p.add_argument("--events", type=Path, required=True)
    p.add_argument("--feature-vectors", type=Path, required=True)
    p.add_argument("--metadata", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--event-timezone", default="America/New_York")
    p.add_argument("--controls-per-event", type=int, default=3)
    p.add_argument("--min-controls", type=int, default=3)
    p.add_argument("--max-component-z", type=float, default=2.5)
    p.add_argument("--min-feature-status", choices=sorted(STATUS_RANK), default="partial")
    p.add_argument("--no-require-same-sector", action="store_true")
    p.add_argument("--no-match-scheduled-event", action="store_true")
    p.add_argument("--covariates", default=",".join(DEFAULT_NUMERIC_COVARIATES))
    p.add_argument("--exclusions", type=Path)
    args = p.parse_args()
    manifest = build(
        events_path=args.events,
        feature_vectors=args.feature_vectors,
        metadata_path=args.metadata,
        output_dir=args.output_dir,
        event_timezone=args.event_timezone,
        controls_per_event=args.controls_per_event,
        min_controls=args.min_controls,
        max_component_z=args.max_component_z,
        require_same_sector=not args.no_require_same_sector,
        match_scheduled_event=not args.no_match_scheduled_event,
        min_feature_status=args.min_feature_status,
        covariates=tuple(x.strip() for x in args.covariates.split(",") if x.strip()),
        exclusions_path=args.exclusions,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
