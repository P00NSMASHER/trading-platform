from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import cross_event_graph as ceg

SCHEMA_VERSION = "0.14.0"
CASE_ID = "CASE:SEC-DUBOVOY-2015"
CASE_LABEL = "SEC v. Dubovoy et al. hacked newswire trading scheme"
# The SEC press release says the complaint was unsealed on Aug. 11, 2015 but does
# not provide a release timestamp. 23:59:59Z is deliberately conservative: it
# never makes the enforcement relationship visible earlier than the documented
# public date.
CASE_PUBLIC_AT = "2015-08-11T23:59:59Z"
SEC_SOURCE = "SEC Press Release 2015-163 / Litigation Release 23319"
SEC_SOURCE_URL = "https://www.sec.gov/newsroom/press-releases/2015-163"
RESEARCH_SOURCE = "vgreg/hacked_earnings_jfe Data/TimeOfFirstTrade.csv"
RESEARCH_SOURCE_URL = "https://github.com/vgreg/hacked_earnings_jfe"
NY = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class HistoricalGraphContext:
    event_id: str
    historical_symbol: str
    permno: str
    gvkey: str
    first_trade_local: str
    first_trade_utc: str
    live_case_visible: int
    forensic_case_visible: int
    live_related_security_count: int
    forensic_related_security_count: int
    live_prior_visible_case_count: int
    forensic_prior_visible_case_count: int
    enforcement_public_at: str
    research_use_only: int = 1


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _to_utc(local_ts: str) -> str:
    dt = datetime.fromisoformat(local_ts)
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    aware = dt.replace(tzinfo=NY)
    return aware.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def load_historical_events(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    required = {
        "event_id", "permno", "gvkey", "historical_symbol",
        "first_documented_illicit_trade_ts", "sec_documented_trade_flag", "research_use_only",
    }
    if not rows:
        raise ValueError("historical event corpus is empty")
    missing = required.difference(rows[0])
    if missing:
        raise ValueError(f"historical event corpus missing columns: {sorted(missing)}")
    seen = set()
    for i, r in enumerate(rows, 2):
        if r["event_id"] in seen:
            raise ValueError(f"row {i}: duplicate event_id")
        seen.add(r["event_id"])
        if r["sec_documented_trade_flag"] != "1" or r["research_use_only"] != "1":
            raise ValueError(f"row {i}: corpus must be SEC-documented research-only events")
        if not r["historical_symbol"].strip() or not r["permno"].strip() or not r["gvkey"].strip():
            raise ValueError(f"row {i}: missing security identifiers")
        _to_utc(r["first_documented_illicit_trade_ts"])
    return rows


def _write_dataclasses(path: Path, rows: list, fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError("refusing to write empty table")
    first = asdict(rows[0]) if hasattr(rows[0], "__dataclass_fields__") else rows[0]
    fields = fieldnames or list(first)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow(asdict(row) if hasattr(row, "__dataclass_fields__") else row)


def build_graph_tables(events: list[dict], nodes_csv: Path, edges_csv: Path) -> dict:
    nodes: dict[str, ceg.GraphNode] = {}
    edges: list[ceg.GraphEdge] = []

    nodes[CASE_ID] = ceg.GraphNode(
        node_id=CASE_ID,
        node_type="case",
        label=CASE_LABEL,
        attributes_json=json.dumps({
            "mechanism": "hacked_newswire",
            "information_type": "pre_release_earnings",
            "instrument": "stock_options_cfd",
            "case_public_date": "2015-08-11",
            "ground_truth_role": "historical_enforcement_case",
        }, sort_keys=True, separators=(",", ":")),
    )

    # One issuer/security identity node per historical PERMNO/GVKEY, plus one
    # event node per documented first-trade record. The identity relationship is
    # made public no earlier than the event timestamp because that is the oldest
    # public point we can prove from this corpus without inventing a listing date.
    identity_first_seen: dict[tuple[str, str, str], str] = {}
    for r in events:
        symbol = r["historical_symbol"].strip().upper()
        permno = r["permno"].strip()
        gvkey = r["gvkey"].strip()
        local_ts = r["first_documented_illicit_trade_ts"].strip()
        utc_ts = _to_utc(local_ts)
        key = (permno, gvkey, symbol)
        if key not in identity_first_seen or utc_ts < identity_first_seen[key]:
            identity_first_seen[key] = utc_ts

        issuer_id = f"ISS:GVKEY:{gvkey}"
        security_id = f"SEC:PERMNO:{permno}"
        event_node_id = f"EV:{r['event_id']}"
        nodes.setdefault(issuer_id, ceg.GraphNode(
            node_id=issuer_id,
            node_type="issuer",
            label=f"Historical issuer GVKEY {gvkey}",
            attributes_json=json.dumps({"gvkey": gvkey}, sort_keys=True, separators=(",", ":")),
        ))
        nodes.setdefault(security_id, ceg.GraphNode(
            node_id=security_id,
            node_type="security",
            label=f"{symbol} historical security",
            symbol=symbol,
            attributes_json=json.dumps({"permno": permno, "gvkey": gvkey}, sort_keys=True, separators=(",", ":")),
        ))
        nodes[event_node_id] = ceg.GraphNode(
            node_id=event_node_id,
            node_type="event",
            label=f"{symbol} documented first illicit trade {local_ts}",
            attributes_json=json.dumps({
                "event_type": "documented_first_illicit_trade",
                "historical_symbol": symbol,
                "permno": permno,
                "gvkey": gvkey,
            }, sort_keys=True, separators=(",", ":")),
        )

        common = dict(
            valid_from="",
            valid_to="",
            observed_at=utc_ts,
            public_at=CASE_PUBLIC_AT,
            source_class="adjudicated_public",
            source_reference=f"{SEC_SOURCE}; {SEC_SOURCE_URL}; {RESEARCH_SOURCE}; {RESEARCH_SOURCE_URL}",
            adjudication_status="charged",
            confidence=0.95,
            research_use_only=1,
        )
        edges.append(ceg.GraphEdge(
            edge_id=f"GE:CASE:{r['event_id']}", src_id=CASE_ID, dst_id=event_node_id,
            edge_type="case_contains_event", **common,
        ))
        edges.append(ceg.GraphEdge(
            edge_id=f"GE:ISSUER:{r['event_id']}", src_id=event_node_id, dst_id=issuer_id,
            edge_type="event_concerns_issuer", **common,
        ))
        edges.append(ceg.GraphEdge(
            edge_id=f"GE:SECURITY:{r['event_id']}", src_id=event_node_id, dst_id=security_id,
            edge_type="event_observed_in_security", **common,
        ))

    for (permno, gvkey, symbol), first_seen in sorted(identity_first_seen.items()):
        edges.append(ceg.GraphEdge(
            edge_id=f"GE:IDENTITY:{permno}",
            src_id=f"ISS:GVKEY:{gvkey}",
            dst_id=f"SEC:PERMNO:{permno}",
            edge_type="issuer_has_security",
            valid_from="",
            valid_to="",
            observed_at=first_seen,
            public_at=first_seen,
            source_class="public_research",
            source_reference=f"{RESEARCH_SOURCE}; {RESEARCH_SOURCE_URL}",
            adjudication_status="not_applicable",
            confidence=0.90,
            research_use_only=1,
        ))

    _write_dataclasses(nodes_csv, list(nodes.values()))
    _write_dataclasses(edges_csv, edges)
    return {
        "nodes": len(nodes),
        "edges": len(edges),
        "case_nodes": 1,
        "event_nodes": len(events),
        "issuer_nodes": len({r['gvkey'] for r in events}),
        "security_nodes": len({r['permno'] for r in events}),
        "identity_edges": len(identity_first_seen),
        "case_public_at": CASE_PUBLIC_AT,
    }


def _case_visible(conn: sqlite3.Connection, as_of: str, mode: str) -> bool:
    dt = ceg._parse_ts(as_of)
    assert dt is not None
    rows = conn.execute("SELECT * FROM edges WHERE src_id=? OR dst_id=?", (CASE_ID, CASE_ID)).fetchall()
    return any(ceg._visible_edge(r, as_of=dt, mode=mode) for r in rows)


def _visible_case_count(conn: sqlite3.Connection, as_of: str, mode: str) -> int:
    dt = ceg._parse_ts(as_of)
    assert dt is not None
    n = 0
    for row in conn.execute("SELECT node_id FROM nodes WHERE node_type='case'"):
        cid = row[0]
        erows = conn.execute("SELECT * FROM edges WHERE src_id=? OR dst_id=?", (cid, cid)).fetchall()
        if any(ceg._visible_edge(e, as_of=dt, mode=mode) for e in erows):
            n += 1
    return n


def build_context_audit(events: list[dict], graph_db: Path, output_csv: Path) -> dict:
    out: list[HistoricalGraphContext] = []
    conn = sqlite3.connect(graph_db)
    conn.row_factory = sqlite3.Row
    try:
        for r in sorted(events, key=lambda x: x["first_documented_illicit_trade_ts"]):
            permno = r["permno"].strip()
            utc_ts = _to_utc(r["first_documented_illicit_trade_ts"])
            sid = f"SEC:PERMNO:{permno}"
            live_rel = ceg.related_securities(
                db_path=graph_db, seed_security_id=sid, as_of=utc_ts,
                mode="live_surveillance", max_hops=4,
            )
            forensic_rel = ceg.related_securities(
                db_path=graph_db, seed_security_id=sid, as_of=utc_ts,
                mode="historical_forensics", max_hops=4,
            )
            out.append(HistoricalGraphContext(
                event_id=r["event_id"],
                historical_symbol=r["historical_symbol"].upper(),
                permno=permno,
                gvkey=r["gvkey"],
                first_trade_local=r["first_documented_illicit_trade_ts"],
                first_trade_utc=utc_ts,
                live_case_visible=int(_case_visible(conn, utc_ts, "live_surveillance")),
                forensic_case_visible=int(_case_visible(conn, utc_ts, "historical_forensics")),
                live_related_security_count=len(live_rel),
                forensic_related_security_count=len(forensic_rel),
                live_prior_visible_case_count=_visible_case_count(conn, utc_ts, "live_surveillance"),
                forensic_prior_visible_case_count=_visible_case_count(conn, utc_ts, "historical_forensics"),
                enforcement_public_at=CASE_PUBLIC_AT,
            ))
    finally:
        conn.close()
    _write_dataclasses(output_csv, out)
    return {
        "rows": len(out),
        "live_case_visible_rows": sum(x.live_case_visible for x in out),
        "forensic_case_visible_rows": sum(x.forensic_case_visible for x in out),
        "live_rows_with_related_securities": sum(x.live_related_security_count > 0 for x in out),
        "forensic_rows_with_related_securities": sum(x.forensic_related_security_count > 0 for x in out),
        "max_forensic_related_security_count": max(x.forensic_related_security_count for x in out),
    }


def _synthetic_source_file(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if "source_names" not in (reader.fieldnames or []):
                return False
            return any("synthetic" in (r.get("source_names") or "").lower() for r in reader)
    except UnicodeDecodeError:
        return False


def assess_challenger_readiness(*, base_features: Path | None, matched_controls: Path | None) -> dict:
    reasons: list[str] = []
    if base_features is None or not base_features.exists():
        reasons.append("missing_non_synthetic_minute_market_feature_vectors")
    elif _synthetic_source_file(base_features):
        reasons.append("base_market_feature_vectors_are_synthetic")
    if matched_controls is None or not matched_controls.exists():
        reasons.append("missing_non_synthetic_matched_controls")
    else:
        # The demo matched-controls artifact is paired with the synthetic model fixture.
        # If the base features are synthetic, controls cannot make the comparison real.
        if base_features is not None and _synthetic_source_file(base_features):
            reasons.append("matched_controls_are_not_eligible_with_synthetic_market_features")
    return {
        "eligible_for_non_synthetic_champion_challenger_comparison": not reasons,
        "comparison_executed": False,
        "active_champion_changed": False,
        "reasons": reasons or ["ready_for_non_synthetic_offline_comparison"],
        "required_before_comparison": [
            "lawfully obtained point-in-time historical equity/options market features",
            "matched controls built from the same non-synthetic feature universe",
            "live_surveillance graph vectors generated at the corresponding timestamps",
        ],
        "warning": "The graph reconstruction is real historical research data; no synthetic market fixture is relabeled as real performance evidence.",
    }


def build_historical_graph_reconstruction(
    *,
    historical_events: Path,
    output_dir: Path,
    base_features: Path | None = None,
    matched_controls: Path | None = None,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    events = load_historical_events(historical_events)
    nodes_csv = output_dir / "historical_graph_nodes.csv"
    edges_csv = output_dir / "historical_graph_edges.csv"
    graph_db = output_dir / "historical_cross_event_graph.sqlite"
    graph_manifest_path = output_dir / "historical_graph_manifest.json"
    context_csv = output_dir / "historical_graph_context.csv"

    table_counts = build_graph_tables(events, nodes_csv, edges_csv)
    graph_manifest = ceg.build_graph_db(
        nodes_csv=nodes_csv, edges_csv=edges_csv, db_path=graph_db,
        manifest_path=graph_manifest_path,
    )
    context = build_context_audit(events, graph_db, context_csv)
    readiness = assess_challenger_readiness(
        base_features=base_features, matched_controls=matched_controls,
    )
    (output_dir / "non_synthetic_comparison_readiness.json").write_text(
        json.dumps(readiness, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    # After the enforcement case becomes public, live mode may use the public case
    # graph prospectively. This is a visibility sanity check only, not a trading signal.
    first = events[0]
    post_public_related = ceg.related_securities(
        db_path=graph_db,
        seed_security_id=f"SEC:PERMNO:{first['permno']}",
        as_of="2015-08-12T00:00:00Z",
        mode="live_surveillance",
        max_hops=4,
    )

    result = {
        "schema_version": SCHEMA_VERSION,
        "purpose": "real historical point-in-time graph reconstruction for MNPI market-surveillance research",
        "research_use_only": True,
        "historical_event_corpus": {
            "rows": len(events),
            "unique_securities": len({r['permno'] for r in events}),
            "unique_issuers": len({r['gvkey'] for r in events}),
            "input_sha256": _sha256(historical_events),
        },
        "table_counts": table_counts,
        "graph_manifest": graph_manifest,
        "context_audit": context,
        "post_public_visibility_probe": {
            "as_of": "2015-08-12T00:00:00Z",
            "seed_symbol": first["historical_symbol"],
            "related_security_count": len(post_public_related),
            "note": "Uses only enforcement relationships after their documented public date.",
        },
        "comparison_readiness": readiness,
        "source_policy": {
            "live_stolen_or_private_inputs_allowed": False,
            "historical_adjudicated_public_records_allowed": True,
            "public_research_corpus_allowed": True,
            "future_enforcement_facts_hidden_from_live_historical_queries": True,
        },
        "limitations": [
            "The public vgreg repository does not include the proprietary merged TAQ/ITCH/CBOE feature panel used in the paper.",
            "No non-synthetic champion/challenger performance claim is produced without those lawful market features and matched controls.",
            "Issuer/security identity public_at is conservatively anchored to the earliest event timestamp observable in this public research corpus, not an invented historical listing date.",
        ],
        "outputs": {
            "nodes": nodes_csv.name,
            "edges": edges_csv.name,
            "graph_db": graph_db.name,
            "graph_manifest": graph_manifest_path.name,
            "context_audit": context_csv.name,
            "readiness": "non_synthetic_comparison_readiness.json",
        },
    }
    (output_dir / "historical_graph_reconstruction_self_check.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def main() -> None:
    p = argparse.ArgumentParser(description="Reconstruct the real historical point-in-time MNPI case graph without back-projecting enforcement facts")
    p.add_argument("--historical-events", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--base-features", type=Path)
    p.add_argument("--matched-controls", type=Path)
    args = p.parse_args()
    result = build_historical_graph_reconstruction(
        historical_events=args.historical_events,
        output_dir=args.output_dir,
        base_features=args.base_features,
        matched_controls=args.matched_controls,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
