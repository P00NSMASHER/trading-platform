from __future__ import annotations

import csv
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cross_event_graph import (
    build_graph_db,
    case_contamination_blocklist,
    case_similarity,
    graph_self_check,
    load_edges,
    load_nodes,
    related_securities,
)


def _write(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def _fixture(tmp_path: Path):
    nodes = [
        {"node_id":"CASE:A","node_type":"case","label":"Case A","attributes_json":json.dumps({"mechanism":"cross_security","information_type":"m&a","instrument":"options"}),"research_use_only":"1"},
        {"node_id":"CASE:B","node_type":"case","label":"Case B","attributes_json":json.dumps({"mechanism":"cross_security","information_type":"m&a","instrument":"stock"}),"research_use_only":"1"},
        {"node_id":"EV:A","node_type":"event","label":"Historical event A","attributes_json":"{}","research_use_only":"1"},
        {"node_id":"ISS:AAA","node_type":"issuer","label":"Issuer AAA","attributes_json":json.dumps({"sector":"health"}),"research_use_only":"1"},
        {"node_id":"ISS:BBB","node_type":"issuer","label":"Issuer BBB","attributes_json":json.dumps({"sector":"health"}),"research_use_only":"1"},
        {"node_id":"SEC:AAA","node_type":"security","label":"AAA common","symbol":"AAA","attributes_json":"{}","research_use_only":"1"},
        {"node_id":"SEC:BBB","node_type":"security","label":"BBB common","symbol":"BBB","attributes_json":"{}","research_use_only":"1"},
        {"node_id":"SEC:CCC","node_type":"security","label":"CCC common","symbol":"CCC","attributes_json":"{}","research_use_only":"1"},
        {"node_id":"ORG:ADV","node_type":"organization","label":"Adviser","attributes_json":"{}","research_use_only":"1"},
        {"node_id":"PER:P","node_type":"person","label":"Historical person","attributes_json":"{}","research_use_only":"1"},
    ]
    edges = [
        {"edge_id":"E1","src_id":"CASE:A","dst_id":"EV:A","edge_type":"case_contains_event","valid_from":"","valid_to":"","observed_at":"2016-08-18T19:19:00Z","public_at":"2021-08-17T12:00:00Z","source_class":"adjudicated_public","source_reference":"official-case","adjudication_status":"final_judgment","confidence":"1","research_use_only":"1"},
        {"edge_id":"E2","src_id":"EV:A","dst_id":"ISS:AAA","edge_type":"event_concerns_issuer","valid_from":"2016-08-18T19:19:00Z","valid_to":"","observed_at":"2016-08-18T19:19:00Z","public_at":"2021-08-17T12:00:00Z","source_class":"adjudicated_public","source_reference":"official-case","adjudication_status":"final_judgment","confidence":"1","research_use_only":"1"},
        {"edge_id":"E3","src_id":"ISS:AAA","dst_id":"SEC:AAA","edge_type":"issuer_has_security","valid_from":"2010-01-01T00:00:00Z","valid_to":"","observed_at":"2010-01-01T00:00:00Z","public_at":"2010-01-01T00:00:00Z","source_class":"public_filing","source_reference":"public","adjudication_status":"public_filing","confidence":"0.98","research_use_only":"1"},
        {"edge_id":"E4","src_id":"ISS:BBB","dst_id":"SEC:BBB","edge_type":"issuer_has_security","valid_from":"2010-01-01T00:00:00Z","valid_to":"","observed_at":"2010-01-01T00:00:00Z","public_at":"2010-01-01T00:00:00Z","source_class":"public_filing","source_reference":"public","adjudication_status":"public_filing","confidence":"0.98","research_use_only":"1"},
        {"edge_id":"E5","src_id":"SEC:AAA","dst_id":"SEC:BBB","edge_type":"peer_of","valid_from":"2015-01-01T00:00:00Z","valid_to":"","observed_at":"2015-01-01T00:00:00Z","public_at":"2015-01-01T00:00:00Z","source_class":"official_public","source_reference":"peer-map","adjudication_status":"not_applicable","confidence":"0.9","research_use_only":"1"},
        {"edge_id":"E6","src_id":"SEC:BBB","dst_id":"SEC:CCC","edge_type":"related_security","valid_from":"2015-01-01T00:00:00Z","valid_to":"","observed_at":"2015-01-01T00:00:00Z","public_at":"2015-01-01T00:00:00Z","source_class":"official_public","source_reference":"relationship-map","adjudication_status":"not_applicable","confidence":"0.8","research_use_only":"1"},
        {"edge_id":"E7","src_id":"CASE:A","dst_id":"PER:P","edge_type":"subject_of_case","valid_from":"","valid_to":"","observed_at":"2016-08-18T19:26:00Z","public_at":"2021-08-17T12:00:00Z","source_class":"adjudicated_public","source_reference":"official-case","adjudication_status":"final_judgment","confidence":"1","research_use_only":"1"},
        {"edge_id":"E8","src_id":"PER:P","dst_id":"ORG:ADV","edge_type":"employed_by","valid_from":"2016-01-01T00:00:00Z","valid_to":"2016-12-31T23:59:59Z","observed_at":"2016-08-18T00:00:00Z","public_at":"2016-01-01T00:00:00Z","source_class":"official_public","source_reference":"public-bio","adjudication_status":"not_applicable","confidence":"0.9","research_use_only":"1"},
        {"edge_id":"E9","src_id":"CASE:B","dst_id":"ISS:BBB","edge_type":"subject_of_case","valid_from":"","valid_to":"","observed_at":"2019-01-01T00:00:00Z","public_at":"2020-01-01T00:00:00Z","source_class":"adjudicated_public","source_reference":"official-case-b","adjudication_status":"guilty_plea","confidence":"1","research_use_only":"1"},
    ]
    np = tmp_path / "nodes.csv"
    ep = tmp_path / "edges.csv"
    _write(np, ["node_id","node_type","label","symbol","attributes_json","research_use_only"], nodes)
    _write(ep, ["edge_id","src_id","dst_id","edge_type","valid_from","valid_to","observed_at","public_at","source_class","source_reference","adjudication_status","confidence","research_use_only"], edges)
    db = tmp_path / "graph.sqlite"
    manifest = tmp_path / "manifest.json"
    build_graph_db(nodes_csv=np, edges_csv=ep, db_path=db, manifest_path=manifest)
    return np, ep, db, manifest


def test_build_and_self_check(tmp_path: Path):
    _, _, db, manifest = _fixture(tmp_path)
    report = graph_self_check(db)
    assert report["ok"] is True
    m = json.loads(manifest.read_text())
    assert m["source_policy"]["live_stolen_or_leaked_inputs_allowed"] is False


def test_rejects_live_stolen_source_class(tmp_path: Path):
    np, ep, _, _ = _fixture(tmp_path)
    rows = list(csv.DictReader(ep.open()))
    rows[0]["source_class"] = "live_stolen"
    bad = tmp_path / "bad.csv"
    _write(bad, list(rows[0].keys()), rows)
    nodes = load_nodes(np)
    with pytest.raises(ValueError):
        load_edges(bad, {n.node_id for n in nodes})


def test_rejects_trading_attributes(tmp_path: Path):
    np, _, _, _ = _fixture(tmp_path)
    rows = list(csv.DictReader(np.open()))
    rows[0]["attributes_json"] = json.dumps({"expected_return": 0.4})
    bad = tmp_path / "bad_nodes.csv"
    _write(bad, list(rows[0].keys()), rows)
    with pytest.raises(ValueError):
        load_nodes(bad)


def test_live_mode_hides_future_enforcement_edges(tmp_path: Path):
    _, _, db, _ = _fixture(tmp_path)
    rows = related_securities(db_path=db, seed_security_id="SEC:AAA", as_of="2016-08-18T19:30:00Z", mode="live_surveillance", max_hops=3)
    assert {r.symbol for r in rows} >= {"BBB", "CCC"}
    # The public peer map is visible, but later enforcement/case links must not affect live expansion.
    assert all("case_contains_event" not in r.relationship_path for r in rows)


def test_historical_mode_can_use_later_public_adjudication(tmp_path: Path):
    _, _, db, _ = _fixture(tmp_path)
    rows = case_contamination_blocklist(db_path=db, case_id="CASE:A", as_of="2022-01-01T00:00:00Z", mode="historical_forensics", max_hops=4)
    syms = {r["symbol"] for r in rows}
    assert "AAA" in syms
    assert "BBB" in syms


def test_related_security_expansion_is_multi_hop(tmp_path: Path):
    _, _, db, _ = _fixture(tmp_path)
    rows = related_securities(db_path=db, seed_security_id="SEC:AAA", as_of="2016-08-18T19:30:00Z", mode="live_surveillance", max_hops=2)
    by = {r.symbol:r for r in rows}
    assert by["BBB"].hop_count == 1
    assert by["CCC"].hop_count == 2
    assert 0 < by["CCC"].path_confidence < by["BBB"].path_confidence


def test_validity_window_excludes_expired_relationship(tmp_path: Path):
    _, _, db, _ = _fixture(tmp_path)
    conn = sqlite3.connect(db)
    # cannot mutate append-only graph; verify employment relation becomes invisible by query date instead.
    conn.close()
    # An entity-to-security route through expired employment should not invent a security; direct public peer route remains.
    rows = related_securities(db_path=db, seed_security_id="SEC:AAA", as_of="2018-01-01T00:00:00Z", mode="live_surveillance", max_hops=3)
    assert {r.symbol for r in rows} == {"BBB", "CCC"}


def test_case_similarity_uses_structure_not_returns(tmp_path: Path):
    _, _, db, _ = _fixture(tmp_path)
    rows = case_similarity(db_path=db, case_id="CASE:A", as_of="2022-01-01T00:00:00Z")
    assert rows and rows[0]["case_id"] == "CASE:B"
    assert 0 <= rows[0]["structural_similarity"] <= 1
    assert "expected_return" not in rows[0]


def test_append_only_nodes_and_edges(tmp_path: Path):
    _, _, db, _ = _fixture(tmp_path)
    conn = sqlite3.connect(db)
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("UPDATE nodes SET label='changed' WHERE node_id='SEC:AAA'")
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("DELETE FROM edges WHERE edge_id='E5'")
    conn.close()


def test_security_requires_symbol(tmp_path: Path):
    np, _, _, _ = _fixture(tmp_path)
    rows = list(csv.DictReader(np.open()))
    for r in rows:
        if r["node_type"] == "security":
            r["symbol"] = ""
            break
    bad = tmp_path / "bad_nodes.csv"
    _write(bad, list(rows[0].keys()), rows)
    with pytest.raises(ValueError):
        load_nodes(bad)


def test_unknown_node_reference_rejected(tmp_path: Path):
    np, ep, _, _ = _fixture(tmp_path)
    rows = list(csv.DictReader(ep.open()))
    rows[0]["dst_id"] = "MISSING"
    bad = tmp_path / "bad_edges.csv"
    _write(bad, list(rows[0].keys()), rows)
    nodes = load_nodes(np)
    with pytest.raises(ValueError):
        load_edges(bad, {n.node_id for n in nodes})


def test_blocklist_is_explicitly_control_exclusion(tmp_path: Path):
    _, _, db, _ = _fixture(tmp_path)
    rows = case_contamination_blocklist(db_path=db, case_id="CASE:A", as_of="2022-01-01T00:00:00Z")
    assert rows
    assert all(r["exclude_from_controls"] == 1 for r in rows)
    header = {k.lower() for k in rows[0]}
    assert not header.intersection({"buy","sell","expected_return","target_price","position_size"})


def test_manifest_hashes_inputs(tmp_path: Path):
    np, ep, _, manifest = _fixture(tmp_path)
    m = json.loads(manifest.read_text())
    assert set(m["input_sha256"]) == {np.name, ep.name}
    assert len(m["db_sha256"]) == 64


def test_historical_mode_never_exposes_edge_before_observed_at(tmp_path: Path):
    _, _, db, _ = _fixture(tmp_path)
    # Case B edge is observed in 2019. Historical forensics may use later-public
    # adjudication, but cannot back-project a later underlying event into 2018.
    rows = case_similarity(db_path=db, case_id="CASE:A", as_of="2018-01-01T00:00:00Z", mode="historical_forensics")
    by = {r["case_id"]: r for r in rows}
    assert "CASE:B" not in by
