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
BASE="847e3b0338212accd31d7fca13e6c7282d541632"
WORKFLOW=".github/workflows/g1-public-batch-0077-worker-2.yml"
SCRIPT="scripts/g1_batch_0077_generate.py"
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
assert len(events)==174 and len(old_exact)==101
exclusion_path=md/"g1_final_timing_exclusions.json"
exclusions=load(exclusion_path)
assert len(exclusions["exclusions"])==73

batch=Path("data/public/metadata/g1_announcement_times_batch_0077.csv")
evidence_path=Path("data/public/metadata/g1_public_batch_0077_evidence.json")
assert not batch.exists() and not evidence_path.exists()

COURT_PDF="https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf"
COURT_DOCKET="https://www.courtlistener.com/docket/4324653/united-states-v-korchevsky/"
specs=[
{
 "event_id":"HEJFE-D346C6CFDFB6E581","historical_symbol":"WTS",
 "expected_trade":"2015-02-17 14:19:00","clock":"2015-02-17T16:30:00-05:00",
 "publisher_timestamp_text":"Federal court event table: WTS 2015 2/17/15 ... 2/17/15 16:30 BW",
 "release_title":"Watts Water Technologies Reports Fourth Quarter and Full Year Results for 2014 and Announces Transformation Program",
 "corroboration_reference":"https://www.sec.gov/Archives/edgar/data/795403/000110465915011302/a15-4702_1ex99d1.htm",
 "expected_delta":7860
},
{
 "event_id":"HEJFE-0273F1BFCD285E7F","historical_symbol":"THC",
 "expected_trade":"2015-02-23 15:57:00","clock":"2015-02-23T16:11:00-05:00",
 "publisher_timestamp_text":"Federal court event table: THC 2015 2/23/15 ... 2/23/15 16:11 BW",
 "release_title":"Tenet Reports Adjusted EBITDA of $646 Million for the Quarter Ended December 31, 2014",
 "corroboration_reference":"https://www.sec.gov/Archives/edgar/data/70318/000119312515058168/d878379dex991.htm",
 "expected_delta":840
},
{
 "event_id":"HEJFE-99F31DB35F001A44","historical_symbol":"DXCM",
 "expected_trade":"2015-02-25 15:44:00","clock":"2015-02-25T16:01:00-05:00",
 "publisher_timestamp_text":"Federal court event table: DXCM 2015 2/25/15 ... 2/25/15 16:01 BW",
 "release_title":"DexCom, Inc. Reports Fourth Quarter and Full Year 2014 Financial Results",
 "corroboration_reference":"https://www.sec.gov/Archives/edgar/data/1093557/000109355715000038/dxcmq4201499-1.htm",
 "expected_delta":1020
},
{
 "event_id":"HEJFE-BB62E8864F35DCD0","historical_symbol":"WLL",
 "expected_trade":"2015-02-25 15:54:00","clock":"2015-02-25T16:00:00-05:00",
 "publisher_timestamp_text":"Federal court event table: WLL 2015 2/25/15 ... 2/25/15 16:00 BW",
 "release_title":"Whiting Petroleum Corporation Announces Fourth Quarter and Full-Year 2014 Financial and Operating Results",
 "corroboration_reference":"https://www.sec.gov/Archives/edgar/data/1255474/000125547415000002/exhibit99.htm",
 "expected_delta":360
},
{
 "event_id":"HEJFE-E1B57B6A71B06A7F","historical_symbol":"CR",
 "expected_trade":"2015-04-27 15:39:00","clock":"2015-04-27T17:38:00-04:00",
 "publisher_timestamp_text":"Federal court event table: CR 2015 4/27/15 ... 4/27/15 17:38 BW",
 "release_title":"Crane Co. Reports First Quarter Results and Updates 2015 EPS Guidance",
 "corroboration_reference":"https://www.sec.gov/Archives/edgar/data/25445/000162828015002968/ex991-pressreleasexq12015.htm",
 "expected_delta":7140
}
]
items=[]
hints_path=Path("data/public/metadata/g1_source_research_20260928.json")
hints=load(hints_path);trial=copy.deepcopy(hints)
trial["validation_probes"]=[r for r in trial.get("validation_probes",[]) if r.get("event_id")!="HEJFE-C368B17FADFC15C7"]
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
      "timestamp_kind":"first_public_release","timestamp_evidence_kind":"explicit_release_clock","source_family":"federal_court_public_distribution_record",
      "source_grade":"A","publisher_timestamp_text":spec["publisher_timestamp_text"],"release_title":spec["release_title"],
      "source_reference":COURT_PDF,"court_docket_reference":COURT_DOCKET,"corroboration_reference":spec["corroboration_reference"],
      "public_distribution_explicit":True,
      "corroboration_basis":"Filed federal-court event table explicitly records this release clock and wire family; the matching SEC press-release exhibit independently corroborates issuer, release date/title and content. Scheduled calls, SEC filing timing, upload/capture times and inference are not used.",
      "reviewed_on":"2026-10-03","information_asymmetry_seconds":delta}
    items.append(item)
    trial["validation_probes"].append(dict(item,probe_id="COURT5-batch0077",historical_event_match=True,
      exact_clock_observed=True,exact_public_release_ts=release.isoformat(),evidence_eligible=True))
research.validate_research_map(trial,exclusions)

fields=["event_id","historical_symbol","event_date","public_announcement_ts","timestamp_kind","source_grade","source_reference"]
s=io.StringIO(newline="");w=csv.DictWriter(s,fieldnames=fields,lineterminator="\n");w.writeheader()
for x in items:w.writerow({k:x[k] for k in fields})
batch.write_text(s.getvalue(),encoding="utf-8")
save(evidence_path,{"schema_version":"1","research_use_only":True,"base_main_sha":BASE,"batch_path":str(batch),"batch_sha256":sha(batch),
"items":items,"previous_exact_count":101,"expected_exact_count_after_batch":106,"expected_excluded_after_batch":68,
"previous_exact_timestamps":{k:r["public_announcement_ts"] for k,r in old_exact.items()},
"evidence_method":"Filed federal-court public-distribution event table via CourtListener RECAP with explicit exact release clocks and matching SEC press-release exhibits for all five events. CI verifies chronology, event identity and deterministic receipts; upload, conference-call, EDGAR acceptance, archive-capture, scheduled-release, date-only and inferred times are not used.",
"prohibited_substitutes":["edgar_acceptance_time","scheduled_call_time","archive_capture_time","inferred_clock","date_only"]})

ids={x["event_id"] for x in items}
exclusions["exclusions"]=[r for r in exclusions["exclusions"] if r["event_id"] not in ids]
exclusions["base_main_sha"]=BASE
exclusions["g1_state"].update(exact_resolved=106,reviewed_excluded=68,raw_exact_time_evidence_gaps=68,exact_timing_analysis_eligible=106)
save(exclusion_path,exclusions)

contract_path=Path("config/metadata_sources.public_progress.json");contract=load(contract_path)
contract["sources"].insert(0,{"source_id":"public-worker2-court5-batch-0077","record_kind":"announcement_timestamp",
"source_family":"federal_court_public_distribution_record","path":str(batch),"enabled":True,"authorized":True,"data_classification":"public_official_data",
"delimiter":",","encoding":"utf-8","timezone":"America/New_York","column_map":{k:k for k in fields},
"license_reference":"Filed federal-court public-distribution event table via CourtListener RECAP, independently corroborated by matching SEC press-release exhibits. No licensed vendor data used.",
"notes":"WTS 2015-02-17 16:30 EST; THC 2015-02-23 16:11 EST; DXCM 2015-02-25 16:01 EST; WLL 2015-02-25 16:00 EST; CR 2015-04-27 17:38 EDT. Upload/call/EDGAR/archive-capture/scheduled/date-only/inferred times are not used."})
contract["reviewed_announcement_exclusions"].update(expected_count=68,expected_sha256=sha(exclusion_path))
contract["purpose"]="Cumulative public point-in-time metadata: G1 has 106 exact release timestamps and 68 reviewed fail-closed exclusions; exact-timing and all independent non-synthetic release locks remain fail-closed."
save(contract_path,contract)

hints["priority_events"]=[r for r in hints.get("priority_events",[]) if r.get("event_id") not in ids]
hints["validation_probes"]=[r for r in hints.get("validation_probes",[]) if r.get("event_id") not in ids]
hints["base_main_sha"]=BASE
hints["current_g1_state"].update(public_exact_batch_count=72,exact_resolved_event_records=106,reviewed_excluded_event_records=68,
 note="The latest integrated recovery is batch_0077; cumulative public exact-time batches are 72 and cumulative exact event records are 106 because some public batches resolve more than one historical event.")
for item in items:
    hints["validation_probes"].append(dict(item,probe_id="COURT5-batch0077",historical_event_match=True,
      exact_clock_observed=True,exact_public_release_ts=item["public_announcement_ts"],evidence_eligible=False,
      disposition="RESOLVED_IN_BATCH_0077",reason="Promoted through the filed federal-court public-distribution table with independent matching SEC press-release corroboration."))
save(hints_path,hints)

assert rebuild.rebuild(ROOT,publish=True)["after"]["up_to_date"]
fresh=rows(md/"announcement_resolutions.csv");by={r["event_id"]:r for r in fresh};assert len(by)==174
for eid,old in old_exact.items():assert by[eid]==old
expected={"HEJFE-D346C6CFDFB6E581":"2015-02-17T21:30:00Z","HEJFE-0273F1BFCD285E7F":"2015-02-23T21:11:00Z","HEJFE-99F31DB35F001A44":"2015-02-25T21:01:00Z","HEJFE-BB62E8864F35DCD0":"2015-02-25T21:00:00Z","HEJFE-E1B57B6A71B06A7F":"2015-04-27T21:38:00Z"}
for item in items:
    r=by[item["event_id"]];assert r["resolution_status"]=="resolved_exact_public_timestamp" and r["public_announcement_ts"]==expected[item["event_id"]]
excluded=[r for r in fresh if r["resolution_status"]=="excluded_fail_closed"]
assert len(excluded)==68 and all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in excluded)
ready=load(md/"metadata_readiness_summary.json");assert ready["announcement_exact_resolved"]==106 and ready["announcement_events_excluded"]==68
assert ready["ready_g1_exact_timing_analysis"] is False

acq=Path("data/public/metadata/g1_acquisition_manifest.json");acq.write_text(acquisition.render_manifest(acquisition.build_manifest()),encoding="utf-8")
sd=Path("data/processed/real_data_release_sprint");cp=Path("data/processed/coverage_plan_real/coverage_summary.json")
sprint.refresh_coverage(coverage_summary_path=cp,metadata_readiness_path=md/"metadata_readiness_summary.json",
 metadata_quality_path=md/"metadata_quality_summary.json",requirements_manifest_path=sd/"requirements_manifest.json",
 unresolved_gates_path=cp.parent/"unresolved_gates.csv")
status=sprint.build_status(requirements_manifest_path=sd/"requirements_manifest.json",coverage_summary_path=cp,
 metadata_readiness_path=md/"metadata_readiness_summary.json",metadata_quality_path=md/"metadata_quality_summary.json",outpath=sd/"step_status.json")
step9=next(x for x in status["steps"] if x["step"]==9);assert step9["status"]=="SOURCE_BLOCKED" and "106/174" in step9["evidence"] and "68" in step9["evidence"]

test_files=[
"tests/test_g1_source_research.py","tests/test_g1_acquisition_manifest.py","tests/test_real_data_release_sprint.py",
*sorted(str(x) for x in Path("tests").glob("test_g1_public_batch_*.py"))
]
for fn in test_files:
    p=Path(fn);txt=p.read_text()
    if fn.endswith("test_g1_source_research.py"):
        pairs=[
          ('report["exact_resolved_event_records"] == 101','report["exact_resolved_event_records"] == 106'),
          ('report["reviewed_excluded_event_records"] == 73','report["reviewed_excluded_event_records"] == 68'),
          ('state["public_exact_batch_count"] == 71','state["public_exact_batch_count"] == 72'),
          ('state["exact_resolved_event_records"] == 101','state["exact_resolved_event_records"] == 106'),
        ]
    elif fn.endswith("test_g1_acquisition_manifest.py"):
        pairs=[
          ('manifest["state"]["exact_resolved"] == 101','manifest["state"]["exact_resolved"] == 106'),
          ('manifest["state"]["acquisition_needed"] == 73','manifest["state"]["acquisition_needed"] == 68'),
          ('len(manifest["work_queue"]) == 73','len(manifest["work_queue"]) == 68'),
          ('len({row["dedupe_key"] for row in manifest["work_queue"]}) == 73','len({row["dedupe_key"] for row in manifest["work_queue"]}) == 68'),
          ('len(resolved) == 101','len(resolved) == 106'),
          ('len(unresolved) == 73','len(unresolved) == 68'),
        ]
    elif fn.endswith("test_real_data_release_sprint.py"):
        pairs=[('updated["missing_exact_announcement_timestamps"] == 73','updated["missing_exact_announcement_timestamps"] == 68')]
    else:
        pairs=[
          ('(readiness["announcement_exact_resolved"],readiness["announcement_events_excluded"]) == (101,73)','(readiness["announcement_exact_resolved"],readiness["announcement_events_excluded"]) == (106,68)'),
          ('(readiness["announcement_exact_resolved"], readiness["announcement_events_excluded"]) == (101, 73)','(readiness["announcement_exact_resolved"], readiness["announcement_events_excluded"]) == (106, 68)'),
          ('"99/174" in step9["evidence"] and "75" in step9["evidence"]','"101/174" in step9["evidence"] and "73" in step9["evidence"]'),
          ('"100/174" in step9["evidence"] and "74" in step9["evidence"]','"101/174" in step9["evidence"] and "73" in step9["evidence"]'),
          ('len(excluded)==68','len(excluded)==68'),
          ('len(excluded) == 68','len(excluded) == 68'),
          ('len(ex)==68','len(ex)==68'),
          ('len(ex) == 68','len(ex) == 68'),
        ]
    for old,new in pairs:
        txt=txt.replace(old,new)
    ast.parse(txt);p.write_text(txt)

p=Path("docs/g1_announcement_times.md");txt=p.read_text()
txt += """
### Batch 0077: Federal-court public-distribution recovery (WTS / THC / DXCM / WLL / CR)

A filed federal-court event table preserved through CourtListener RECAP records exact public-distribution clocks for five independently corroborated earnings releases: WTS 2015-02-17 16:30 EST, THC 2015-02-23 16:11 EST, DXCM 2015-02-25 16:01 EST, WLL 2015-02-25 16:00 EST, and CR 2015-04-27 17:38 EDT. Matching SEC press-release exhibits independently corroborate each issuer, release date/title and content. The same court-table clock column reproduces already-validated JNPR 2011-04-19 16:12 ET and EW 2011-04-20 16:01 ET clocks. This advances G1 from 101 exact / 73 reviewed exclusions to 106 exact / 68 reviewed exclusions. Upload, scheduled call, EDGAR acceptance, archive-capture, date-only and inferred clocks are not used. Step 9 remains SOURCE_BLOCKED.
""";p.write_text(txt)

tp=Path("tests/test_g1_public_batch_0077.py")
ts='''import csv,json,hashlib
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
def rr(p):
    with p.open(newline="",encoding="utf-8") as h:return list(csv.DictReader(h))
EXPECTED={
"HEJFE-D346C6CFDFB6E581":("WTS","2015-02-17T21:30:00Z",7860),
"HEJFE-0273F1BFCD285E7F":("THC","2015-02-23T21:11:00Z",840),
"HEJFE-99F31DB35F001A44":("DXCM","2015-02-25T21:01:00Z",1020),
"HEJFE-BB62E8864F35DCD0":("WLL","2015-02-25T21:00:00Z",360),
"HEJFE-E1B57B6A71B06A7F":("CR","2015-04-27T21:38:00Z",7140),
}
def test_batch_0077():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0077_evidence.json").read_text())
    events={r["event_id"]:r for r in rr(ROOT/"data/processed/historical_events.csv")}
    resolved={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    assert len(d["items"])==5
    for x in d["items"]:
        sym,utc,delta=EXPECTED[x["event_id"]];e=events[x["event_id"]]
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
def test_batch_0077_preserves_prior():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0077_evidence.json").read_text())
    assert hashlib.sha256((ROOT/d["batch_path"]).read_bytes()).hexdigest()==d["batch_sha256"]
    by={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    for eid,stamp in d["previous_exact_timestamps"].items():assert by[eid]["public_announcement_ts"]==stamp
    ex=[r for r in by.values() if r["resolution_status"]=="excluded_fail_closed"];assert len(ex)==68
    assert all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in ex)
'''
ast.parse(ts);tp.write_text(ts)
assert rebuild.rebuild(ROOT,publish=False)["before"]["up_to_date"]

changed=set(subprocess.check_output(["git","diff","--name-only",BASE],text=True).splitlines());changed.update([str(batch),str(evidence_path),str(tp),SCRIPT])
permitted={WORKFLOW,SCRIPT,str(contract_path),str(exclusion_path),str(hints_path),str(acq),str(batch),str(evidence_path),str(tp),
"docs/g1_announcement_times.md","src/metadata_resolver.py","tests/test_metadata_resolver.py","tests/test_g1_source_research.py","tests/test_g1_acquisition_manifest.py","tests/test_real_data_release_sprint.py",
str(cp),str(cp.parent/"unresolved_gates.csv"),str(sd/"step_status.json"),"data/processed/research_receipt_bundle.json",
"data/processed/real_data_replay/real_data_replay_status.json","data/public/metadata/g1_public_batch_0072_integration_spec.json"} | {str(x) for x in Path("tests").glob("test_g1_public_batch_*.py")} | {str(md/name) for name in rebuild.METADATA_RECEIPTS}
assert changed<=permitted,f"Unexpected {changed-permitted}"
allowp=Path("config/release_drift_allowlist.json");allow=load(allowp);reason="G1 batch 0077 Worker-2 federal-court exact public-distribution clocks for WTS/THC/DXCM/WLL/CR; deterministic 106 exact / 68 reviewed exclusions with CourtListener RECAP evidence, SEC corroboration and prior exact evidence preserved."
for name in sorted(changed):
    sec="intentional_release_modifications" if name in allow["intentional_release_modifications"] else "repository_additions"
    allow[sec][name]={"expected_sha256":sha(name),"reason":reason}
save(allowp,allow);changed.add(str(allowp));subprocess.run(["git","add","--",*sorted(changed)],check=True)
audit=Path("private_runtime/audit/g1-batch-0077");audit.mkdir(parents=True,exist_ok=True)
save(audit/"verification.json",{"base_main_sha":BASE,"source_head_sha":os.environ["GITHUB_SHA"],"exact":106,"reviewed_excluded":68,
"previous_exact_preserved":101,"new_events":items,"step9":"SOURCE_BLOCKED","evaluation_release_permitted":False,"deterministic_rebuild_matches":True})
print(json.dumps({"exact":106,"reviewed_excluded":68,"new_events":[x["event_id"] for x in items]},indent=2))
