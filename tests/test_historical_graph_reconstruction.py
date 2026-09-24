from pathlib import Path
import csv
import json

import historical_graph_reconstruction as hgr
import cross_event_graph as ceg

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "data/processed/historical_events.csv"


def test_loads_real_historical_corpus():
    rows = hgr.load_historical_events(EVENTS)
    assert len(rows) == 174
    assert len({r["permno"] for r in rows}) == 146
    assert all(r["sec_documented_trade_flag"] == "1" for r in rows)


def test_new_york_timestamp_conversion_is_dst_aware():
    assert hgr._to_utc("2012-01-26 15:53:00") == "2012-01-26T20:53:00Z"
    assert hgr._to_utc("2011-07-27 15:59:00") == "2011-07-27T19:59:00Z"


def test_real_graph_counts_and_source_policy(tmp_path: Path):
    result = hgr.build_historical_graph_reconstruction(
        historical_events=EVENTS,
        output_dir=tmp_path,
    )
    assert result["table_counts"]["nodes"] == 467
    assert result["table_counts"]["edges"] == 668
    assert result["table_counts"]["event_nodes"] == 174
    assert result["table_counts"]["security_nodes"] == 146
    manifest = json.loads((tmp_path / "historical_graph_manifest.json").read_text())
    assert "public_research" in manifest["source_policy"]["allowed_source_classes"]
    assert manifest["source_policy"]["live_stolen_or_leaked_inputs_allowed"] is False


def test_live_mode_does_not_back_project_enforcement(tmp_path: Path):
    result = hgr.build_historical_graph_reconstruction(historical_events=EVENTS, output_dir=tmp_path)
    assert result["context_audit"]["live_case_visible_rows"] == 0
    assert result["context_audit"]["live_rows_with_related_securities"] == 0
    assert result["context_audit"]["forensic_case_visible_rows"] == 174


def test_forensic_mode_links_only_already_observed_events(tmp_path: Path):
    hgr.build_historical_graph_reconstruction(historical_events=EVENTS, output_dir=tmp_path)
    rows = list(csv.DictReader((tmp_path / "historical_graph_context.csv").open()))
    rows.sort(key=lambda r: r["first_trade_utc"])
    assert int(rows[0]["forensic_related_security_count"]) == 0
    assert int(rows[-1]["forensic_related_security_count"]) == 145
    assert all(int(r["live_related_security_count"]) == 0 for r in rows)


def test_case_relationship_becomes_live_only_after_public_date(tmp_path: Path):
    rows = hgr.load_historical_events(EVENTS)
    hgr.build_historical_graph_reconstruction(historical_events=EVENTS, output_dir=tmp_path)
    sid = f"SEC:PERMNO:{rows[0]['permno']}"
    before = ceg.related_securities(
        db_path=tmp_path / "historical_cross_event_graph.sqlite",
        seed_security_id=sid,
        as_of=hgr._to_utc(rows[0]["first_documented_illicit_trade_ts"]),
        mode="live_surveillance",
        max_hops=4,
    )
    after = ceg.related_securities(
        db_path=tmp_path / "historical_cross_event_graph.sqlite",
        seed_security_id=sid,
        as_of="2015-08-12T00:00:00Z",
        mode="live_surveillance",
        max_hops=4,
    )
    assert before == []
    assert len(after) == 145


def test_challenger_readiness_fails_closed_on_synthetic_market_fixture(tmp_path: Path):
    result = hgr.build_historical_graph_reconstruction(
        historical_events=EVENTS,
        output_dir=tmp_path,
        base_features=ROOT / "data/examples/model_training_feature_vectors.csv",
        matched_controls=ROOT / "data/examples/model_training_matched_controls.csv",
    )
    readiness = result["comparison_readiness"]
    assert readiness["eligible_for_non_synthetic_champion_challenger_comparison"] is False
    assert readiness["comparison_executed"] is False
    assert "base_market_feature_vectors_are_synthetic" in readiness["reasons"]


def test_real_graph_outputs_remain_research_only_and_non_directional(tmp_path: Path):
    hgr.build_historical_graph_reconstruction(historical_events=EVENTS, output_dir=tmp_path)
    nodes = (tmp_path / "historical_graph_nodes.csv").read_text().lower()
    edges = (tmp_path / "historical_graph_edges.csv").read_text().lower()
    assert "research_use_only" in nodes
    for forbidden in ["expected_return", "target_price", "position_size", "order_quantity", "trade_direction"]:
        assert forbidden not in nodes
        assert forbidden not in edges
