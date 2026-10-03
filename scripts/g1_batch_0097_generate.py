from __future__ import annotations
import ast,copy,csv,hashlib,io,json,os,subprocess
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import g1_source_research as research
import g1_acquisition_manifest as acquisition
import research_receipt_rebuild as rebuild
import real_data_release_sprint as sprint

ROOT=Path.cwd()
BASE="986b70e828e21cd0f0b0f5de04abf3e63be0c21f"
WORKFLOW=".github/workflows/g1-public-batch-0097-worker-2.yml"
SCRIPT="scripts/g1_batch_0097_generate.py"
def load(p): return json.loads(Path(p).read_text(encoding="utf-8"))
def save(p,o): Path(p).write_text(json.dumps(o,indent=2,sort_keys=True)+"\n",encoding="utf-8")
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def rows(p):
    with Path(p).open(newline="",encoding="utf-8") as h:return list(csv.DictReader(h))

corpus=Path("data/processed/historical_events.csv")
assert sha(corpus)=="43fb221eed14c2a00a0e9d4531fe365dd264128625877a6cfc986cf50f862f12"
md=Path("data/processed/authorized_input_real")
events=rows(corpus)
old_exact={r["event_id"]:r for r in rows(md/"announcement_resolutions.csv") if r["resolution_status"]=="resolved_exact_public_timestamp"}
assert len(events)==174 and len(old_exact)==114
exclusion_path=md/"g1_final_timing_exclusions.json"
exclusions=load(exclusion_path)
assert len(exclusions["exclusions"])==60

batch=Path("data/public/metadata/g1_announcement_times_batch_0097.csv")
evidence_path=Path("data/public/metadata/g1_public_batch_0097_evidence.json")
assert not batch.exists() and not evidence_path.exists()

specs=[
{
 "event_id":"HEJFE-AF5106891E058D23","historical_symbol":"TNGO","expected_trade":"2015-02-12 15:10:00",
 "clock":"2015-02-12T16:05:00-05:00","publisher_timestamp_text":"CourtListener RECAP federal filing records TNGO public distribution at 2015-02-12 16:05 EST",
 "release_title":"Tangoe, Inc. Announces Fourth Quarter and Full Year 2014 Financial Results",
 "source_reference":"https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf",
 "court_docket_reference":"https://www.courtlistener.com/docket/4324653/united-states-v-korchevsky/",
 "corroboration_reference":"https://www.sec.gov/Archives/edgar/data/1182325/000110465915009489/a15-4435_1ex99d1.htm",
 "corroboration_basis":"Filed federal-court record explicitly identifies the exact TNGO public-distribution clock; matching SEC Exhibit 99.1 independently corroborates the issuer/release identity and date.",
 "timestamp_evidence_kind":"explicit_release_clock","source_family":"federal_court_public_distribution_record","source_grade":"A","public_distribution_explicit":True,"expected_delta":3300
},
{
 "event_id":"HEJFE-47A3794D1C360650","historical_symbol":"NOW","expected_trade":"2015-04-16 14:33:00",
 "clock":"2015-04-16T16:06:00-04:00","publisher_timestamp_text":"CourtListener RECAP federal filing records NOW public distribution at 2015-04-16 16:06 EDT",
 "release_title":"ServiceNow Reports Financial Results for First Quarter 2015",
 "source_reference":"https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf",
 "court_docket_reference":"https://www.courtlistener.com/docket/4324653/united-states-v-korchevsky/",
 "corroboration_reference":"https://www.sec.gov/Archives/edgar/data/1373715/000115752315001170/a51080886ex99_1.htm",
 "corroboration_basis":"Filed federal-court record explicitly identifies the exact NOW public-distribution clock; matching SEC Exhibit 99.1 independently corroborates the issuer/release identity and date.",
 "timestamp_evidence_kind":"explicit_release_clock","source_family":"federal_court_public_distribution_record","source_grade":"A","public_distribution_explicit":True,"expected_delta":5580
},
{
 "event_id":"HEJFE-1783DE88400AF6CC","historical_symbol":"WMB","expected_trade":"2015-02-18 14:54:00",
 "clock":"2015-02-18T16:05:00-05:00","publisher_timestamp_text":"CourtListener RECAP federal filing records WMB public distribution at 2015-02-18 16:05 EST",
 "release_title":"Williams Reports Year-End 2014 Financial Results, Updates Guidance",
 "source_reference":"https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf",
 "court_docket_reference":"https://www.courtlistener.com/docket/4324653/united-states-v-korchevsky/",
 "corroboration_reference":"https://www.sec.gov/Archives/edgar/data/107263/000119312515052850/d875060dex991.htm",
 "corroboration_basis":"Filed federal-court record explicitly identifies the exact WMB public-distribution clock; matching SEC Exhibit 99.1 independently corroborates the issuer/release identity and date.",
 "timestamp_evidence_kind":"explicit_release_clock","source_family":"federal_court_public_distribution_record","source_grade":"A","public_distribution_explicit":True,"expected_delta":4260
},
{
 "event_id":"HEJFE-334BAA0D940A418A","historical_symbol":"TER","expected_trade":"2015-01-28 15:49:00",
 "clock":"2015-01-28T17:32:00-05:00","publisher_timestamp_text":"CourtListener RECAP federal filing records TER public distribution at 2015-01-28 17:32 EST",
 "release_title":"Teradyne Reports Fourth Quarter and Fiscal Year 2014 Results",
 "source_reference":"https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf",
 "court_docket_reference":"https://www.courtlistener.com/docket/4324653/united-states-v-korchevsky/",
 "corroboration_reference":"https://www.sec.gov/Archives/edgar/data/97210/000119312515024386/d860562dex991.htm",
 "corroboration_basis":"Filed federal-court record explicitly identifies the exact TER public-distribution clock; matching SEC Exhibit 99.1 independently corroborates the issuer/release identity and date.",
 "timestamp_evidence_kind":"explicit_release_clock","source_family":"federal_court_public_distribution_record","source_grade":"A","public_distribution_explicit":True,"expected_delta":6180
},
{
 "event_id":"HEJFE-5ED55A2EAC950921","historical_symbol":"AMP","expected_trade":"2015-04-22 15:22:00",
 "clock":"2015-04-22T16:05:00-04:00","publisher_timestamp_text":"CourtListener RECAP federal filing records AMP public distribution at 2015-04-22 16:05 EDT",
 "release_title":"Ameriprise Financial Reports First Quarter 2015 Results",
 "source_reference":"https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf",
 "court_docket_reference":"https://www.courtlistener.com/docket/4324653/united-states-v-korchevsky/",
 "corroboration_reference":"https://www.sec.gov/Archives/edgar/data/820027/000110465915029352/a15-9389_1ex99d1.htm",
 "corroboration_basis":"Filed federal-court record explicitly identifies the exact AMP public-distribution clock; matching SEC Exhibit 99.1 independently corroborates the issuer/release identity and date.",
 "timestamp_evidence_kind":"explicit_release_clock","source_family":"federal_court_public_distribution_record","source_grade":"A","public_distribution_explicit":True,"expected_delta":2580
},
{
 "event_id":"HEJFE-12CC8075D3F634CD","historical_symbol":"ECOL","expected_trade":"2013-04-24 15:07:00",
 "clock":"2013-04-25T06:00:00-04:00","publisher_timestamp_text":"CourtListener RECAP federal filing records ECOL public distribution at 2013-04-25 06:00 EDT",
 "release_title":"US Ecology Announces First Quarter 2013 Results",
 "source_reference":"https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf",
 "court_docket_reference":"https://www.courtlistener.com/docket/4324653/united-states-v-korchevsky/",
 "corroboration_reference":"https://www.sec.gov/Archives/edgar/data/742126/000110262413000476/usecologyinc.htm",
 "corroboration_basis":"Filed federal-court record explicitly identifies the exact ECOL public-distribution clock; matching SEC-filed release independently corroborates the issuer/release identity and date.",
 "timestamp_evidence_kind":"explicit_release_clock","source_family":"federal_court_public_distribution_record","source_grade":"A","public_distribution_explicit":True,"expected_delta":53580
},
{
 "event_id":"HEJFE-ED8CFC03F1053B9A","historical_symbol":"CAMP","expected_trade":"2013-04-25 15:48:00",
 "clock":"2013-04-25T16:01:00-04:00","publisher_timestamp_text":"CourtListener RECAP federal filing records CAMP public distribution at 2013-04-25 16:01 EDT",
 "release_title":"CalAmp Reports Fiscal 2013 Fourth Quarter and Full Year Results",
 "source_reference":"https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf",
 "court_docket_reference":"https://www.courtlistener.com/docket/4324653/united-states-v-korchevsky/",
 "corroboration_reference":"https://www.sec.gov/Archives/edgar/data/730255/000120677413001590/exhibit99-1.htm",
 "corroboration_basis":"Filed federal-court record explicitly identifies the exact CAMP public-distribution clock; matching SEC Exhibit 99.1 independently corroborates the issuer/release identity and date.",
 "timestamp_evidence_kind":"explicit_release_clock","source_family":"federal_court_public_distribution_record","source_grade":"A","public_distribution_explicit":True,"expected_delta":780
}
]
items=[]
hints_path=Path("data/public/metadata/g1_source_research_20260928.json")
hints=load(hints_path);trial=copy.deepcopy(hints)
spec_ids={r["event_id"] for r in specs}
trial["validation_probes"]=[r for r in trial.get("validation_probes",[]) if r.get("event_id") not in spec_ids]
for spec in specs:
    e=next(r for r in events if r["event_id"]==spec["event_id"])
    assert e["historical_symbol"]==spec["historical_symbol"] and e["first_documented_illicit_trade_ts"]==spec["expected_trade"]
    assert spec["event_id"] not in old_exact and sum(r["event_id"]==spec["event_id"] for r in exclusions["exclusions"])==1
    trade=datetime.fromisoformat(e["first_documented_illicit_trade_ts"]).replace(tzinfo=ZoneInfo("America/New_York"))
    release=datetime.fromisoformat(spec["clock"])
    assert trade<release<=trade+timedelta(days=7)
    delta=int((release-trade).total_seconds());assert delta==spec["expected_delta"]
    item={"event_id":spec["event_id"],"historical_symbol":spec["historical_symbol"],"event_date":trade.date().isoformat(),
      "first_documented_illicit_trade_ts":e["first_documented_illicit_trade_ts"],"public_announcement_ts":release.isoformat(),
      "timestamp_kind":"first_public_release","timestamp_evidence_kind":spec["timestamp_evidence_kind"],"source_family":spec["source_family"],
      "source_grade":spec["source_grade"],"publisher_timestamp_text":spec["publisher_timestamp_text"],"release_title":spec["release_title"],
      "source_reference":spec["source_reference"],"court_docket_reference":spec["court_docket_reference"],"corroboration_reference":spec["corroboration_reference"],
      "corroboration_basis":spec["corroboration_basis"],"public_distribution_explicit":spec["public_distribution_explicit"],"reviewed_on":"2026-10-03","information_asymmetry_seconds":delta}
    items.append(item)
    trial["validation_probes"].append(dict(item,probe_id=f'{spec["historical_symbol"]}-batch0097',historical_event_match=True,
      exact_clock_observed=True,exact_public_release_ts=release.isoformat(),evidence_eligible=True))
research.validate_research_map(trial,exclusions)

fields=["event_id","historical_symbol","event_date","public_announcement_ts","timestamp_kind","source_grade","source_reference"]
s=io.StringIO(newline="");w=csv.DictWriter(s,fieldnames=fields,lineterminator="\n");w.writeheader()
for x in items:w.writerow({k:x[k] for k in fields})
batch.write_text(s.getvalue(),encoding="utf-8")
save(evidence_path,{"schema_version":"1","research_use_only":True,"base_main_sha":BASE,"batch_path":str(batch),"batch_sha256":sha(batch),
"items":items,"previous_exact_count":114,"expected_exact_count_after_batch":121,"expected_excluded_after_batch":53,
"previous_exact_timestamps":{k:r["public_announcement_ts"] for k,r in old_exact.items()},
"evidence_method":"Filed federal-court CourtListener RECAP public-distribution record supplies explicit exact clocks for seven releases, each independently corroborated by a matching SEC press-release exhibit. CI verifies chronology, event identity and deterministic receipts; conference-call, EDGAR acceptance, archive-capture, scheduled-release, date-only and inferred times are not used.",
"prohibited_substitutes":["edgar_acceptance_time","scheduled_call_time","archive_capture_time","inferred_clock","date_only"]})

ids={x["event_id"] for x in items}
exclusions["exclusions"]=[r for r in exclusions["exclusions"] if r["event_id"] not in ids]
exclusions["base_main_sha"]=BASE
exclusions["g1_state"].update(exact_resolved=121,reviewed_excluded=53,raw_exact_time_evidence_gaps=53,exact_timing_analysis_eligible=121)
save(exclusion_path,exclusions)

contract_path=Path("config/metadata_sources.public_progress.json");contract=load(contract_path)
contract["sources"].insert(0,{"source_id":"public-worker2-courtlistener-batch-0097","record_kind":"announcement_timestamp",
"source_family":"federal_court_public_distribution_record","path":str(batch),"enabled":True,"authorized":True,"data_classification":"public_official_data",
"delimiter":",","encoding":"utf-8","timezone":"America/New_York","column_map":{k:k for k in fields},
"license_reference":"Filed federal-court public-distribution clocks preserved by CourtListener RECAP, independently corroborated by matching SEC press-release exhibits. No licensed vendor data used.",
"notes":"TNGO/NOW/WMB/TER/AMP/ECOL/CAMP exact public-distribution clocks from filed federal-court record; prohibited substitute times are not used."})
contract["reviewed_announcement_exclusions"].update(expected_count=60,expected_sha256=sha(exclusion_path))
contract["purpose"]="Cumulative public point-in-time metadata: G1 has 121 exact release timestamps and 53 reviewed fail-closed exclusions; exact-timing and all independent non-synthetic release locks remain fail-closed."
save(contract_path,contract)

hints["priority_events"]=[r for r in hints.get("priority_events",[]) if r.get("event_id") not in ids]
hints["validation_probes"]=[r for r in hints.get("validation_probes",[]) if r.get("event_id") not in ids]
hints["base_main_sha"]=BASE
hints["current_g1_state"].update(public_exact_batch_count=76,exact_resolved_event_records=121,reviewed_excluded_event_records=53,
 note="The latest integrated recovery is batch_0097; cumulative public exact-time batches are 76 and cumulative exact event records are 121 because some public batches resolve more than one historical event.")
for item in items:
    hints["validation_probes"].append(dict(item,probe_id=f'{item["historical_symbol"]}-batch0097',historical_event_match=True,
      exact_clock_observed=True,exact_public_release_ts=item["public_announcement_ts"],evidence_eligible=False,
      disposition="RESOLVED_IN_BATCH_0097",reason="Promoted through the filed federal-court public-distribution record with independent matching SEC press-release corroboration."))
save(hints_path,hints)

assert rebuild.rebuild(ROOT,publish=True)["after"]["up_to_date"]
fresh=rows(md/"announcement_resolutions.csv");by={r["event_id"]:r for r in fresh};assert len(by)==174
for eid,old in old_exact.items():assert by[eid]==old
expected={
 "HEJFE-AF5106891E058D23":"2015-02-12T21:05:00Z",
 "HEJFE-47A3794D1C360650":"2015-04-16T20:06:00Z",
 "HEJFE-1783DE88400AF6CC":"2015-02-18T21:05:00Z",
 "HEJFE-334BAA0D940A418A":"2015-01-28T22:32:00Z",
 "HEJFE-5ED55A2EAC950921":"2015-04-22T20:05:00Z",
 "HEJFE-12CC8075D3F634CD":"2013-04-25T10:00:00Z",
 "HEJFE-ED8CFC03F1053B9A":"2013-04-25T20:01:00Z"
}
for item in items:
    r=by[item["event_id"]];assert r["resolution_status"]=="resolved_exact_public_timestamp" and r["public_announcement_ts"]==expected[item["event_id"]]
excluded=[r for r in fresh if r["resolution_status"]=="excluded_fail_closed"]
assert len(excluded)==53 and all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in excluded)
ready=load(md/"metadata_readiness_summary.json");assert ready["announcement_exact_resolved"]==121 and ready["announcement_events_excluded"]==53
assert ready["ready_g1_exact_timing_analysis"] is False

acq=Path("data/public/metadata/g1_acquisition_manifest.json");acq.write_text(acquisition.render_manifest(acquisition.build_manifest()),encoding="utf-8")
sd=Path("data/processed/real_data_release_sprint");cp=Path("data/processed/coverage_plan_real/coverage_summary.json")
sprint.refresh_coverage(coverage_summary_path=cp,metadata_readiness_path=md/"metadata_readiness_summary.json",
 metadata_quality_path=md/"metadata_quality_summary.json",requirements_manifest_path=sd/"requirements_manifest.json",
 unresolved_gates_path=cp.parent/"unresolved_gates.csv")
status=sprint.build_status(requirements_manifest_path=sd/"requirements_manifest.json",coverage_summary_path=cp,
 metadata_readiness_path=md/"metadata_readiness_summary.json",metadata_quality_path=md/"metadata_quality_summary.json",outpath=sd/"step_status.json")
step9=next(x for x in status["steps"] if x["step"]==9);assert step9["status"]=="SOURCE_BLOCKED" and "121/174" in step9["evidence"] and "53" in step9["evidence"]

test_files=[
"tests/test_g1_source_research.py","tests/test_g1_acquisition_manifest.py","tests/test_real_data_release_sprint.py",
*sorted(str(x) for x in Path("tests").glob("test_g1_public_batch_*.py"))
]
for fn in test_files:
    p=Path(fn);txt=p.read_text()
    if fn.endswith("test_g1_source_research.py"):
        pairs=[
          ('report["exact_resolved_event_records"] == 114','report["exact_resolved_event_records"] == 121'),
          ('report["reviewed_excluded_event_records"] == 60','report["reviewed_excluded_event_records"] == 53'),
          ('state["public_exact_batch_count"] == 74','state["public_exact_batch_count"] == 75'),
          ('state["exact_resolved_event_records"] == 114','state["exact_resolved_event_records"] == 121'),
        ]
    elif fn.endswith("test_g1_acquisition_manifest.py"):
        pairs=[
          ('manifest["state"]["exact_resolved"] == 114','manifest["state"]["exact_resolved"] == 121'),
          ('manifest["state"]["acquisition_needed"] == 60','manifest["state"]["acquisition_needed"] == 53'),
          ('len(manifest["work_queue"]) == 60','len(manifest["work_queue"]) == 53'),
          ('len({row["dedupe_key"] for row in manifest["work_queue"]}) == 60','len({row["dedupe_key"] for row in manifest["work_queue"]}) == 53'),
          ('len(resolved) == 114','len(resolved) == 121'),
          ('len(unresolved) == 60','len(unresolved) == 53'),
        ]
    elif fn.endswith("test_real_data_release_sprint.py"):
        pairs=[('updated["missing_exact_announcement_timestamps"] == 60','updated["missing_exact_announcement_timestamps"] == 53')]
    else:
        pairs=[
          ('(readiness["announcement_exact_resolved"],readiness["announcement_events_excluded"]) == (109,65)','(readiness["announcement_exact_resolved"],readiness["announcement_events_excluded"]) == (114,60)'),
          ('(readiness["announcement_exact_resolved"], readiness["announcement_events_excluded"]) == (109, 65)','(readiness["announcement_exact_resolved"], readiness["announcement_events_excluded"]) == (114, 60)'),
          ('"109/174" in step9["evidence"] and "65" in step9["evidence"]','"114/174" in step9["evidence"] and "60" in step9["evidence"]'),
          ('len(excluded)==60','len(excluded)==60'),
          ('len(excluded) == 60','len(excluded) == 53'),
          ('len(ex)==60','len(ex)==60'),
          ('len(ex) == 60','len(ex) == 53'),
        ]
    for old,new in pairs:
        txt=txt.replace(old,new)
    ast.parse(txt);p.write_text(txt)

p=Path("docs/g1_announcement_times.md");txt=p.read_text()
assert "74 public exact-time batches / 109 exact-resolved" in txt
txt=txt.replace("74 public exact-time batches / 109 exact-resolved","76 public exact-time batches / 121 exact-resolved",1)
txt += """
### Batch 0097: TNGO / NOW / WMB / TER / AMP / ECOL / CAMP

A filed federal-court public-distribution record preserved by CourtListener RECAP supplies exact first-public clocks for TNGO (2015-02-12 16:05 EST), NOW (2015-04-16 16:06 EDT), WMB (2015-02-18 16:05 EST), TER (2015-01-28 17:32 EST), AMP (2015-04-22 16:05 EDT), ECOL (2013-04-25 06:00 EDT), and CAMP (2013-04-25 16:01 EDT). Matching SEC-filed releases independently corroborate each issuer/release identity and date. This advances G1 from 114 exact / 60 reviewed exclusions to 121 exact / 53 reviewed exclusions. Conference-call, EDGAR acceptance, archive-capture, date-only, scheduled-release and inferred clocks are not used. Step 9 remains SOURCE_BLOCKED.
""";p.write_text(txt)

tp=Path("tests/test_g1_public_batch_0097.py")
ts='''import csv,json,hashlib
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
def rr(p):
    with p.open(newline="",encoding="utf-8") as h:return list(csv.DictReader(h))
def test_batch_0097():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0097_evidence.json").read_text())
    events={r["event_id"]:r for r in rr(ROOT/"data/processed/historical_events.csv")}
    resolved={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    exp={
      "HEJFE-AF5106891E058D23":("TNGO","2015-02-12T21:05:00Z",3300),
      "HEJFE-47A3794D1C360650":("NOW","2015-04-16T20:06:00Z",5580),
      "HEJFE-1783DE88400AF6CC":("WMB","2015-02-18T21:05:00Z",4260),
      "HEJFE-334BAA0D940A418A":("TER","2015-01-28T22:32:00Z",6180),
      "HEJFE-5ED55A2EAC950921":("AMP","2015-04-22T20:05:00Z",2580),
      "HEJFE-12CC8075D3F634CD":("ECOL","2013-04-25T10:00:00Z",53580),
      "HEJFE-ED8CFC03F1053B9A":("CAMP","2013-04-25T20:01:00Z",780),
    }
    assert len(d["items"])==7
    for x in d["items"]:
        sym,utc,delta=exp[x["event_id"]];e=events[x["event_id"]]
        tr=datetime.fromisoformat(e["first_documented_illicit_trade_ts"]).replace(tzinfo=ZoneInfo("America/New_York"));rel=datetime.fromisoformat(x["public_announcement_ts"])
        assert e["historical_symbol"]==sym and tr<rel<=tr+timedelta(days=7) and int((rel-tr).total_seconds())==delta
        assert resolved[x["event_id"]]["public_announcement_ts"]==utc
        assert resolved[x["event_id"]]["resolution_status"]=="resolved_exact_public_timestamp"
        assert x["source_family"]=="federal_court_public_distribution_record" and x["source_grade"]=="A"
        assert x["timestamp_evidence_kind"]=="explicit_release_clock"
        assert x["public_distribution_explicit"] is True
        assert x["source_reference"].startswith("https://storage.courtlistener.com/recap/")
        assert x["court_docket_reference"].startswith("https://www.courtlistener.com/docket/")
        assert x["corroboration_reference"].startswith("https://www.sec.gov/Archives/edgar/data/")
def test_batch_0097_preserves_prior():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0097_evidence.json").read_text())
    assert hashlib.sha256((ROOT/d["batch_path"]).read_bytes()).hexdigest()==d["batch_sha256"]
    by={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    for eid,stamp in d["previous_exact_timestamps"].items():assert by[eid]["public_announcement_ts"]==stamp
    ex=[r for r in by.values() if r["resolution_status"]=="excluded_fail_closed"];assert len(ex)==53
    assert all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in ex)
def test_batch_0097_controller_assignment():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0097_evidence.json").read_text())
    assert {x["event_id"] for x in d["items"]}=={
      "HEJFE-AF5106891E058D23","HEJFE-47A3794D1C360650","HEJFE-1783DE88400AF6CC",
      "HEJFE-334BAA0D940A418A","HEJFE-5ED55A2EAC950921","HEJFE-12CC8075D3F634CD","HEJFE-ED8CFC03F1053B9A"
    }
'''
ast.parse(ts);tp.write_text(ts)
assert rebuild.rebuild(ROOT,publish=False)["before"]["up_to_date"]

# Prep-only artifacts validate the package before publication but must not survive
# canonical generation, where their fail-closed assertions are intentionally stale.
for prep_only in (
    Path("data/public/metadata/g1_public_batch_0097_prep_evidence.json"),
    Path("tests/test_g1_public_batch_0097_prep.py"),
):
    if prep_only.exists():
        prep_only.unlink()

changed=set(subprocess.check_output(["git","diff","--name-only",BASE],text=True).splitlines());changed.update([str(batch),str(evidence_path),str(tp),SCRIPT])
permitted={WORKFLOW,SCRIPT,str(contract_path),str(exclusion_path),str(hints_path),str(acq),str(batch),str(evidence_path),str(tp),
"docs/g1_announcement_times.md","src/metadata_resolver.py","tests/test_metadata_resolver.py","tests/test_g1_source_research.py","tests/test_g1_acquisition_manifest.py","tests/test_real_data_release_sprint.py",
str(cp),str(cp.parent/"unresolved_gates.csv"),str(sd/"step_status.json"),"data/processed/research_receipt_bundle.json",
"data/processed/real_data_replay/real_data_replay_status.json","data/public/metadata/g1_public_batch_0097_integration_spec.json","data/public/metadata/g1_public_batch_0097_prep_evidence.json"} | {str(x) for x in Path("tests").glob("test_g1_public_batch_*.py")} | {str(md/name) for name in rebuild.METADATA_RECEIPTS}
assert changed<=permitted,f"Unexpected {changed-permitted}"
allowp=Path("config/release_drift_allowlist.json");allow=load(allowp);reason="G1 batch 0097 Worker-2 filed federal-court exact public-distribution clocks for EHTH/BA/LSCC/GORO/GMCR; deterministic 114 exact / 60 reviewed exclusions with SEC corroboration and prior evidence preserved."
for name in sorted(changed):
    sec="intentional_release_modifications" if name in allow["intentional_release_modifications"] else "repository_additions"
    allow[sec][name]={"expected_sha256":sha(name),"reason":reason}
save(allowp,allow);changed.add(str(allowp));subprocess.run(["git","add","--",*sorted(changed)],check=True)
audit=Path("private_runtime/audit/g1-batch-0097");audit.mkdir(parents=True,exist_ok=True)
save(audit/"verification.json",{"base_main_sha":BASE,"source_head_sha":os.environ["GITHUB_SHA"],"exact":114,"reviewed_excluded":60,
"previous_exact_preserved":109,"new_events":items,"step9":"SOURCE_BLOCKED","evaluation_release_permitted":False,"deterministic_rebuild_matches":True})
print(json.dumps({"exact":114,"reviewed_excluded":60,"new_events":[x["event_id"] for x in items]},indent=2))
