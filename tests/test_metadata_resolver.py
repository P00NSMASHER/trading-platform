from pathlib import Path
import csv
import hashlib
import json
import sys

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))

from metadata_resolver import (
    build, load_contract, resolve_announcements, resolve_event_exchanges,
    resolve_shares, resolve_control_readiness, _load_source_rows,
    SharesResolution, _apply_reviewed_share_exclusions,
)


def load_demo_sources(contract_path=ROOT/"config/metadata_sources.demo.json"):
    contracts,_=load_contract(contract_path)
    root=contract_path.parent.parent
    out=[]
    for s in contracts:
        rows,p=_load_source_rows(s,root)
        out.append((s,rows,p))
    return out


def events():
    with (ROOT/"data/examples/metadata/events.csv").open(newline="",encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_exact_release_resolves_and_asymmetry_positive():
    x=resolve_announcements(events(),load_demo_sources())[0]
    assert x.resolution_status=="resolved_exact_public_timestamp"
    assert x.timestamp_confidence=="A-EXACT"
    assert int(x.information_asymmetry_seconds)>0


def test_edgar_acceptance_is_proxy_not_exact(tmp_path):
    c=json.loads((ROOT/"config/metadata_sources.demo.json").read_text())
    c["sources"][0]["path"]="data/examples/metadata/edgar_proxy.csv"
    c["sources"][0]["source_family"]="sec_edgar_submission_header"
    p=tmp_path/"contract.json"; p.write_text(json.dumps(c),encoding="utf-8")
    # Make relative paths work by placing contract under workspace config equivalent.
    q=ROOT/"config/_tmp_edgar_test.json"; q.write_text(json.dumps(c),encoding="utf-8")
    try:
        x=resolve_announcements(events(),load_demo_sources(q))[0]
        assert x.resolution_status=="proxy_public_timestamp_not_exact_release"
        assert x.timestamp_confidence=="C-PROXY"
    finally:
        q.unlink(missing_ok=True)


def test_event_exchange_resolves_nasdaq():
    x=resolve_event_exchanges(events(),load_demo_sources())[0]
    assert x.primary_exchange=="XNAS"
    assert x.itch_requirement=="required"




def test_event_bound_exchange_record_beats_same_symbol_fallback(tmp_path):
    data=ROOT/"data/examples/metadata/_event_bound_exchange.csv"
    data.write_text(
        "event_id,historical_symbol,effective_date,primary_exchange,source_reference\n"
        "OTHER,TEST,2015-02-17,XNYS,https://example.invalid/other\n"
        "E1,TEST,2015-02-17,XNAS,https://example.invalid/e1\n",
        encoding="utf-8",
    )
    contract={
        "schema_version":"1",
        "sources":[{
            "source_id":"event-bound","record_kind":"security_master","source_family":"public_listing_evidence",
            "path":"data/examples/metadata/_event_bound_exchange.csv","enabled":True,"authorized":True,
            "data_classification":"public_research_replication","license_reference":"public fixture",
            "delimiter":",","encoding":"utf-8","timezone":"America/New_York","column_map":{}
        }]
    }
    q=ROOT/"config/_tmp_event_bound.json"; q.write_text(json.dumps(contract),encoding="utf-8")
    try:
        x=resolve_event_exchanges(events(),load_demo_sources(q))[0]
        assert x.primary_exchange=="XNAS"
        assert x.source_reference=="https://example.invalid/e1"
    finally:
        data.unlink(missing_ok=True); q.unlink(missing_ok=True)


def test_real_g3_public_evidence_resolves_all_event_exchanges(tmp_path):
    contract=ROOT/"config/metadata_sources.g3_public.json"
    evidence=ROOT/"data/public/metadata/g3_primary_listing_history.csv"
    if not evidence.exists():
        pytest.skip("generated G3 evidence not present yet")
    out=tmp_path/"g3-real"
    r=build(
        ROOT/"data/processed/historical_events.csv",
        ROOT/"data/processed/coverage_plan_real/symbol_date_requirements.csv",
        contract,
        out,
    )
    assert r["event_count"]==174
    assert r["event_exchange_resolved"]==174
    assert r["event_exchange_unresolved"]==0
    assert r["ready_g3_primary_listing_history"] is True
    assert r["ready_g1_announcement_times"] is False
    assert r["ready_g4_shares_outstanding"] is False
    assert r["ready_g5_matched_control_universe"] is False


def test_shares_resolve_exact_day_and_millions_scale():
    rows=[{"historical_symbol":"TEST","trade_date":"2015-02-16"},{"historical_symbol":"TEST","trade_date":"2015-02-17"}]
    x=resolve_shares(rows,load_demo_sources())
    assert x[1].shares_outstanding=="10000000"
    assert x[1].staleness_days=="0"




def test_shares_target_date_binding_and_pre_window_cutoff(tmp_path):
    data=ROOT/"data/examples/metadata/_g4_bound_shares.csv"
    data.write_text(
        "historical_symbol,target_trade_date,fact_date,available_at,shares_outstanding,source_reference\n"
        "TEST,2015-02-17,2015-02-10,2015-02-17T14:00:00-05:00,10000000,https://example.invalid/early\n"
        "TEST,2015-02-18,2015-02-10,2015-02-17T13:00:00-05:00,20000000,https://example.invalid/wrong-date\n",
        encoding="utf-8",
    )
    contract={
        "schema_version":"1",
        "sources":[{
            "source_id":"g4-bound","record_kind":"shares_outstanding","source_family":"sec_xbrl_companyfacts",
            "path":"data/examples/metadata/_g4_bound_shares.csv","enabled":True,"authorized":True,
            "data_classification":"public_official_data","license_reference":"SEC fixture",
            "delimiter":",","encoding":"utf-8","timezone":"America/New_York","column_map":{}
        }]
    }
    q=ROOT/"config/_tmp_g4_bound.json"; q.write_text(json.dumps(contract),encoding="utf-8")
    try:
        rows=[{
            "historical_symbol":"TEST","trade_date":"2015-02-17",
            "window_intervals_local":"13:30-14:30"
        }]
        x=resolve_shares(rows,load_demo_sources(q))[0]
        assert x.resolution_status=="unresolved"

        data.write_text(
            "historical_symbol,target_trade_date,fact_date,available_at,shares_outstanding,source_reference\n"
            "TEST,2015-02-17,2015-02-10,2015-02-17T13:00:00-05:00,10000000,https://example.invalid/early\n"
            "TEST,2015-02-18,2015-02-10,2015-02-17T12:00:00-05:00,20000000,https://example.invalid/wrong-date\n",
            encoding="utf-8",
        )
        x=resolve_shares(rows,load_demo_sources(q))[0]
        assert x.resolution_status=="resolved"
        assert x.shares_outstanding=="10000000"
        assert x.source_reference=="https://example.invalid/early"
    finally:
        data.unlink(missing_ok=True); q.unlink(missing_ok=True)

def test_future_shares_fact_is_not_used(tmp_path):
    p=ROOT/"data/examples/metadata/_future_shares.csv"
    p.write_text("symbol,trade_date,listed_exchange,shares_outstanding_millions\nTEST,2015-02-18,Q,20\n",encoding="utf-8")
    c={"schema_version":"1","sources":[{
        "source_id":"future","record_kind":"security_master","source_family":"synthetic_fixture",
        "path":"data/examples/metadata/_future_shares.csv","enabled":True,"authorized":True,
        "data_classification":"synthetic_fixture","license_reference":"fixture","delimiter":",","encoding":"utf-8","timezone":"America/New_York","column_map":{}}]}
    q=ROOT/"config/_tmp_future.json"; q.write_text(json.dumps(c),encoding="utf-8")
    try:
        x=resolve_shares([{"historical_symbol":"TEST","trade_date":"2015-02-17"}],load_demo_sources(q))[0]
        assert x.resolution_status=="unresolved"
    finally:
        p.unlink(missing_ok=True); q.unlink(missing_ok=True)


def test_control_universe_closes_with_three_pre_event_complete_candidates():
    x=resolve_control_readiness(events(),load_demo_sources())[0]
    assert x.candidate_count==3
    assert x.candidates_with_pre_event_covariates==3
    assert x.readiness_status=="resolved_for_point_in_time_matching"


def test_control_candidate_available_after_cutoff_is_excluded(tmp_path):
    p=ROOT/"data/examples/metadata/_late_controls.csv"
    base=(ROOT/"data/examples/metadata/control_universe.csv").read_text()
    p.write_text(base.replace("12:00:00","15:00:00"),encoding="utf-8")
    c={"schema_version":"1","sources":[{
        "source_id":"late","record_kind":"control_universe","source_family":"synthetic_fixture",
        "path":"data/examples/metadata/_late_controls.csv","enabled":True,"authorized":True,
        "data_classification":"synthetic_fixture","license_reference":"fixture","delimiter":",","encoding":"utf-8","timezone":"America/New_York","column_map":{}}]}
    q=ROOT/"config/_tmp_late.json"; q.write_text(json.dumps(c),encoding="utf-8")
    try:
        x=resolve_control_readiness(events(),load_demo_sources(q))[0]
        assert x.candidate_count==0
        assert x.readiness_status=="unresolved"
    finally:
        p.unlink(missing_ok=True); q.unlink(missing_ok=True)


def test_contract_rejects_prohibited_private_source(tmp_path):
    p=tmp_path/"c.json"
    p.write_text(json.dumps({"schema_version":"1","sources":[{
        "source_id":"x","record_kind":"announcement_timestamp","source_family":"generic_authorized_reference_data",
        "path":"x","enabled":False,"authorized":False,"data_classification":"live_stolen_information",
        "license_reference":"","column_map":{}}]}),encoding="utf-8")
    with pytest.raises(ValueError,match="prohibited metadata source"):
        load_contract(p)


def test_contract_rejects_credential_fields(tmp_path):
    p=tmp_path/"c.json"
    p.write_text(json.dumps({"schema_version":"1","sources":[{
        "source_id":"x","record_kind":"announcement_timestamp","source_family":"synthetic_fixture",
        "path":"x","enabled":False,"authorized":True,"data_classification":"synthetic_fixture",
        "license_reference":"fixture","api_key":"NOPE","column_map":{}}]}),encoding="utf-8")
    with pytest.raises(ValueError,match="credential-like"):
        load_contract(p)


def test_demo_build_closes_all_metadata_gates(tmp_path):
    out=tmp_path/"out"
    r=build(ROOT/"data/examples/metadata/events.csv",ROOT/"data/examples/metadata/symbol_dates.csv",ROOT/"config/metadata_sources.demo.json",out)
    assert r["ready_g1_announcement_times"] is True
    assert r["ready_g3_primary_listing_history"] is True
    assert r["ready_g4_shares_outstanding"] is True
    assert r["ready_g5_matched_control_universe"] is True
    assert (out/"metadata_readiness_summary.json").exists()


def test_real_corpus_empty_contract_remains_fail_closed(tmp_path):
    out=tmp_path/"real"
    r=build(ROOT/"data/processed/historical_events.csv",ROOT/"data/processed/coverage_plan_real/symbol_date_requirements.csv",ROOT/"config/metadata_sources.example.json",out)
    assert r["event_count"]==174
    assert r["announcement_exact_resolved"]==0
    assert r["event_exchange_resolved"]==0
    assert r["shares_symbol_dates_resolved"]==0
    assert r["control_dates_resolved"]==0
    assert r["ready_for_non_synthetic_model_evaluation_metadata"] is False


def _reviewed_exclusion_fixture(tmp_path: Path, *, expected_sha_override: str | None = None):
    receipt = {
        "schema_version": "1",
        "research_use_only": True,
        "blockers": [{
            "historical_symbol": "TEST",
            "target_trade_dates": ["2015-02-17"],
            "resolution_status": "FAIL_CLOSED_NO_ADMISSIBLE_PRE_CUTOFF_EXACT_TOTAL",
        }],
    }
    p = tmp_path / "data" / "g4_final_blockers.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(receipt, indent=2) + "\n"
    p.write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    contract = {
        "reviewed_share_exclusions": {
            "enabled": True,
            "mode": "reviewed_fail_closed_exclusions",
            "path": "data/g4_final_blockers.json",
            "expected_sha256": expected_sha_override or digest,
            "expected_count": 1,
            "require_resolution_status": "FAIL_CLOSED_NO_ADMISSIBLE_PRE_CUTOFF_EXACT_TOTAL",
            "downstream_policy": "excluded rows may not contribute turnover",
        }
    }
    symbol_dates = [{"historical_symbol": "TEST", "trade_date": "2015-02-17"}]
    return contract, symbol_dates


def test_reviewed_share_exclusion_marks_unresolved_fail_closed(tmp_path):
    contract, symbol_dates = _reviewed_exclusion_fixture(tmp_path)
    rows = [SharesResolution("TEST", "2015-02-17", "", "unresolved", "", "", "", "", "", "")]
    out, meta = _apply_reviewed_share_exclusions(
        rows, raw_contract=contract, root=tmp_path, symbol_date_rows=symbol_dates
    )
    assert out[0].resolution_status == "excluded_fail_closed"
    assert out[0].shares_outstanding == ""
    assert out[0].fact_date == ""
    assert meta["applied_count"] == 1


def test_reviewed_share_exclusion_cannot_mask_resolved_fact(tmp_path):
    contract, symbol_dates = _reviewed_exclusion_fixture(tmp_path)
    rows = [SharesResolution(
        "TEST", "2015-02-17", "1000000", "resolved", "src", "sec_xbrl_companyfacts",
        "https://example.test", "2015-02-01", "2015-02-02T12:00:00-05:00", "16"
    )]
    with pytest.raises(ValueError, match="exclusion is stale"):
        _apply_reviewed_share_exclusions(
            rows, raw_contract=contract, root=tmp_path, symbol_date_rows=symbol_dates
        )


def test_reviewed_share_exclusion_receipt_hash_mismatch_fails_closed(tmp_path):
    contract, symbol_dates = _reviewed_exclusion_fixture(tmp_path, expected_sha_override="0" * 64)
    rows = [SharesResolution("TEST", "2015-02-17", "", "unresolved", "", "", "", "", "", "")]
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        _apply_reviewed_share_exclusions(
            rows, raw_contract=contract, root=tmp_path, symbol_date_rows=symbol_dates
        )
