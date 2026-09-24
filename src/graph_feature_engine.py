from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sqlite3
import statistics
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import cross_event_graph as ceg

SCHEMA_VERSION = "0.12.0"

MULTIVARIATE_ANOMALY_THRESHOLD = 2.0
EQUITY_VOLUME_ANOMALY_THRESHOLD = 2.0
OPTION_VOLUME_ANOMALY_THRESHOLD = 2.0
SPREAD_WIDEN_THRESHOLD = 1.5

PROHIBITED_OUTPUT_FIELDS = {
    "buy",
    "sell",
    "trade_direction",
    "expected_return",
    "target_price",
    "position_size",
    "order_quantity",
    "entry_price",
    "exit_price",
}


@dataclass(frozen=True)
class GraphAwareFeatureVector:
    minute_ts_utc: str
    symbol: str
    security_id: str
    visibility_mode: str
    graph_feature_status: str
    seed_feature_status: str

    related_security_count: int
    direct_related_security_count: int
    second_hop_related_security_count: int
    confidence_weighted_breadth: str
    max_path_confidence: str
    mean_path_confidence: str

    related_feature_count: int
    anomalous_related_count: int
    anomalous_related_fraction: str
    synchronized_equity_volume_anomaly_count: int
    synchronized_option_volume_anomaly_count: int
    synchronized_spread_widen_count: int

    max_related_multivariate_l2: str
    mean_related_multivariate_l2: str
    confidence_weighted_peer_anomaly: str
    propagation_strength: str
    min_anomalous_hop: str
    mean_anomalous_hop: str

    prior_visible_case_count: int
    prior_case_similarity_max: str
    prior_case_similarity_mean: str

    graph_db_sha256: str
    feature_input_sha256: str
    research_use_only: int = 1


def _clean(v: str | None) -> str:
    return (v or "").strip()


def _parse_ts(v: str) -> datetime:
    raw = _clean(v)
    if not raw:
        raise ValueError("blank timestamp")
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"timestamp must include timezone: {raw!r}")
    return dt.astimezone(timezone.utc)


def _ts_key(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_float(v: str | None) -> float | None:
    raw = _clean(v)
    if not raw:
        return None
    try:
        x = float(raw)
    except Exception as exc:
        raise ValueError(f"invalid numeric value {raw!r}") from exc
    if not math.isfinite(x):
        raise ValueError(f"non-finite numeric value {raw!r}")
    return x


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


def load_feature_vectors(path: Path) -> dict[tuple[str, str], dict]:
    out: dict[tuple[str, str], dict] = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {
            "minute_ts_utc",
            "symbol",
            "feature_status",
            "equity_volume_z",
            "equity_spread_z",
            "option_volume_z",
            "multivariate_l2",
        }
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"feature file missing required columns: {sorted(missing)}")
        lower_fields = {str(x).lower() for x in (reader.fieldnames or [])}
        bad = sorted(lower_fields.intersection(PROHIBITED_OUTPUT_FIELDS))
        if bad:
            raise ValueError(f"feature input contains prohibited trading/output fields: {bad}")
        for line_no, row in enumerate(reader, 2):
            symbol = _clean(row.get("symbol")).upper()
            if not symbol:
                raise ValueError(f"feature row {line_no}: blank symbol")
            ts = _ts_key(_parse_ts(row.get("minute_ts_utc", "")))
            key = (symbol, ts)
            if key in out:
                raise ValueError(f"duplicate feature vector for {key}")
            out[key] = {
                "symbol": symbol,
                "minute_ts_utc": ts,
                "feature_status": _clean(row.get("feature_status")).lower() or "insufficient",
                "equity_volume_z": _parse_float(row.get("equity_volume_z")),
                "equity_spread_z": _parse_float(row.get("equity_spread_z")),
                "option_volume_z": _parse_float(row.get("option_volume_z")),
                "multivariate_l2": _parse_float(row.get("multivariate_l2")),
            }
    return out


def _security_map(conn: sqlite3.Connection) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for row in conn.execute("SELECT node_id,symbol FROM nodes WHERE node_type='security'"):
        sym = _clean(row["symbol"]).upper()
        if not sym:
            continue
        out.setdefault(sym, []).append(row["node_id"])
    return out


def _neighborhood_signature(
    conn: sqlite3.Connection,
    node_id: str,
    *,
    as_of: datetime,
    mode: str,
    max_hops: int,
) -> set[str]:
    sig: set[str] = set()
    queue: list[tuple[str, int]] = [(node_id, 0)]
    visited = {node_id}
    while queue:
        current, depth = queue.pop(0)
        if depth >= max_hops:
            continue
        for other, edge in ceg._adjacent(conn, current, as_of=as_of, mode=mode):
            sig.add(f"edge:{edge['edge_type']}")
            nrow = conn.execute("SELECT node_type,attributes_json FROM nodes WHERE node_id=?", (other,)).fetchone()
            if nrow:
                sig.add(f"node:{nrow['node_type']}")
                try:
                    attrs = json.loads(nrow["attributes_json"] or "{}")
                except Exception:
                    attrs = {}
                if nrow["node_type"] == "issuer" and attrs.get("sector"):
                    sig.add(f"sector:{str(attrs['sector']).strip().lower()}")
            if other not in visited:
                visited.add(other)
                queue.append((other, depth + 1))
    return sig


def _prior_case_similarity(
    conn: sqlite3.Connection,
    security_id: str,
    *,
    as_of: datetime,
    mode: str,
) -> tuple[int, float | None, float | None]:
    seed_sig = _neighborhood_signature(conn, security_id, as_of=as_of, mode=mode, max_hops=2)
    scores: list[float] = []
    visible_count = 0
    for row in conn.execute("SELECT node_id FROM nodes WHERE node_type='case' ORDER BY node_id"):
        cid = row["node_id"]
        # A case is eligible only if at least one case edge is visible under the same
        # point-in-time rules. In live mode this excludes later-public enforcement facts.
        if not ceg._adjacent(conn, cid, as_of=as_of, mode=mode):
            continue
        visible_count += 1
        case_sig = _neighborhood_signature(conn, cid, as_of=as_of, mode=mode, max_hops=4)
        union = seed_sig | case_sig
        scores.append(len(seed_sig & case_sig) / len(union) if union else 0.0)
    if not scores:
        return 0, None, None
    return visible_count, max(scores), statistics.fmean(scores)


def _weighted_mean(pairs: Iterable[tuple[float, float]]) -> float | None:
    vals = [(v, w) for v, w in pairs if math.isfinite(v) and math.isfinite(w) and w > 0]
    if not vals:
        return None
    denom = sum(w for _, w in vals)
    return sum(v * w for v, w in vals) / denom if denom > 0 else None


def _build_one(
    *,
    base: dict,
    security_id: str,
    related: list[ceg.RelatedSecurity],
    all_features: dict[tuple[str, str], dict],
    conn: sqlite3.Connection,
    graph_hash: str,
    feature_hash: str,
    mode: str,
) -> GraphAwareFeatureVector:
    ts = base["minute_ts_utc"]
    related_count = len(related)
    direct_count = sum(r.hop_count == 1 for r in related)
    second_count = sum(r.hop_count == 2 for r in related)
    breadth = sum(r.path_confidence / max(r.hop_count, 1) for r in related)
    path_conf = [r.path_confidence for r in related]

    peers: list[tuple[ceg.RelatedSecurity, dict]] = []
    for rel in related:
        row = all_features.get((rel.symbol.upper(), ts))
        if row is not None:
            peers.append((rel, row))

    peer_l2 = [(rel, row["multivariate_l2"]) for rel, row in peers if row.get("multivariate_l2") is not None]
    anomalous = [(rel, x) for rel, x in peer_l2 if x >= MULTIVARIATE_ANOMALY_THRESHOLD]
    anomaly_fraction = len(anomalous) / len(peer_l2) if peer_l2 else None

    eq_sync = sum((row.get("equity_volume_z") is not None and row["equity_volume_z"] >= EQUITY_VOLUME_ANOMALY_THRESHOLD) for _, row in peers)
    op_sync = sum((row.get("option_volume_z") is not None and row["option_volume_z"] >= OPTION_VOLUME_ANOMALY_THRESHOLD) for _, row in peers)
    spread_sync = sum((row.get("equity_spread_z") is not None and row["equity_spread_z"] >= SPREAD_WIDEN_THRESHOLD) for _, row in peers)

    l2_values = [x for _, x in peer_l2]
    weighted_peer_anomaly = _weighted_mean(
        (
            max(x - MULTIVARIATE_ANOMALY_THRESHOLD, 0.0),
            rel.path_confidence / max(rel.hop_count, 1),
        )
        for rel, x in peer_l2
    )
    seed_l2 = base.get("multivariate_l2")
    propagation = None
    if seed_l2 is not None and weighted_peer_anomaly is not None:
        propagation = max(seed_l2 - MULTIVARIATE_ANOMALY_THRESHOLD, 0.0) * weighted_peer_anomaly

    anomalous_hops = [float(rel.hop_count) for rel, _ in anomalous]
    case_count, case_max, case_mean = _prior_case_similarity(conn, security_id, as_of=_parse_ts(ts), mode=mode)

    if related_count == 0:
        status = "no_related_securities"
    elif not peers:
        status = "no_peer_features"
    elif len(peers) < related_count:
        status = "partial"
    else:
        status = "full"

    return GraphAwareFeatureVector(
        minute_ts_utc=ts,
        symbol=base["symbol"],
        security_id=security_id,
        visibility_mode=mode,
        graph_feature_status=status,
        seed_feature_status=base.get("feature_status", "insufficient"),
        related_security_count=related_count,
        direct_related_security_count=direct_count,
        second_hop_related_security_count=second_count,
        confidence_weighted_breadth=_fmt(breadth),
        max_path_confidence=_fmt(max(path_conf) if path_conf else None),
        mean_path_confidence=_fmt(statistics.fmean(path_conf) if path_conf else None),
        related_feature_count=len(peers),
        anomalous_related_count=len(anomalous),
        anomalous_related_fraction=_fmt(anomaly_fraction),
        synchronized_equity_volume_anomaly_count=int(eq_sync),
        synchronized_option_volume_anomaly_count=int(op_sync),
        synchronized_spread_widen_count=int(spread_sync),
        max_related_multivariate_l2=_fmt(max(l2_values) if l2_values else None),
        mean_related_multivariate_l2=_fmt(statistics.fmean(l2_values) if l2_values else None),
        confidence_weighted_peer_anomaly=_fmt(weighted_peer_anomaly),
        propagation_strength=_fmt(propagation),
        min_anomalous_hop=_fmt(min(anomalous_hops) if anomalous_hops else None),
        mean_anomalous_hop=_fmt(statistics.fmean(anomalous_hops) if anomalous_hops else None),
        prior_visible_case_count=case_count,
        prior_case_similarity_max=_fmt(case_max),
        prior_case_similarity_mean=_fmt(case_mean),
        graph_db_sha256=graph_hash,
        feature_input_sha256=feature_hash,
    )


def build_graph_features(
    *,
    feature_vectors: Path,
    graph_db: Path,
    output_dir: Path,
    mode: str = "live_surveillance",
    max_hops: int = 2,
    min_confidence: float = 0.0,
) -> dict:
    if mode not in {"live_surveillance", "historical_forensics"}:
        raise ValueError("mode must be live_surveillance or historical_forensics")
    if max_hops < 1 or max_hops > 6:
        raise ValueError("max_hops must be between 1 and 6")
    if not 0 <= min_confidence <= 1:
        raise ValueError("min_confidence must be in [0,1]")

    features = load_feature_vectors(feature_vectors)
    graph_hash = _sha256(graph_db)
    feature_hash = _sha256(feature_vectors)

    conn = sqlite3.connect(graph_db)
    conn.row_factory = sqlite3.Row
    try:
        security_map = _security_map(conn)
        output: list[GraphAwareFeatureVector] = []
        for (_symbol, _ts), base in sorted(features.items(), key=lambda kv: (kv[0][1], kv[0][0])):
            symbol = base["symbol"]
            ids = security_map.get(symbol, [])
            if len(ids) == 0:
                output.append(
                    GraphAwareFeatureVector(
                        minute_ts_utc=base["minute_ts_utc"],
                        symbol=symbol,
                        security_id="",
                        visibility_mode=mode,
                        graph_feature_status="no_security_node",
                        seed_feature_status=base.get("feature_status", "insufficient"),
                        related_security_count=0,
                        direct_related_security_count=0,
                        second_hop_related_security_count=0,
                        confidence_weighted_breadth="",
                        max_path_confidence="",
                        mean_path_confidence="",
                        related_feature_count=0,
                        anomalous_related_count=0,
                        anomalous_related_fraction="",
                        synchronized_equity_volume_anomaly_count=0,
                        synchronized_option_volume_anomaly_count=0,
                        synchronized_spread_widen_count=0,
                        max_related_multivariate_l2="",
                        mean_related_multivariate_l2="",
                        confidence_weighted_peer_anomaly="",
                        propagation_strength="",
                        min_anomalous_hop="",
                        mean_anomalous_hop="",
                        prior_visible_case_count=0,
                        prior_case_similarity_max="",
                        prior_case_similarity_mean="",
                        graph_db_sha256=graph_hash,
                        feature_input_sha256=feature_hash,
                    )
                )
                continue
            if len(ids) > 1:
                raise ValueError(f"ambiguous graph security mapping for symbol={symbol!r}: {ids}")
            security_id = ids[0]
            related = ceg.related_securities(
                db_path=graph_db,
                seed_security_id=security_id,
                as_of=base["minute_ts_utc"],
                mode=mode,
                max_hops=max_hops,
                min_confidence=min_confidence,
            )
            output.append(
                _build_one(
                    base=base,
                    security_id=security_id,
                    related=related,
                    all_features=features,
                    conn=conn,
                    graph_hash=graph_hash,
                    feature_hash=feature_hash,
                    mode=mode,
                )
            )
    finally:
        conn.close()

    output_dir.mkdir(parents=True, exist_ok=True)
    out_csv = output_dir / "graph_feature_vectors.csv"
    write_records(output, out_csv)

    status_counts: dict[str, int] = {}
    for row in output:
        status_counts[row.graph_feature_status] = status_counts.get(row.graph_feature_status, 0) + 1

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "purpose": "Point-in-time graph-aware surveillance features; not a trading signal.",
        "research_use_only": True,
        "visibility_mode": mode,
        "max_hops": max_hops,
        "min_confidence": min_confidence,
        "thresholds": {
            "multivariate_l2": MULTIVARIATE_ANOMALY_THRESHOLD,
            "equity_volume_z": EQUITY_VOLUME_ANOMALY_THRESHOLD,
            "option_volume_z": OPTION_VOLUME_ANOMALY_THRESHOLD,
            "spread_widen_z": SPREAD_WIDEN_THRESHOLD,
        },
        "point_in_time_policy": {
            "edge_must_be_observed_by_scoring_time": True,
            "live_mode_requires_public_at_or_before_scoring_time": True,
            "later_enforcement_facts_excluded_from_live_features": True,
            "historical_forensics_may_use_later_public_adjudication_after_underlying_event_time": True,
        },
        "inputs": {
            "feature_vectors": {"path": str(feature_vectors), "sha256": feature_hash},
            "graph_db": {"path": str(graph_db), "sha256": graph_hash},
        },
        "outputs": {
            "rows": len(output),
            "status_counts": dict(sorted(status_counts.items())),
            "path": str(out_csv),
        },
        "prohibited_outputs": sorted(PROHIBITED_OUTPUT_FIELDS),
    }
    (output_dir / "graph_feature_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def write_records(records: Iterable[GraphAwareFeatureVector], path: Path) -> None:
    records = list(records)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not records:
        path.write_text("", encoding="utf-8")
        return
    names = [f.name for f in fields(records[0])]
    bad = sorted({n.lower() for n in names}.intersection(PROHIBITED_OUTPUT_FIELDS))
    if bad:
        raise ValueError(f"prohibited output fields: {bad}")
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=names)
        w.writeheader()
        for row in records:
            w.writerow(asdict(row))


def main() -> None:
    p = argparse.ArgumentParser(description="Build point-in-time graph-aware market-surveillance features")
    p.add_argument("--feature-vectors", type=Path, required=True)
    p.add_argument("--graph-db", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--mode", choices=["live_surveillance", "historical_forensics"], default="live_surveillance")
    p.add_argument("--max-hops", type=int, default=2)
    p.add_argument("--min-confidence", type=float, default=0.0)
    args = p.parse_args()
    manifest = build_graph_features(
        feature_vectors=args.feature_vectors,
        graph_db=args.graph_db,
        output_dir=args.output_dir,
        mode=args.mode,
        max_hops=args.max_hops,
        min_confidence=args.min_confidence,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
