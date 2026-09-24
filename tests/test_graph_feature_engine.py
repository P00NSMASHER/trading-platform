from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cross_event_graph import build_graph_db
from graph_feature_engine import build_graph_features, load_feature_vectors


def _write(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def _graph(tmp_path: Path) -> Path:
    nodes = [
        {"node_id":"CASE:OLD","node_type":"case","label":"Prior public case","symbol":"","attributes_json":json.dumps({"mechanism":"cross_security"}),"research_use_only":"1"},
        {"node_id":"CASE:FUT","node_type":"case","label":"Later case","symbol":"","attributes_json":json.dumps({"mechanism":"regulatory"}),"research_use_only":"1"},
        {"node_id":"EV:OLD","node_type":"event","label":"Old event","symbol":"","attributes_json":"{}","research_use_only":"1"},
        {"node_id":"EV:FUT","node_type":"event","label":"Future event","symbol":"","attributes_json":"{}","research_use_only":"1"},
        {"node_id":"ISS:AAA","node_type":"issuer","label":"Issuer A","symbol":"","attributes_json":json.dumps({"sector":"health"}),"research_use_only":"1"},
        {"node_id":"ISS:BBB","node_type":"issuer","label":"Issuer B","symbol":"","attributes_json":json.dumps({"sector":"health"}),"research_use_only":"1"},
        {"node_id":"SEC:AAA","node_type":"security","label":"AAA","symbol":"AAA","attributes_json":"{}","research_use_only":"1"},
        {"node_id":"SEC:BBB","node_type":"security","label":"BBB","symbol":"BBB","attributes_json":"{}","research_use_only":"1"},
        {"node_id":"SEC:CCC","node_type":"security","label":"CCC","symbol":"CCC","attributes_json":"{}","research_use_only":"1"},
    ]
    edges = [
        {"edge_id":"E1","src_id":"ISS:AAA","dst_id":"SEC:AAA","edge_type":"issuer_has_security","valid_from":"2010-01-01T00:00:00Z","valid_to":"","observed_at":"2010-01-01T00:00:00Z","public_at":"2010-01-01T00:00:00Z","source_class":"public_filing","source_reference":"public","adjudication_status":"public_filing","confidence":"0.98","research_use_only":"1"},
        {"edge_id":"E2","src_id":"ISS:BBB","dst_id":"SEC:BBB","edge_type":"issuer_has_security","valid_from":"2010-01-01T00:00:00Z","valid_to":"","observed_at":"2010-01-01T00:00:00Z","public_at":"2010-01-01T00:00:00Z","source_class":"public_filing","source_reference":"public","adjudication_status":"public_filing","confidence":"0.98","research_use_only":"1"},
        {"edge_id":"E3","src_id":"SEC:AAA","dst_id":"SEC:BBB","edge_type":"peer_of","valid_from":"2015-01-01T00:00:00Z","valid_to":"","observed_at":"2015-01-01T00:00:00Z","public_at":"2015-01-01T00:00:00Z","source_class":"official_public","source_reference":"peer-map","adjudication_status":"not_applicable","confidence":"0.9","research_use_only":"1"},
        {"edge_id":"E4","src_id":"SEC:BBB","dst_id":"SEC:CCC","edge_type":"related_security","valid_from":"2015-01-01T00:00:00Z","valid_to":"","observed_at":"2015-01-01T00:00:00Z","public_at":"2015-01-01T00:00:00Z","source_class":"official_public","source_reference":"map","adjudication_status":"not_applicable","confidence":"0.8","research_use_only":"1"},
        {"edge_id":"E5","src_id":"CASE:OLD","dst_id":"EV:OLD","edge_type":"case_contains_event","valid_from":"","valid_to":"","observed_at":"2016-01-02T00:00:00Z","public_at":"2017-01-01T00:00:00Z","source_class":"adjudicated_public","source_reference":"old-case","adjudication_status":"final_judgment","confidence":"1","research_use_only":"1"},
        {"edge_id":"E6","src_id":"EV:OLD","dst_id":"ISS:AAA","edge_type":"event_concerns_issuer","valid_from":"2016-01-02T00:00:00Z","valid_to":"","observed_at":"2016-01-02T00:00:00Z","public_at":"2017-01-01T00:00:00Z","source_class":"adjudicated_public","source_reference":"old-case","adjudication_status":"final_judgment","confidence":"1","research_use_only":"1"},
        {"edge_id":"E7","src_id":"CASE:FUT","dst_id":"EV:FUT","edge_type":"case_contains_event","valid_from":"","valid_to":"","observed_at":"2024-01-02T00:00:00Z","public_at":"2025-01-01T00:00:00Z","source_class":"adjudicated_public","source_reference":"later-case","adjudication_status":"final_judgment","confidence":"1","research_use_only":"1"},
        {"edge_id":"E8","src_id":"EV:FUT","dst_id":"ISS:BBB","edge_type":"event_concerns_issuer","valid_from":"2024-01-02T00:00:00Z","valid_to":"","observed_at":"2024-01-02T00:00:00Z","public_at":"2025-01-01T00:00:00Z","source_class":"adjudicated_public","source_reference":"later-case","adjudication_status":"final_judgment","confidence":"1","research_use_only":"1"},
    ]
    np = tmp_path / "nodes.csv"
    ep = tmp_path / "edges.csv"
    _write(np, ["node_id","node_type","label","symbol","attributes_json","research_use_only"], nodes)
    _write(ep, ["edge_id","src_id","dst_id","edge_type","valid_from","valid_to","observed_at","public_at","source_class","source_reference","adjudication_status","confidence","research_use_only"], edges)
    db = tmp_path / "graph.sqlite"
    build_graph_db(nodes_csv=np, edges_csv=ep, db_path=db)
    return db


def _feature_row(ts: str, symbol: str, *, l2="", eq="", op="", spread="", status="full") -> dict:
    return {
        "minute_ts_utc": ts,
        "symbol": symbol,
        "feature_status": status,
        "equity_volume_z": eq,
        "equity_spread_z": spread,
        "option_volume_z": op,
        "multivariate_l2": l2,
    }


def _features(tmp_path: Path, ts: str = "2022-06-01T15:00:00.000Z", include_ccc: bool = True) -> Path:
    rows = [
        _feature_row(ts, "AAA", l2="4", eq="3", op="0.5", spread="2"),
        _feature_row(ts, "BBB", l2="5", eq="2.5", op="3", spread="1.6"),
    ]
    if include_ccc:
        rows.append(_feature_row(ts, "CCC", l2="1", eq="0.5", op="0.2", spread="0.3"))
    p = tmp_path / "features.csv"
    _write(p, list(rows[0].keys()), rows)
    return p


def _read_one(path: Path, symbol: str = "AAA") -> dict:
    rows = list(csv.DictReader(path.open()))
    return next(r for r in rows if r["symbol"] == symbol)


def test_load_feature_vectors_normalizes_timestamp(tmp_path: Path):
    p = _features(tmp_path, ts="2022-06-01T11:00:00-04:00")
    rows = load_feature_vectors(p)
    assert ("AAA", "2022-06-01T15:00:00.000Z") in rows


def test_graph_breadth_and_hops(tmp_path: Path):
    db = _graph(tmp_path)
    fp = _features(tmp_path)
    out = tmp_path / "out"
    build_graph_features(feature_vectors=fp, graph_db=db, output_dir=out, max_hops=2)
    row = _read_one(out / "graph_feature_vectors.csv")
    assert row["graph_feature_status"] == "full"
    assert int(row["related_security_count"]) == 2
    assert int(row["direct_related_security_count"]) == 1
    assert int(row["second_hop_related_security_count"]) == 1
    assert float(row["confidence_weighted_breadth"]) == pytest.approx(0.9 + (0.9 * 0.8 * 0.92) / 2)


def test_synchronized_anomalies_and_propagation(tmp_path: Path):
    db = _graph(tmp_path)
    fp = _features(tmp_path)
    out = tmp_path / "out"
    build_graph_features(feature_vectors=fp, graph_db=db, output_dir=out)
    row = _read_one(out / "graph_feature_vectors.csv")
    assert int(row["anomalous_related_count"]) == 1
    assert float(row["anomalous_related_fraction"]) == pytest.approx(0.5)
    assert int(row["synchronized_equity_volume_anomaly_count"]) == 1
    assert int(row["synchronized_option_volume_anomaly_count"]) == 1
    assert int(row["synchronized_spread_widen_count"]) == 1
    assert float(row["max_related_multivariate_l2"]) == pytest.approx(5.0)
    assert float(row["propagation_strength"]) > 0
    assert float(row["min_anomalous_hop"]) == pytest.approx(1.0)


def test_partial_status_when_related_feature_missing(tmp_path: Path):
    db = _graph(tmp_path)
    fp = _features(tmp_path, include_ccc=False)
    out = tmp_path / "out"
    build_graph_features(feature_vectors=fp, graph_db=db, output_dir=out)
    row = _read_one(out / "graph_feature_vectors.csv")
    assert row["graph_feature_status"] == "partial"
    assert int(row["related_feature_count"]) == 1


def test_live_similarity_excludes_later_case(tmp_path: Path):
    db = _graph(tmp_path)
    fp = _features(tmp_path, ts="2022-06-01T15:00:00.000Z")
    out = tmp_path / "out"
    build_graph_features(feature_vectors=fp, graph_db=db, output_dir=out, mode="live_surveillance")
    row = _read_one(out / "graph_feature_vectors.csv")
    assert int(row["prior_visible_case_count"]) == 1
    assert float(row["prior_case_similarity_max"]) >= 0


def test_live_similarity_sees_later_case_only_after_publication(tmp_path: Path):
    db = _graph(tmp_path)
    fp = _features(tmp_path, ts="2026-06-01T15:00:00.000Z")
    out = tmp_path / "out"
    build_graph_features(feature_vectors=fp, graph_db=db, output_dir=out, mode="live_surveillance")
    row = _read_one(out / "graph_feature_vectors.csv")
    assert int(row["prior_visible_case_count"]) == 2


def test_historical_forensics_does_not_backproject_future_event(tmp_path: Path):
    db = _graph(tmp_path)
    fp = _features(tmp_path, ts="2022-06-01T15:00:00.000Z")
    out = tmp_path / "out"
    build_graph_features(feature_vectors=fp, graph_db=db, output_dir=out, mode="historical_forensics")
    row = _read_one(out / "graph_feature_vectors.csv")
    # The 2024 event is still hidden because observed_at is in the future.
    assert int(row["prior_visible_case_count"]) == 1


def test_unknown_security_is_retained_with_status(tmp_path: Path):
    db = _graph(tmp_path)
    p = tmp_path / "features.csv"
    row = _feature_row("2022-06-01T15:00:00.000Z", "ZZZ", l2="3", eq="3")
    _write(p, list(row.keys()), [row])
    out = tmp_path / "out"
    build_graph_features(feature_vectors=p, graph_db=db, output_dir=out)
    got = _read_one(out / "graph_feature_vectors.csv", "ZZZ")
    assert got["graph_feature_status"] == "no_security_node"
    assert got["security_id"] == ""


def test_min_confidence_filters_weak_path(tmp_path: Path):
    db = _graph(tmp_path)
    fp = _features(tmp_path)
    out = tmp_path / "out"
    build_graph_features(feature_vectors=fp, graph_db=db, output_dir=out, max_hops=2, min_confidence=0.8)
    row = _read_one(out / "graph_feature_vectors.csv")
    # BBB path confidence .9 survives; CCC path confidence .72 is filtered.
    assert int(row["related_security_count"]) == 1
    assert int(row["direct_related_security_count"]) == 1


def test_manifest_records_point_in_time_policy_and_hashes(tmp_path: Path):
    db = _graph(tmp_path)
    fp = _features(tmp_path)
    out = tmp_path / "out"
    m = build_graph_features(feature_vectors=fp, graph_db=db, output_dir=out)
    assert m["point_in_time_policy"]["later_enforcement_facts_excluded_from_live_features"] is True
    assert len(m["inputs"]["feature_vectors"]["sha256"]) == 64
    assert len(m["inputs"]["graph_db"]["sha256"]) == 64


def test_output_schema_contains_no_trading_fields(tmp_path: Path):
    db = _graph(tmp_path)
    fp = _features(tmp_path)
    out = tmp_path / "out"
    build_graph_features(feature_vectors=fp, graph_db=db, output_dir=out)
    header = next(csv.reader((out / "graph_feature_vectors.csv").open()))
    low = {x.lower() for x in header}
    assert not low.intersection({"buy","sell","trade_direction","expected_return","target_price","position_size","order_quantity"})


def test_ambiguous_symbol_mapping_fails_closed(tmp_path: Path):
    db = _graph(tmp_path)
    # append is allowed; create a second security node with the same symbol.
    import sqlite3
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO nodes(node_id,node_type,label,symbol,attributes_json,research_use_only) VALUES (?,?,?,?,?,1)", ("SEC:AAA2","security","AAA2","AAA","{}"))
    conn.commit(); conn.close()
    fp = _features(tmp_path)
    with pytest.raises(ValueError, match="ambiguous graph security mapping"):
        build_graph_features(feature_vectors=fp, graph_db=db, output_dir=tmp_path / "out")
