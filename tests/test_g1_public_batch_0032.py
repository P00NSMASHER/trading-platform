from __future__ import annotations
import csv
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest
ROOT = Path(__file__).resolve().parents[1]
META = ROOT / "data/processed/authorized_input_real"
def rows(p):
    with p.open(newline="", encoding="utf-8") as f: return list(csv.DictReader(f))
@pytest.mark.parametrize("event_id,symbol,clock", [
    ("HEJFE-B46D4F8F72DD0212","AMD","2013-10-17T16:15:00-04:00"),
    ("HEJFE-13FC93F4D143B268","HAE","2012-01-30T08:00:00-05:00"),
])
def test_reviewed_primary_clocks_resolve_exactly(event_id,symbol,clock):
    actual = {r["event_id"]:r for r in rows(META / "announcement_resolutions.csv")}[event_id]
    frozen = {r["event_id"]:r for r in rows(ROOT / "data/processed/historical_events.csv")}[event_id]
    release = datetime.fromisoformat(clock)
    trade = datetime.fromisoformat(frozen["first_documented_illicit_trade_ts"]).replace(tzinfo=ZoneInfo("America/New_York"))
    assert actual["historical_symbol"] == symbol
    assert actual["resolution_status"] == "resolved_exact_public_timestamp"
    assert actual["source_grade"] == "A"
    assert datetime.fromisoformat(actual["public_announcement_ts"].replace("Z","+00:00")) == release
    assert trade < release <= trade + timedelta(days=7)
def test_batch_hash_and_primary_clock_semantics():
    batch=ROOT / "data/public/metadata/g1_announcement_times_batch_0032.csv"
    dossier=json.loads((ROOT / "data/public/metadata/g1_announcement_times_batch_0032_evidence.json").read_text())
    assert hashlib.sha256(batch.read_bytes()).hexdigest() == dossier["batch_sha256"]
    assert len(rows(batch)) == len(dossier["candidates"]) == 2
    assert {r["clock_evidence_kind"] for r in dossier["candidates"]} == {"publisher_timestamp","issuer_release_header"}
    assert all(r["corroboration_reference"].startswith("https://") for r in dossier["candidates"])
def test_remaining_exclusions_stay_blank_and_step9_blocked():
    readiness=json.loads((META / "metadata_readiness_summary.json").read_text())
    assert (readiness["announcement_exact_resolved"],readiness["announcement_events_excluded"]) == (64,110)
    assert readiness["ready_g1_exact_timing_analysis"] is False
    excluded=[r for r in rows(META / "announcement_resolutions.csv") if r["resolution_status"]=="excluded_fail_closed"]
    assert len(excluded)==110
    assert all(not r["public_announcement_ts"] and not r.get("information_asymmetry_seconds") for r in excluded)
    status=json.loads((ROOT / "data/processed/real_data_release_sprint/step_status.json").read_text())
    step9=next(r for r in status["steps"] if r["step"]==9)
    assert step9["status"] == "SOURCE_BLOCKED"
    assert "64/174" in step9["evidence"] and "110" in step9["evidence"]
    assert status["all_12_genuinely_complete"] is False
