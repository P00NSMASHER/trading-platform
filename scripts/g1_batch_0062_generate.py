from __future__ import annotations
import ast,copy,csv,hashlib,io,json,os,re,subprocess
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import g1_source_research as research
import g1_acquisition_manifest as acquisition
import research_receipt_rebuild as rebuild
import real_data_release_sprint as sprint

ROOT=Path.cwd()
BASE="663905045a80cb3d90a5a2d086d87d9054181317"
WORKFLOW=".github/workflows/g1-public-batch-0062-worker-2.yml"
SCRIPT="scripts/g1_batch_0062_generate.py"
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
assert len(events)==174 and len(old_exact)==82
exclusion_path=md/"g1_final_timing_exclusions.json"
exclusions=load(exclusion_path)
assert len(exclusions["exclusions"])==92

batch=Path("data/public/metadata/g1_announcement_times_batch_0062.csv")
evidence_path=Path("data/public/metadata/g1_public_batch_0062_evidence.json")
assert not batch.exists() and not evidence_path.exists()

specs=[
{"event_id":"HEJFE-873A37657E58A8CD","historical_symbol":"PAY","expected_trade":"2015-03-10 15:11:00",
 "clock":"2015-03-10T16:01:00-04:00","publisher_timestamp_text":"March 10, 2015 4:01 PM EDT",
 "release_title":"Verifone Reports Results for the First Quarter of Fiscal 2015",
 "source_reference":"https://www.streetinsider.com/Press+Releases/Verifone+Reports+Results+for+the+First+Quarter+of+Fiscal+2015/10358461.html",
 "corroboration_reference":"https://www.sec.gov/Archives/edgar/data/1312073/000131207315000007/ex991q12015pressrelease.htm",
 "corroboration_basis":"StreetInsider preserves the full Business Wire release with an explicit March 10, 2015 4:01 PM EDT publication clock; SEC Exhibit 99.1 independently matches VeriFone Systems, Inc., the release title/date, Business Wire attribution, and first-quarter fiscal 2015 results. The separately stated 1:30 PM PT conference call is not used.",
 "expected_delta":3000},
{"event_id":"HEJFE-3BBEC23702C1A375","historical_symbol":"VMW","expected_trade":"2013-07-23 15:35:00",
 "clock":"2013-07-23T16:01:00-04:00","publisher_timestamp_text":"2013-07-23T20:01:00Z",
 "release_title":"VMware Reports Second Quarter 2013 Results",
 "source_reference":"https://finance.yahoo.com/news/vmware-reports-second-quarter-2013-200100675.html",
 "corroboration_reference":"https://www.sec.gov/Archives/edgar/data/1124610/000119312513298856/d571978dex991.htm",
 "corroboration_basis":"Yahoo Finance preserves the original Marketwired VMware release and exposes published_date 2013-07-23T20:01:00Z; SEC Exhibit 99.1 independently matches VMware, July 23 2013, the second-quarter 2013 release, and reported results. The separately scheduled 5:00 p.m. ET conference call is not used.",
 "expected_delta":1560}
]
items=[]
hints_path=Path("data/public/metadata/g1_source_research_20260928.json")
hints=load(hints_path);trial=copy.deepcopy(hints)
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
      "timestamp_kind":"first_public_release","timestamp_evidence_kind":"publisher_timestamp","source_family":"preserved_wire_mirror",
      "source_grade":"B","publisher_timestamp_text":spec["publisher_timestamp_text"],"release_title":spec["release_title"],
      "source_reference":spec["source_reference"],"corroboration_reference":spec["corroboration_reference"],
      "corroboration_basis":spec["corroboration_basis"],"reviewed_on":"2026-09-30","information_asymmetry_seconds":delta}
    items.append(item)
    trial["validation_probes"].append(dict(item,probe_id=f"{spec['historical_symbol']}-batch0062",historical_event_match=True,
      exact_clock_observed=True,exact_public_release_ts=release.isoformat(),evidence_eligible=True))
research.validate_research_map(trial,exclusions)

fields=["event_id","historical_symbol","event_date","public_announcement_ts","timestamp_kind","source_grade","source_reference"]
s=io.StringIO(newline="");w=csv.DictWriter(s,fieldnames=fields,lineterminator="\n");w.writeheader()
for x in items:w.writerow({k:x[k] for k in fields})
batch.write_text(s.getvalue(),encoding="utf-8")
save(evidence_path,{"schema_version":"1","research_use_only":True,"base_main_sha":BASE,"batch_path":str(batch),"batch_sha256":sha(batch),
"items":items,"previous_exact_count":82,"expected_exact_count_after_batch":84,"expected_excluded_after_batch":90,
"previous_exact_timestamps":{k:r["public_announcement_ts"] for k,r in old_exact.items()},
"evidence_method":"Two timestamp-preserving public-wire mirrors: StreetInsider preserves the Business Wire PAY publication clock and Yahoo Finance preserves the original Marketwired VMW publisher timestamp; independent SEC Exhibit 99.1 releases corroborate identity/date/results. CI verifies chronology, event identity and deterministic receipts; conference-call, EDGAR acceptance, archive-capture, scheduled-release, date-only and inferred times are not used.",
"prohibited_substitutes":["edgar_acceptance_time","scheduled_call_time","archive_capture_time","inferred_clock","date_only"]})

ids={x["event_id"] for x in items}
exclusions["exclusions"]=[r for r in exclusions["exclusions"] if r["event_id"] not in ids]
exclusions["base_main_sha"]=BASE
exclusions["g1_state"].update(exact_resolved=84,reviewed_excluded=90,raw_exact_time_evidence_gaps=90,exact_timing_analysis_eligible=84)
save(exclusion_path,exclusions)

contract_path=Path("config/metadata_sources.public_progress.json");contract=load(contract_path)
contract["sources"].insert(0,{"source_id":"public-preserved-wire-pay-vmw-batch-0062","record_kind":"announcement_timestamp",
"source_family":"official_newswire_archive","path":str(batch),"enabled":True,"authorized":True,"data_classification":"public_official_data",
"delimiter":",","encoding":"utf-8","timezone":"America/New_York","column_map":{k:k for k in fields},
"license_reference":"Public timestamp-preserving mirrors of the original Business Wire PAY and Marketwired VMW releases, each independently corroborated by SEC Exhibit 99.1. No licensed vendor data used.",
"notes":"PAY 2015-03-10 16:01 EDT; VMW 2013-07-23 16:01 EDT. Conference-call, EDGAR acceptance, archive-capture, scheduled-release, date-only and inferred times are not used."})
contract["reviewed_announcement_exclusions"].update(expected_count=90,expected_sha256=sha(exclusion_path))
contract["purpose"]="Cumulative public point-in-time metadata: G1 has 84 exact release timestamps and 90 reviewed fail-closed exclusions; exact-timing and all independent non-synthetic release locks remain fail-closed."
save(contract_path,contract)

hints["priority_events"]=[r for r in hints.get("priority_events",[]) if r.get("event_id") not in ids]
hints["base_main_sha"]=BASE
hints["current_g1_state"].update(public_exact_batch_count=56,exact_resolved_event_records=84,reviewed_excluded_event_records=90,
 note="The latest integrated recovery is batch_0062; cumulative public exact-time batches are 56 and cumulative exact event records are 84 because some public batches resolve more than one historical event.")
for item in items:
    hints["validation_probes"].append(dict(item,probe_id=f"{item['historical_symbol']}-batch0062",historical_event_match=True,
      exact_clock_observed=True,exact_public_release_ts=item["public_announcement_ts"],evidence_eligible=False,
      disposition="RESOLVED_IN_BATCH_0062",reason="Promoted through timestamp-preserving public-wire mirror evidence with independent SEC Exhibit 99.1 corroboration."))
save(hints_path,hints)

assert rebuild.rebuild(ROOT,publish=True)["after"]["up_to_date"]
fresh=rows(md/"announcement_resolutions.csv");by={r["event_id"]:r for r in fresh};assert len(by)==174
for eid,old in old_exact.items():assert by[eid]==old
expected={"HEJFE-873A37657E58A8CD":"2015-03-10T20:01:00Z","HEJFE-3BBEC23702C1A375":"2013-07-23T20:01:00Z"}
for item in items:
    r=by[item["event_id"]];assert r["resolution_status"]=="resolved_exact_public_timestamp" and r["public_announcement_ts"]==expected[item["event_id"]]
excluded=[r for r in fresh if r["resolution_status"]=="excluded_fail_closed"]
assert len(excluded)==90 and all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in excluded)
ready=load(md/"metadata_readiness_summary.json");assert ready["announcement_exact_resolved"]==84 and ready["announcement_events_excluded"]==90
assert ready["ready_g1_exact_timing_analysis"] is False

acq=Path("data/public/metadata/g1_acquisition_manifest.json");acq.write_text(acquisition.render_manifest(acquisition.build_manifest()),encoding="utf-8")
sd=Path("data/processed/real_data_release_sprint");cp=Path("data/processed/coverage_plan_real/coverage_summary.json")
sprint.refresh_coverage(coverage_summary_path=cp,metadata_readiness_path=md/"metadata_readiness_summary.json",
 metadata_quality_path=md/"metadata_quality_summary.json",requirements_manifest_path=sd/"requirements_manifest.json",
 unresolved_gates_path=cp.parent/"unresolved_gates.csv")
status=sprint.build_status(requirements_manifest_path=sd/"requirements_manifest.json",coverage_summary_path=cp,
 metadata_readiness_path=md/"metadata_readiness_summary.json",metadata_quality_path=md/"metadata_quality_summary.json",outpath=sd/"step_status.json")
step9=next(x for x in status["steps"] if x["step"]==9);assert step9["status"]=="SOURCE_BLOCKED" and "84/174" in step9["evidence"] and "90" in step9["evidence"]

test_files=[
"tests/test_g1_source_research.py","tests/test_g1_acquisition_manifest.py","tests/test_real_data_release_sprint.py",
*sorted(str(x) for x in Path("tests").glob("test_g1_public_batch_*.py"))
]
for fn in test_files:
    p=Path(fn);txt=p.read_text()
    if fn.endswith("test_g1_source_research.py"):
        pairs=[
          ('report["exact_resolved_event_records"] == 82','report["exact_resolved_event_records"] == 84'),
          ('report["reviewed_excluded_event_records"] == 92','report["reviewed_excluded_event_records"] == 90'),
          ('state["public_exact_batch_count"] == 55','state["public_exact_batch_count"] == 56'),
          ('state["exact_resolved_event_records"] == 82','state["exact_resolved_event_records"] == 84'),
        ]
    elif fn.endswith("test_g1_acquisition_manifest.py"):
        pairs=[
          ('manifest["state"]["exact_resolved"] == 82','manifest["state"]["exact_resolved"] == 84'),
          ('manifest["state"]["acquisition_needed"] == 92','manifest["state"]["acquisition_needed"] == 90'),
          ('len(manifest["work_queue"]) == 92','len(manifest["work_queue"]) == 90'),
          ('len({row["dedupe_key"] for row in manifest["work_queue"]}) == 92','len({row["dedupe_key"] for row in manifest["work_queue"]}) == 90'),
          ('len(resolved) == 82','len(resolved) == 84'),
          ('len(unresolved) == 92','len(unresolved) == 90'),
        ]
    elif fn.endswith("test_real_data_release_sprint.py"):
        pairs=[('updated["missing_exact_announcement_timestamps"] == 92','updated["missing_exact_announcement_timestamps"] == 90')]
    else:
        pairs=[
          ('(readiness["announcement_exact_resolved"],readiness["announcement_events_excluded"]) == (82,92)','(readiness["announcement_exact_resolved"],readiness["announcement_events_excluded"]) == (84,90)'),
          ('(readiness["announcement_exact_resolved"], readiness["announcement_events_excluded"]) == (82, 92)','(readiness["announcement_exact_resolved"], readiness["announcement_events_excluded"]) == (84, 90)'),
          ('"82/174" in step9["evidence"] and "92" in step9["evidence"]','"84/174" in step9["evidence"] and "90" in step9["evidence"]'),
          ('len(excluded)==92','len(excluded)==90'),
          ('len(excluded) == 92','len(excluded) == 90'),
          ('len(ex)==92','len(ex)==90'),
          ('len(ex) == 92','len(ex) == 90'),
        ]
    for old,new in pairs:
        txt=txt.replace(old,new)
    ast.parse(txt);p.write_text(txt)

p=Path("docs/g1_announcement_times.md");txt=p.read_text()
assert "55 public exact-time batches / 82 exact-resolved" in txt
txt=txt.replace("55 public exact-time batches / 82 exact-resolved","56 public exact-time batches / 84 exact-resolved",1)
txt += """
### Batch 0062: VeriFone and VMware

Timestamp-preserving public-wire mirrors establish VeriFone Systems, Inc.'s exact first-public clock at 2015-03-10 16:01 EDT (20:01 UTC), 3,000 seconds after the frozen 15:11 EDT trade, and VMware's exact first-public clock at 2013-07-23 16:01 EDT (20:01 UTC), 1,560 seconds after the frozen 15:35 EDT trade. StreetInsider preserves the Business Wire VeriFone publication clock; Yahoo Finance preserves the original Marketwired VMware publisher timestamp. Matching SEC Exhibits 99.1 independently corroborate issuer, title, date, reporting period, and release body for both events. This advances G1 from 82 exact / 92 reviewed exclusions to 84 exact / 90 reviewed exclusions. Conference-call, scheduled-release, EDGAR acceptance, archive-capture, date-only, and inferred clocks are not used. Step 9 remains SOURCE_BLOCKED.
""";p.write_text(txt)

tp=Path("tests/test_g1_public_batch_0062.py")
ts='''import csv,json,hashlib
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
def rr(p):
    with p.open(newline="",encoding="utf-8") as h:return list(csv.DictReader(h))
def test_batch_0062():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0062_evidence.json").read_text())
    events={r["event_id"]:r for r in rr(ROOT/"data/processed/historical_events.csv")}
    resolved={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    exp={"HEJFE-873A37657E58A8CD":("PAY","2015-03-10T20:01:00Z",3000),"HEJFE-3BBEC23702C1A375":("VMW","2013-07-23T20:01:00Z",1560)}
    assert len(d["items"])==2
    for x in d["items"]:
        sym,utc,delta=exp[x["event_id"]];e=events[x["event_id"]]
        tr=datetime.fromisoformat(e["first_documented_illicit_trade_ts"]).replace(tzinfo=ZoneInfo("America/New_York"));rel=datetime.fromisoformat(x["public_announcement_ts"])
        assert e["historical_symbol"]==sym and tr<rel<=tr+timedelta(days=7) and int((rel-tr).total_seconds())==delta
        assert resolved[x["event_id"]]["public_announcement_ts"]==utc
        assert resolved[x["event_id"]]["resolution_status"]=="resolved_exact_public_timestamp"
        assert x["source_family"]=="preserved_wire_mirror" and x["source_grade"]=="B"
        assert x["corroboration_reference"].startswith("https://www.sec.gov/")
def test_batch_0062_preserves_prior():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0062_evidence.json").read_text())
    assert hashlib.sha256((ROOT/d["batch_path"]).read_bytes()).hexdigest()==d["batch_sha256"]
    by={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    for eid,stamp in d["previous_exact_timestamps"].items():assert by[eid]["public_announcement_ts"]==stamp
    ex=[r for r in by.values() if r["resolution_status"]=="excluded_fail_closed"];assert len(ex)==90
    assert all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in ex)
'''
ast.parse(ts);tp.write_text(ts)
assert rebuild.rebuild(ROOT,publish=False)["before"]["up_to_date"]

changed=set(subprocess.check_output(["git","diff","--name-only",BASE],text=True).splitlines());changed.update([str(batch),str(evidence_path),str(tp),SCRIPT])
permitted={WORKFLOW,SCRIPT,str(contract_path),str(exclusion_path),str(hints_path),str(acq),str(batch),str(evidence_path),str(tp),
"docs/g1_announcement_times.md","tests/test_g1_source_research.py","tests/test_g1_acquisition_manifest.py","tests/test_real_data_release_sprint.py",
str(cp),str(cp.parent/"unresolved_gates.csv"),str(sd/"step_status.json"),"data/processed/research_receipt_bundle.json",
"data/processed/real_data_replay/real_data_replay_status.json"} | {str(x) for x in Path("tests").glob("test_g1_public_batch_*.py")} | {str(md/name) for name in rebuild.METADATA_RECEIPTS}
assert changed<=permitted,f"Unexpected {changed-permitted}"
allowp=Path("config/release_drift_allowlist.json");allow=load(allowp);reason="G1 batch 0062 timestamp-preserving Business Wire/Marketwired mirror clocks for VeriFone and VMware; deterministic 84 exact / 90 reviewed exclusions with SEC corroboration and prior evidence preserved."
for name in sorted(changed):
    sec="intentional_release_modifications" if name in allow["intentional_release_modifications"] else "repository_additions"
    allow[sec][name]={"expected_sha256":sha(name),"reason":reason}
save(allowp,allow);changed.add(str(allowp));subprocess.run(["git","add","--",*sorted(changed)],check=True)
audit=Path("private_runtime/audit/g1-batch-0062");audit.mkdir(parents=True,exist_ok=True)
save(audit/"verification.json",{"base_main_sha":BASE,"source_head_sha":os.environ["GITHUB_SHA"],"exact":84,"reviewed_excluded":90,
"previous_exact_preserved":82,"new_events":items,"step9":"SOURCE_BLOCKED","evaluation_release_permitted":False,"deterministic_rebuild_matches":True})
print(json.dumps({"exact":84,"reviewed_excluded":90,"new_events":[x["event_id"] for x in items]},indent=2))