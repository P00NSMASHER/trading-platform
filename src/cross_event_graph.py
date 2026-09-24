from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

SCHEMA_VERSION = "0.14.0"

ALLOWED_NODE_TYPES = {
    "case",
    "event",
    "issuer",
    "security",
    "person",
    "organization",
    "regulatory_body",
}

ALLOWED_EDGE_TYPES = {
    "case_contains_event",
    "subject_of_case",
    "event_concerns_issuer",
    "event_observed_in_security",
    "issuer_has_security",
    "peer_of",
    "related_security",
    "advisor_to",
    "employed_by",
    "tipper_to_tippee",
    "supplier_of",
    "counterparty_to",
}

SYMMETRIC_EDGE_TYPES = {"peer_of", "related_security"}

ALLOWED_SOURCE_CLASSES = {
    "adjudicated_public",
    "official_public",
    "public_filing",
    "public_research",
    "licensed_authorized",
    "synthetic",
}

FORBIDDEN_SOURCE_CLASSES = {
    "live_stolen",
    "stolen_private",
    "leaked_credential",
    "active_credential",
    "accidental_private",
    "unverified_private",
}

ALLOWED_ADJUDICATION_STATUS = {
    "final_judgment",
    "guilty_plea",
    "jury_liability",
    "settled",
    "charged",
    "public_filing",
    "not_applicable",
    "synthetic",
}

# Confidence is provenance confidence, not a probability of wrongdoing.
DEFAULT_CONFIDENCE = {
    "final_judgment": 1.00,
    "guilty_plea": 1.00,
    "jury_liability": 1.00,
    "settled": 0.85,
    "charged": 0.55,
    "public_filing": 0.80,
    "not_applicable": 0.75,
    "synthetic": 0.50,
}

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
class GraphNode:
    node_id: str
    node_type: str
    label: str
    symbol: str = ""
    attributes_json: str = "{}"
    research_use_only: int = 1


@dataclass(frozen=True)
class GraphEdge:
    edge_id: str
    src_id: str
    dst_id: str
    edge_type: str
    valid_from: str
    valid_to: str
    observed_at: str
    public_at: str
    source_class: str
    source_reference: str
    adjudication_status: str
    confidence: float
    research_use_only: int = 1


@dataclass(frozen=True)
class RelatedSecurity:
    seed_security_id: str
    security_id: str
    symbol: str
    hop_count: int
    relationship_path: str
    node_path: str
    path_confidence: float
    visibility_mode: str
    research_use_only: int = 1


def _clean(v: str | None) -> str:
    return (v or "").strip()


def _parse_ts(v: str | None, *, allow_blank: bool = False) -> datetime | None:
    raw = _clean(v)
    if not raw:
        if allow_blank:
            return None
        raise ValueError("blank timestamp")
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"timestamp must include timezone: {raw!r}")
    return dt.astimezone(timezone.utc)


def _ts_key(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _bool1(v: str | int | bool | None) -> int:
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return 1 if v == 1 else 0
    return 1 if _clean(str(v)).lower() in {"1", "true", "yes"} else 0


def _confidence(raw: str | None, status: str) -> float:
    text = _clean(raw)
    val = DEFAULT_CONFIDENCE[status] if not text else float(text)
    if not math.isfinite(val) or not 0.0 <= val <= 1.0:
        raise ValueError("edge confidence must be finite and in [0,1]")
    return val


def _validate_attributes(raw: str) -> str:
    raw = _clean(raw) or "{}"
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError("attributes_json must encode an object")
    lowered = {str(k).lower() for k in obj}
    bad = sorted(lowered.intersection(PROHIBITED_OUTPUT_FIELDS))
    if bad:
        raise ValueError(f"prohibited trading/output attributes: {bad}")
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def load_nodes(path: Path) -> list[GraphNode]:
    out: list[GraphNode] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {"node_id", "node_type", "label"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"nodes missing columns: {sorted(missing)}")
        for line_no, row in enumerate(reader, 2):
            node_id = _clean(row.get("node_id"))
            node_type = _clean(row.get("node_type")).lower()
            if not node_id or node_id in seen:
                raise ValueError(f"nodes row {line_no}: missing/duplicate node_id")
            if node_type not in ALLOWED_NODE_TYPES:
                raise ValueError(f"nodes row {line_no}: unsupported node_type={node_type!r}")
            if _bool1(row.get("research_use_only", "1")) != 1:
                raise ValueError(f"nodes row {line_no}: research_use_only must be true")
            symbol = _clean(row.get("symbol")).upper()
            if node_type == "security" and not symbol:
                raise ValueError(f"nodes row {line_no}: security requires symbol")
            out.append(GraphNode(
                node_id=node_id,
                node_type=node_type,
                label=_clean(row.get("label")) or node_id,
                symbol=symbol,
                attributes_json=_validate_attributes(row.get("attributes_json", "{}")),
            ))
            seen.add(node_id)
    if not out:
        raise ValueError("node file contains no rows")
    return out


def load_edges(path: Path, node_ids: set[str]) -> list[GraphEdge]:
    out: list[GraphEdge] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {
            "edge_id", "src_id", "dst_id", "edge_type", "observed_at", "public_at",
            "source_class", "source_reference", "adjudication_status",
        }
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"edges missing columns: {sorted(missing)}")
        for line_no, row in enumerate(reader, 2):
            edge_id = _clean(row.get("edge_id"))
            src = _clean(row.get("src_id"))
            dst = _clean(row.get("dst_id"))
            et = _clean(row.get("edge_type")).lower()
            source_class = _clean(row.get("source_class")).lower()
            status = _clean(row.get("adjudication_status")).lower()
            if not edge_id or edge_id in seen:
                raise ValueError(f"edges row {line_no}: missing/duplicate edge_id")
            if src not in node_ids or dst not in node_ids:
                raise ValueError(f"edges row {line_no}: unknown node reference")
            if src == dst:
                raise ValueError(f"edges row {line_no}: self-edge not allowed")
            if et not in ALLOWED_EDGE_TYPES:
                raise ValueError(f"edges row {line_no}: unsupported edge_type={et!r}")
            if source_class in FORBIDDEN_SOURCE_CLASSES or source_class not in ALLOWED_SOURCE_CLASSES:
                raise ValueError(f"edges row {line_no}: prohibited/unsupported source_class={source_class!r}")
            if status not in ALLOWED_ADJUDICATION_STATUS:
                raise ValueError(f"edges row {line_no}: invalid adjudication_status={status!r}")
            if _bool1(row.get("research_use_only", "1")) != 1:
                raise ValueError(f"edges row {line_no}: research_use_only must be true")
            observed = _parse_ts(row.get("observed_at"))
            public = _parse_ts(row.get("public_at"))
            vfrom = _parse_ts(row.get("valid_from"), allow_blank=True)
            vto = _parse_ts(row.get("valid_to"), allow_blank=True)
            # public_at is the time the relationship/source became public; observed_at is the
            # historical time the underlying relationship/event is associated with. Either can
            # precede the other (for example, an employment relationship published in a bio
            # before a later event). Live visibility is enforced at query time using public_at.
            if vfrom and vto and vto < vfrom:
                raise ValueError(f"edges row {line_no}: valid_to precedes valid_from")
            out.append(GraphEdge(
                edge_id=edge_id,
                src_id=src,
                dst_id=dst,
                edge_type=et,
                valid_from=_ts_key(vfrom),
                valid_to=_ts_key(vto),
                observed_at=_ts_key(observed),
                public_at=_ts_key(public),
                source_class=source_class,
                source_reference=_clean(row.get("source_reference")),
                adjudication_status=status,
                confidence=_confidence(row.get("confidence"), status),
            ))
            seen.add(edge_id)
    if not out:
        raise ValueError("edge file contains no rows")
    return out


def init_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE IF NOT EXISTS graph_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS nodes (
            node_id TEXT PRIMARY KEY,
            node_type TEXT NOT NULL,
            label TEXT NOT NULL,
            symbol TEXT NOT NULL DEFAULT '',
            attributes_json TEXT NOT NULL,
            research_use_only INTEGER NOT NULL CHECK(research_use_only = 1)
        );
        CREATE TABLE IF NOT EXISTS edges (
            edge_id TEXT PRIMARY KEY,
            src_id TEXT NOT NULL REFERENCES nodes(node_id),
            dst_id TEXT NOT NULL REFERENCES nodes(node_id),
            edge_type TEXT NOT NULL,
            valid_from TEXT NOT NULL DEFAULT '',
            valid_to TEXT NOT NULL DEFAULT '',
            observed_at TEXT NOT NULL,
            public_at TEXT NOT NULL,
            source_class TEXT NOT NULL,
            source_reference TEXT NOT NULL,
            adjudication_status TEXT NOT NULL,
            confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
            research_use_only INTEGER NOT NULL CHECK(research_use_only = 1)
        );
        CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src_id);
        CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst_id);
        CREATE INDEX IF NOT EXISTS idx_edges_public ON edges(public_at);

        CREATE TRIGGER IF NOT EXISTS nodes_no_update BEFORE UPDATE ON nodes
        BEGIN SELECT RAISE(ABORT, 'graph nodes are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS nodes_no_delete BEFORE DELETE ON nodes
        BEGIN SELECT RAISE(ABORT, 'graph nodes are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS edges_no_update BEFORE UPDATE ON edges
        BEGIN SELECT RAISE(ABORT, 'graph edges are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS edges_no_delete BEFORE DELETE ON edges
        BEGIN SELECT RAISE(ABORT, 'graph edges are append-only'); END;
        """
    )
    return conn


def build_graph_db(*, nodes_csv: Path, edges_csv: Path, db_path: Path, manifest_path: Path | None = None) -> dict:
    nodes = load_nodes(nodes_csv)
    edges = load_edges(edges_csv, {n.node_id for n in nodes})
    if db_path.exists():
        db_path.unlink()
    conn = init_db(db_path)
    try:
        with conn:
            conn.execute("INSERT OR REPLACE INTO graph_meta(key,value) VALUES (?,?)", ("schema_version", SCHEMA_VERSION))
            conn.executemany(
                "INSERT INTO nodes(node_id,node_type,label,symbol,attributes_json,research_use_only) VALUES (:node_id,:node_type,:label,:symbol,:attributes_json,:research_use_only)",
                [asdict(n) for n in nodes],
            )
            conn.executemany(
                """INSERT INTO edges(edge_id,src_id,dst_id,edge_type,valid_from,valid_to,observed_at,public_at,source_class,source_reference,adjudication_status,confidence,research_use_only)
                   VALUES (:edge_id,:src_id,:dst_id,:edge_type,:valid_from,:valid_to,:observed_at,:public_at,:source_class,:source_reference,:adjudication_status,:confidence,:research_use_only)""",
                [asdict(e) for e in edges],
            )
    finally:
        conn.close()
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "research_use_only": True,
        "nodes": len(nodes),
        "edges": len(edges),
        "security_nodes": sum(n.node_type == "security" for n in nodes),
        "case_nodes": sum(n.node_type == "case" for n in nodes),
        "source_policy": {
            "allowed_source_classes": sorted(ALLOWED_SOURCE_CLASSES),
            "forbidden_source_classes": sorted(FORBIDDEN_SOURCE_CLASSES),
            "live_stolen_or_leaked_inputs_allowed": False,
        },
        "point_in_time_policy": {
            "live_surveillance_uses_public_at": True,
            "historical_forensics_may_use_later_adjudication": True,
            "future_enforcement_information_not_live_visible": True,
        },
        "input_sha256": {
            nodes_csv.name: _sha256(nodes_csv),
            edges_csv.name: _sha256(edges_csv),
        },
        "db_sha256": _sha256(db_path),
        "prohibited_outputs": sorted(PROHIBITED_OUTPUT_FIELDS),
    }
    if manifest_path:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def _visible_edge(row: sqlite3.Row, *, as_of: datetime, mode: str) -> bool:
    if mode not in {"live_surveillance", "historical_forensics"}:
        raise ValueError("mode must be live_surveillance or historical_forensics")
    public_at = _parse_ts(row["public_at"])
    observed_at = _parse_ts(row["observed_at"])
    # An edge cannot exist in the point-in-time graph before the underlying
    # relationship/event was observed. Historical-forensics mode may use a
    # later-public adjudication to explain an earlier event, but it must never
    # back-project a genuinely later event into an earlier timestamp.
    if observed_at and observed_at > as_of:
        return False
    if mode == "live_surveillance" and public_at and public_at > as_of:
        return False
    vfrom = _parse_ts(row["valid_from"], allow_blank=True)
    vto = _parse_ts(row["valid_to"], allow_blank=True)
    if vfrom and vfrom > as_of:
        return False
    if vto and vto < as_of:
        return False
    return True


def _adjacent(conn: sqlite3.Connection, node_id: str, *, as_of: datetime, mode: str, allowed_edges: set[str] | None = None) -> list[tuple[str, sqlite3.Row]]:
    rows = conn.execute("SELECT * FROM edges WHERE src_id=? OR dst_id=?", (node_id, node_id)).fetchall()
    out: list[tuple[str, sqlite3.Row]] = []
    for r in rows:
        if allowed_edges and r["edge_type"] not in allowed_edges:
            continue
        if not _visible_edge(r, as_of=as_of, mode=mode):
            continue
        other = r["dst_id"] if r["src_id"] == node_id else r["src_id"]
        # Directional relations may only be traversed backwards for entity discovery, never interpreted as a trade direction.
        out.append((other, r))
    return out


def related_securities(
    *,
    db_path: Path,
    seed_security_id: str,
    as_of: str,
    mode: str = "live_surveillance",
    max_hops: int = 3,
    min_confidence: float = 0.0,
) -> list[RelatedSecurity]:
    if max_hops < 1 or max_hops > 5:
        raise ValueError("max_hops must be between 1 and 5")
    as_of_dt = _parse_ts(as_of)
    assert as_of_dt is not None
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        seed = conn.execute("SELECT * FROM nodes WHERE node_id=?", (seed_security_id,)).fetchone()
        if not seed or seed["node_type"] != "security":
            raise ValueError("seed_security_id must identify a security node")
        best: dict[str, RelatedSecurity] = {}
        queue: list[tuple[str, list[str], list[str], float]] = [(seed_security_id, [seed_security_id], [], 1.0)]
        seen_depth: dict[str, int] = {seed_security_id: 0}
        while queue:
            current, node_path, edge_path, confidence = queue.pop(0)
            depth = len(edge_path)
            if depth >= max_hops:
                continue
            for other, edge in _adjacent(conn, current, as_of=as_of_dt, mode=mode):
                next_depth = depth + 1
                path_conf = confidence * float(edge["confidence"]) * (0.92 if next_depth > 1 else 1.0)
                if path_conf < min_confidence:
                    continue
                prior_depth = seen_depth.get(other)
                if prior_depth is None or next_depth < prior_depth:
                    seen_depth[other] = next_depth
                    queue.append((other, node_path + [other], edge_path + [edge["edge_type"]], path_conf))
                nrow = conn.execute("SELECT * FROM nodes WHERE node_id=?", (other,)).fetchone()
                if nrow and nrow["node_type"] == "security" and other != seed_security_id:
                    candidate = RelatedSecurity(
                        seed_security_id=seed_security_id,
                        security_id=other,
                        symbol=nrow["symbol"],
                        hop_count=next_depth,
                        relationship_path=">".join(edge_path + [edge["edge_type"]]),
                        node_path=">".join(node_path + [other]),
                        path_confidence=round(path_conf, 8),
                        visibility_mode=mode,
                    )
                    old = best.get(other)
                    if old is None or (candidate.hop_count, -candidate.path_confidence) < (old.hop_count, -old.path_confidence):
                        best[other] = candidate
        return sorted(best.values(), key=lambda x: (x.hop_count, -x.path_confidence, x.security_id))
    finally:
        conn.close()


def case_contamination_blocklist(
    *,
    db_path: Path,
    case_id: str,
    as_of: str,
    mode: str = "historical_forensics",
    max_hops: int = 4,
) -> list[dict]:
    as_of_dt = _parse_ts(as_of)
    assert as_of_dt is not None
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        case = conn.execute("SELECT * FROM nodes WHERE node_id=?", (case_id,)).fetchone()
        if not case or case["node_type"] != "case":
            raise ValueError("case_id must identify a case node")
        queue = [(case_id, 0)]
        visited = {case_id}
        securities: dict[str, int] = {}
        while queue:
            node, depth = queue.pop(0)
            if depth >= max_hops:
                continue
            for other, _edge in _adjacent(conn, node, as_of=as_of_dt, mode=mode):
                if other in visited:
                    continue
                visited.add(other)
                nrow = conn.execute("SELECT * FROM nodes WHERE node_id=?", (other,)).fetchone()
                if not nrow:
                    continue
                nd = depth + 1
                if nrow["node_type"] == "security":
                    securities[other] = min(securities.get(other, 999), nd)
                queue.append((other, nd))
        return [
            {"case_id": case_id, "security_id": sid, "symbol": conn.execute("SELECT symbol FROM nodes WHERE node_id=?", (sid,)).fetchone()[0], "hop_count": hop, "exclude_from_controls": 1, "research_use_only": 1}
            for sid, hop in sorted(securities.items(), key=lambda kv: (kv[1], kv[0]))
        ]
    finally:
        conn.close()


def case_similarity(*, db_path: Path, case_id: str, as_of: str, mode: str = "historical_forensics") -> list[dict]:
    as_of_dt = _parse_ts(as_of)
    assert as_of_dt is not None
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cases = conn.execute("SELECT * FROM nodes WHERE node_type='case'").fetchall()
        target = next((r for r in cases if r["node_id"] == case_id), None)
        if not target:
            raise ValueError("case_id must identify a case node")

        def sig(cid: str) -> set[str]:
            s: set[str] = set()
            cnode = conn.execute("SELECT * FROM nodes WHERE node_id=?", (cid,)).fetchone()
            attrs = json.loads(cnode["attributes_json"])
            for k in ("mechanism", "information_type", "instrument"):
                if attrs.get(k):
                    s.add(f"{k}:{str(attrs[k]).lower()}")
            for other, edge in _adjacent(conn, cid, as_of=as_of_dt, mode=mode):
                nrow = conn.execute("SELECT node_type,attributes_json FROM nodes WHERE node_id=?", (other,)).fetchone()
                s.add(f"edge:{edge['edge_type']}")
                if nrow:
                    s.add(f"node:{nrow['node_type']}")
            return s

        if not _adjacent(conn, case_id, as_of=as_of_dt, mode=mode):
            raise ValueError("case_id is not visible/observed at as_of under the selected mode")
        target_sig = sig(case_id)
        out = []
        for row in cases:
            cid = row["node_id"]
            if cid == case_id:
                continue
            # Do not emit future/unobserved cases merely because their node metadata
            # already exists in the database. At least one case edge must be visible
            # under the same point-in-time semantics.
            if not _adjacent(conn, cid, as_of=as_of_dt, mode=mode):
                continue
            other_sig = sig(cid)
            union = target_sig | other_sig
            score = len(target_sig & other_sig) / len(union) if union else 0.0
            out.append({
                "case_id": cid,
                "label": row["label"],
                "structural_similarity": round(score, 8),
                "shared_signature_count": len(target_sig & other_sig),
                "research_use_only": 1,
            })
        return sorted(out, key=lambda r: (-r["structural_similarity"], r["case_id"]))
    finally:
        conn.close()


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(rows[0].keys())
    low = {f.lower() for f in fields}
    bad = sorted(low.intersection(PROHIBITED_OUTPUT_FIELDS))
    if bad:
        raise ValueError(f"prohibited output fields: {bad}")
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def graph_self_check(db_path: Path) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        fk = conn.execute("PRAGMA foreign_key_check").fetchall()
        source_classes = {r[0] for r in conn.execute("SELECT DISTINCT source_class FROM edges")}
        forbidden_found = sorted(source_classes.intersection(FORBIDDEN_SOURCE_CLASSES))
        bad_research = conn.execute("SELECT COUNT(*) FROM nodes WHERE research_use_only != 1").fetchone()[0] + conn.execute("SELECT COUNT(*) FROM edges WHERE research_use_only != 1").fetchone()[0]
        return {
            "ok": integrity == "ok" and not fk and not forbidden_found and bad_research == 0,
            "integrity_check": integrity,
            "foreign_key_violations": len(fk),
            "forbidden_source_classes_found": forbidden_found,
            "non_research_rows": bad_research,
            "nodes": conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
            "edges": conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
            "db_sha256": _sha256(db_path),
        }
    finally:
        conn.close()


def _cmd_build(args: argparse.Namespace) -> None:
    manifest = build_graph_db(nodes_csv=Path(args.nodes), edges_csv=Path(args.edges), db_path=Path(args.db), manifest_path=Path(args.manifest))
    print(json.dumps(manifest, indent=2, sort_keys=True))


def _cmd_expand(args: argparse.Namespace) -> None:
    rows = related_securities(db_path=Path(args.db), seed_security_id=args.seed_security, as_of=args.as_of, mode=args.mode, max_hops=args.max_hops, min_confidence=args.min_confidence)
    _write_csv(Path(args.output), [asdict(r) for r in rows])
    print(json.dumps({"rows": len(rows), "output": args.output}, indent=2))


def _cmd_blocklist(args: argparse.Namespace) -> None:
    rows = case_contamination_blocklist(db_path=Path(args.db), case_id=args.case_id, as_of=args.as_of, mode=args.mode, max_hops=args.max_hops)
    _write_csv(Path(args.output), rows)
    print(json.dumps({"rows": len(rows), "output": args.output}, indent=2))


def _cmd_similar(args: argparse.Namespace) -> None:
    rows = case_similarity(db_path=Path(args.db), case_id=args.case_id, as_of=args.as_of, mode=args.mode)
    _write_csv(Path(args.output), rows)
    print(json.dumps({"rows": len(rows), "output": args.output}, indent=2))


def _cmd_check(args: argparse.Namespace) -> None:
    report = graph_self_check(Path(args.db))
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["ok"]:
        raise SystemExit(2)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Private cross-event intelligence graph for historical market-surveillance research")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build")
    b.add_argument("--nodes", required=True)
    b.add_argument("--edges", required=True)
    b.add_argument("--db", required=True)
    b.add_argument("--manifest", required=True)
    b.set_defaults(func=_cmd_build)

    e = sub.add_parser("expand")
    e.add_argument("--db", required=True)
    e.add_argument("--seed-security", required=True)
    e.add_argument("--as-of", required=True)
    e.add_argument("--mode", choices=["live_surveillance", "historical_forensics"], default="live_surveillance")
    e.add_argument("--max-hops", type=int, default=3)
    e.add_argument("--min-confidence", type=float, default=0.0)
    e.add_argument("--output", required=True)
    e.set_defaults(func=_cmd_expand)

    c = sub.add_parser("blocklist")
    c.add_argument("--db", required=True)
    c.add_argument("--case-id", required=True)
    c.add_argument("--as-of", required=True)
    c.add_argument("--mode", choices=["live_surveillance", "historical_forensics"], default="historical_forensics")
    c.add_argument("--max-hops", type=int, default=4)
    c.add_argument("--output", required=True)
    c.set_defaults(func=_cmd_blocklist)

    s = sub.add_parser("similar-cases")
    s.add_argument("--db", required=True)
    s.add_argument("--case-id", required=True)
    s.add_argument("--as-of", required=True)
    s.add_argument("--mode", choices=["live_surveillance", "historical_forensics"], default="historical_forensics")
    s.add_argument("--output", required=True)
    s.set_defaults(func=_cmd_similar)

    q = sub.add_parser("self-check")
    q.add_argument("--db", required=True)
    q.set_defaults(func=_cmd_check)
    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
