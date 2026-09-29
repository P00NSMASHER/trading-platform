from __future__ import annotations
import copy
import csv
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest
import g1_source_research as validator
ROOT=Path(__file__).resolve().parents[1]
META=ROOT/"data/processed/authorized_input_real"
DOSS=ROOT/"data/public/metadata/g1_announcement_times_batch_0033_evidence.json"
def load(p): return json.loads(p.read_text())
def rows(p):
    with p.open(newline="",encoding="utf-8") as f: return list(csv.DictReader(f))
@pytest.mark.parametrize("event_id,symbol,lag",[("HEJFE-6C73B4B05384BC1E","PFPT",3900),("HEJFE-1FCAAB3F7CC931CF","VRSN",7080)])
def test_reviewed_syndicated_clocks_resolve_exactly(event_id,symbol,lag):
    actual={r["event_id"]:r for r in rows(META/"announcement_resolutions.csv")}[event_id]
    e={r["event_id"]:r for r in rows(ROOT/"data/processed/historical_events.csv")}[event_id]
    release=datetime.fromisoformat(actual["public_announcement_ts"].replace("Z","+00:00"))
    trade=datetime.fromisoformat(e["first_documented_illicit_trade_ts"]).replace(tzinfo=ZoneInfo("America/New_York"))
    assert actual["historical_symbol"]==symbol
    assert actual["resolution_status"]=="resolved_exact_public_timestamp"
    assert actual["source_grade"]=="B"
    assert release==datetime.fromisoformat("2013-04-25T20:05:00+00:00")
    assert int((release-trade).total_seconds())==lag
    assert trade < release <= trade+timedelta(days=7)
def test_evidence_retains_observed_metadata_and_mirror_limitations():
    d=load(DOSS); batch=ROOT/"data/public/metadata/g1_announcement_times_batch_0033.csv"
    assert hashlib.sha256(batch.read_bytes()).hexdigest()==d["batch_sha256"]
    assert len(rows(batch))==len(d["candidates"])==2
    for r in d["candidates"]:
        assert r["evidence_source_family"]=="preserved_wire_mirror"
        assert r["source_grade"]=="B"
        assert r["original_wire_publisher_byline"]=="Marketwired"
        assert r["observed_html_time_datetime"]=="2013-04-25T20:05:00+00:00"
        assert r["visible_clock_observed"] is False
        assert r["original_wire_source_link_observed"] is None
        assert r["corroboration_reference"].startswith("https://www.sec.gov/Archives/")
        assert datetime.fromisoformat(r["observed_html_time_datetime"])==datetime.fromisoformat(r["public_announcement_ts"])
def test_all_non_promoted_resolution_rows_preserved():
    d=load(DOSS); promoted={r["event_id"] for r in d["candidates"]}
    remaining={r["event_id"]:r for r in rows(META/"announcement_resolutions.csv") if r["event_id"] not in promoted}
    digest=hashlib.sha256(json.dumps(remaining,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    assert digest==d["non_promoted_resolution_rows_sha256"]
    assert hashlib.sha256((ROOT/"data/processed/historical_events.csv").read_bytes()).hexdigest()==d["frozen_events_sha256"]
def test_current_receipts_reconcile_without_completing_step9():
    r=load(META/"metadata_readiness_summary.json")
    assert (r["event_count"],r["announcement_exact_resolved"],r["announcement_events_excluded"],r["announcement_unresolved"])==(174,37,137,0)
    assert r["ready_g1_exact_timing_analysis"] is False
    excluded=[x for x in rows(META/"announcement_resolutions.csv") if x["resolution_status"]=="excluded_fail_closed"]
    assert len(excluded)==137
    assert all(not x["public_announcement_ts"] and not x.get("information_asymmetry_seconds") for x in excluded)
    status=load(ROOT/"data/processed/real_data_release_sprint/step_status.json")
    step9=next(x for x in status["steps"] if x["step"]==9)
    assert step9["status"]=="SOURCE_BLOCKED"
    assert "37/174" in step9["evidence"] and "137" in step9["evidence"]
    assert status["all_12_genuinely_complete"] is False
@pytest.mark.parametrize("mutation,match",[("missing_corroboration","corroboration_reference"),("date_only","timezone-aware"),("capture_time","timestamp_evidence_kind")])
def test_batch_specific_invalid_evidence_stays_rejected(mutation,match):
    r=load(DOSS)["candidates"][0]
    exclusions={r["event_id"]:{"historical_symbol":r["historical_symbol"],"first_documented_illicit_trade_ts":r["first_trade"]}}
    p=dict(probe_id="batch0033-negative",event_id=r["event_id"],historical_symbol=r["historical_symbol"],historical_event_match=True,exact_clock_observed=True,exact_public_release_ts=r["public_announcement_ts"],timestamp_kind="first_public_release",timestamp_evidence_kind="publisher_timestamp",source_family="preserved_wire_mirror",source_reference=r["source_reference"],corroboration_reference=r["corroboration_reference"])
    if mutation=="missing_corroboration": p.pop("corroboration_reference")
    elif mutation=="date_only": p["exact_public_release_ts"]="2013-04-25"
    else: p["timestamp_evidence_kind"]="archive_capture_time"
    with pytest.raises(validator.G1SourceResearchError,match=match): validator._validate_evidence_eligible_probe(p,exclusions)
