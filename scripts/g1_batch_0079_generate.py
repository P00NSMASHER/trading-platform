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
BASE="b5c830d77236e23f63422c759bc49b6ded851ce9"
WORKFLOW=".github/workflows/g1-public-batch-0079-worker-4.yml"
SCRIPT="scripts/g1_batch_0079_generate.py"
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
assert len(events)==174 and len(old_exact)==93
exclusion_path=md/"g1_final_timing_exclusions.json"
exclusions=load(exclusion_path)
assert len(exclusions["exclusions"])==81

batch=Path("data/public/metadata/g1_announcement_times_batch_0079.csv")
evidence_path=Path("data/public/metadata/g1_public_batch_0079_evidence.json")
assert not batch.exists() and not evidence_path.exists()

specs=[{
 "event_id":"HEJFE-D7FD00AF94DD8F41",
 "historical_symbol":"JNPR",
 "expected_trade":"2011-04-19 15:50:00",
 "clock":"2011-04-19T16:12:00-04:00",
 "publisher_timestamp_text":"InvestorsHub/ADVFN preserved Marketwire release: Tuesday, April 19, 2011 16:12ET",
 "release_title":"Juniper Networks Reports Preliminary First Quarter 2011 Financial Results",
 "source_reference":"https://investorshub.advfn.com/Juniper-Networks-Inc-JNPR-4985?nextStart=110",
 "corroboration_reference":"https://www.sec.gov/Archives/edgar/data/1043604/000095012311036828/f58994exv99w1.htm",
 "corroboration_basis":"InvestorsHub/ADVFN preserves the matching Marketwire release title, body, Marketwire attribution/date, and explicit April 19 2011 16:12 ET timestamp. SEC Exhibit 99.1 independently matches Juniper Networks, the April 19 2011 Q1 release title/date, reported quarter, metrics, and release body. The separately scheduled 17:00 ET conference call and SEC filing timing are not used.",
 "timestamp_evidence_kind":"publisher_timestamp",
 "source_family":"preserved_wire_mirror",
 "source_grade":"A",
 "expected_delta":1320
}]
items=[]
hints_path=Path("data/public/metadata/g1_source_research_20260928.json")
hints=load(hints_path);trial=copy.deepcopy(hints)
trial["validation_probes"]=[r for r in trial.get("validation_probes",[]) if r.get("event_id")!="HEJFE-D7FD00AF94DD8F41"]
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
      "source_reference":spec["source_reference"],"corroboration_reference":spec["corroboration_reference"],
      "corroboration_basis":spec["corroboration_basis"],"reviewed_on":"2026-10-02","information_asymmetry_seconds":delta}
    items.append(item)
    trial["validation_probes"].append(dict(item,probe_id="JNPR-batch0079",historical_event_match=True,
      exact_clock_observed=True,exact_public_release_ts=release.isoformat(),evidence_eligible=True))
research.validate_research_map(trial,exclusions)

fields=["event_id","historical_symbol","event_date","public_announcement_ts","timestamp_kind","source_grade","source_reference"]
s=io.StringIO(newline="");w=csv.DictWriter(s,fieldnames=fields,lineterminator="\n");w.writeheader()
for x in items:w.writerow({k:x[k] for k in fields})
batch.write_text(s.getvalue(),encoding="utf-8")
save(evidence_path,{"schema_version":"1","research_use_only":True,"base_main_sha":BASE,"batch_path":str(batch),"batch_sha256":sha(batch),
"items":items,"previous_exact_count":93,"expected_exact_count_after_batch":94,"expected_excluded_after_batch":80,
"previous_exact_timestamps":{k:r["public_announcement_ts"] for k,r in old_exact.items()},
"evidence_method":"One timestamp-preserving InvestorsHub/ADVFN Marketwire mirror records Juniper Networks' exact first-public release clock at 16:12 ET, independently corroborated by matching SEC Exhibit 99.1. CI verifies chronology, event identity and deterministic receipts; conference-call, EDGAR acceptance, archive-capture, scheduled-release, date-only and inferred times are not used.",
"prohibited_substitutes":["edgar_acceptance_time","scheduled_call_time","archive_capture_time","inferred_clock","date_only"]})

ids={x["event_id"] for x in items}
exclusions["exclusions"]=[r for r in exclusions["exclusions"] if r["event_id"] not in ids]
exclusions["base_main_sha"]=BASE
exclusions["g1_state"].update(exact_resolved=94,reviewed_excluded=80,raw_exact_time_evidence_gaps=80,exact_timing_analysis_eligible=94)
save(exclusion_path,exclusions)

contract_path=Path("config/metadata_sources.public_progress.json");contract=load(contract_path)
contract["sources"].insert(0,{"source_id":"public-worker4-jnpr-batch-0079","record_kind":"announcement_timestamp",
"source_family":"preserved_wire_mirror","path":str(batch),"enabled":True,"authorized":True,"data_classification":"public_official_data",
"delimiter":",","encoding":"utf-8","timezone":"America/New_York","column_map":{k:k for k in fields},
"license_reference":"Public timestamp-preserving Marketwire mirror for JNPR, independently corroborated by SEC Exhibit 99.1. No licensed vendor data used.",
"notes":"JNPR 2011-04-19 16:12 EDT. Conference-call, EDGAR acceptance, archive-capture, scheduled-release, date-only and inferred times are not used."})
contract["reviewed_announcement_exclusions"].update(expected_count=80,expected_sha256=sha(exclusion_path))
contract["purpose"]="Cumulative public point-in-time metadata: G1 has 94 exact release timestamps and 80 reviewed fail-closed exclusions; exact-timing and all independent non-synthetic release locks remain fail-closed."
save(contract_path,contract)

hints["priority_events"]=[r for r in hints.get("priority_events",[]) if r.get("event_id") not in ids]
hints["validation_probes"]=[r for r in hints.get("validation_probes",[]) if r.get("event_id") not in ids]
hints["base_main_sha"]=BASE
hints["current_g1_state"].update(public_exact_batch_count=64,exact_resolved_event_records=94,reviewed_excluded_event_records=80,
 note="The latest integrated recovery is batch_0079; cumulative public exact-time batches are 64 and cumulative exact event records are 94 because some public batches resolve more than one historical event.")
for item in items:
    hints["validation_probes"].append(dict(item,probe_id="JNPR-batch0079",historical_event_match=True,
      exact_clock_observed=True,exact_public_release_ts=item["public_announcement_ts"],evidence_eligible=False,
      disposition="RESOLVED_IN_BATCH_0079",reason="Promoted through timestamp-preserving Business Wire mirror evidence with independent SEC Exhibit 99.1 corroboration."))
save(hints_path,hints)

assert rebuild.rebuild(ROOT,publish=True)["after"]["up_to_date"]
fresh=rows(md/"announcement_resolutions.csv");by={r["event_id"]:r for r in fresh};assert len(by)==174
for eid,old in old_exact.items():assert by[eid]==old
expected={"HEJFE-D7FD00AF94DD8F41":"2011-04-19T20:12:00Z"}
for item in items:
    r=by[item["event_id"]];assert r["resolution_status"]=="resolved_exact_public_timestamp" and r["public_announcement_ts"]==expected[item["event_id"]]
excluded=[r for r in fresh if r["resolution_status"]=="excluded_fail_closed"]
assert len(excluded)==80 and all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in excluded)
ready=load(md/"metadata_readiness_summary.json");assert ready["announcement_exact_resolved"]==94 and ready["announcement_events_excluded"]==80
assert ready["ready_g1_exact_timing_analysis"] is False

acq=Path("data/public/metadata/g1_acquisition_manifest.json");acq.write_text(acquisition.render_manifest(acquisition.build_manifest()),encoding="utf-8")
sd=Path("data/processed/real_data_release_sprint");cp=Path("data/processed/coverage_plan_real/coverage_summary.json")
sprint.refresh_coverage(coverage_summary_path=cp,metadata_readiness_path=md/"metadata_readiness_summary.json",
 metadata_quality_path=md/"metadata_quality_summary.json",requirements_manifest_path=sd/"requirements_manifest.json",
 unresolved_gates_path=cp.parent/"unresolved_gates.csv")
status=sprint.build_status(requirements_manifest_path=sd/"requirements_manifest.json",coverage_summary_path=cp,
 metadata_readiness_path=md/"metadata_readiness_summary.json",metadata_quality_path=md/"metadata_quality_summary.json",outpath=sd/"step_status.json")
step9=next(x for x in status["steps"] if x["step"]==9);assert step9["status"]=="SOURCE_BLOCKED" and "94/174" in step9["evidence"] and "80" in step9["evidence"]

test_files=[
"tests/test_g1_source_research.py","tests/test_g1_acquisition_manifest.py","tests/test_real_data_release_sprint.py",
*sorted(str(x) for x in Path("tests").glob("test_g1_public_batch_*.py"))
]
for fn in test_files:
    p=Path(fn);txt=p.read_text()
    if fn.endswith("test_g1_source_research.py"):
        pairs=[
          ('report["exact_resolved_event_records"] == 93','report["exact_resolved_event_records"] == 94'),
          ('report["reviewed_excluded_event_records"] == 81','report["reviewed_excluded_event_records"] == 80'),
          ('state["public_exact_batch_count"] == 63','state["public_exact_batch_count"] == 64'),
          ('state["exact_resolved_event_records"] == 93','state["exact_resolved_event_records"] == 94'),
        ]
    elif fn.endswith("test_g1_acquisition_manifest.py"):
        pairs=[
          ('manifest["state"]["exact_resolved"] == 93','manifest["state"]["exact_resolved"] == 94'),
          ('manifest["state"]["acquisition_needed"] == 81','manifest["state"]["acquisition_needed"] == 80'),
          ('len(manifest["work_queue"]) == 81','len(manifest["work_queue"]) == 80'),
          ('len({row["dedupe_key"] for row in manifest["work_queue"]}) == 81','len({row["dedupe_key"] for row in manifest["work_queue"]}) == 80'),
          ('len(resolved) == 93','len(resolved) == 94'),
          ('len(unresolved) == 81','len(unresolved) == 80'),
        ]
    elif fn.endswith("test_real_data_release_sprint.py"):
        pairs=[('updated["missing_exact_announcement_timestamps"] == 81','updated["missing_exact_announcement_timestamps"] == 80')]
    else:
        pairs=[
          ('(readiness["announcement_exact_resolved"],readiness["announcement_events_excluded"]) == (93,81)','(readiness["announcement_exact_resolved"],readiness["announcement_events_excluded"]) == (94,80)'),
          ('(readiness["announcement_exact_resolved"], readiness["announcement_events_excluded"]) == (93, 81)','(readiness["announcement_exact_resolved"], readiness["announcement_events_excluded"]) == (94, 80)'),
          ('"93/174" in step9["evidence"] and "81" in step9["evidence"]','"94/174" in step9["evidence"] and "80" in step9["evidence"]'),
          ('len(excluded)==81','len(excluded)==80'),
          ('len(excluded) == 81','len(excluded) == 80'),
          ('len(ex)==81','len(ex)==80'),
          ('len(ex) == 81','len(ex) == 80'),
        ]
    for old,new in pairs:
        txt=txt.replace(old,new)
    ast.parse(txt);p.write_text(txt)

p=Path("docs/g1_announcement_times.md");txt=p.read_text()
assert "63 public exact-time batches / 93 exact-resolved" in txt
txt=txt.replace("63 public exact-time batches / 93 exact-resolved","64 public exact-time batches / 94 exact-resolved",1)
txt += """
### Batch 0079: Juniper Networks

InvestorsHub/ADVFN preserves the matching Marketwire release for Juniper Networks' preliminary first-quarter 2011 results with an explicit publication clock of 2011-04-19 16:12 EDT (20:12 UTC), 1,320 seconds after the frozen 15:50 EDT illicit trade. SEC Exhibit 99.1 independently corroborates issuer, release title/date, reporting period, and release content. This advances G1 from 93 exact / 81 reviewed exclusions to 94 exact / 80 reviewed exclusions. The separately scheduled 17:00 ET conference call, EDGAR acceptance, archive-capture, date-only, and inferred clocks are not used. Step 9 remains SOURCE_BLOCKED.
""";p.write_text(txt)

tp=Path("tests/test_g1_public_batch_0079.py")
ts='''import csv,json,hashlib
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
def rr(p):
    with p.open(newline="",encoding="utf-8") as h:return list(csv.DictReader(h))
def test_batch_0079():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0079_evidence.json").read_text())
    events={r["event_id"]:r for r in rr(ROOT/"data/processed/historical_events.csv")}
    resolved={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    exp={"HEJFE-D7FD00AF94DD8F41":("JNPR","2011-04-19T20:12:00Z",1320)}
    assert len(d["items"])==1
    for x in d["items"]:
        sym,utc,delta=exp[x["event_id"]];e=events[x["event_id"]]
        tr=datetime.fromisoformat(e["first_documented_illicit_trade_ts"]).replace(tzinfo=ZoneInfo("America/New_York"));rel=datetime.fromisoformat(x["public_announcement_ts"])
        assert e["historical_symbol"]==sym and tr<rel<=tr+timedelta(days=7) and int((rel-tr).total_seconds())==delta
        assert resolved[x["event_id"]]["public_announcement_ts"]==utc
        assert resolved[x["event_id"]]["resolution_status"]=="resolved_exact_public_timestamp"
        assert x["source_family"]=="preserved_wire_mirror" and x["source_grade"]=="A"
        assert x["timestamp_evidence_kind"]=="publisher_timestamp"
        assert x["corroboration_reference"].startswith("https://www.sec.gov/Archives/edgar/data/")
def test_batch_0079_preserves_prior():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0079_evidence.json").read_text())
    assert hashlib.sha256((ROOT/d["batch_path"]).read_bytes()).hexdigest()==d["batch_sha256"]
    by={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    for eid,stamp in d["previous_exact_timestamps"].items():assert by[eid]["public_announcement_ts"]==stamp
    ex=[r for r in by.values() if r["resolution_status"]=="excluded_fail_closed"];assert len(ex)==80
    assert all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in ex)
'''
ast.parse(ts);tp.write_text(ts)
assert rebuild.rebuild(ROOT,publish=False)["before"]["up_to_date"]

changed=set(subprocess.check_output(["git","diff","--name-only",BASE],text=True).splitlines());changed.update([str(batch),str(evidence_path),str(tp),SCRIPT])
permitted={WORKFLOW,SCRIPT,str(contract_path),str(exclusion_path),str(hints_path),str(acq),str(batch),str(evidence_path),str(tp),
"docs/g1_announcement_times.md","src/metadata_resolver.py","tests/test_metadata_resolver.py","tests/test_g1_source_research.py","tests/test_g1_acquisition_manifest.py","tests/test_real_data_release_sprint.py",
str(cp),str(cp.parent/"unresolved_gates.csv"),str(sd/"step_status.json"),"data/processed/research_receipt_bundle.json",
"data/processed/real_data_replay/real_data_replay_status.json"} | {str(x) for x in Path("tests").glob("test_g1_public_batch_*.py")} | {str(md/name) for name in rebuild.METADATA_RECEIPTS}
assert changed<=permitted,f"Unexpected {changed-permitted}"
allowp=Path("config/release_drift_allowlist.json");allow=load(allowp);reason="G1 batch 0079 Worker-4 JNPR timestamp-preserving Marketwire mirror; deterministic 94 exact / 80 reviewed exclusions with SEC corroboration and prior evidence preserved."
for name in sorted(changed):
    sec="intentional_release_modifications" if name in allow["intentional_release_modifications"] else "repository_additions"
    allow[sec][name]={"expected_sha256":sha(name),"reason":reason}
save(allowp,allow);changed.add(str(allowp));subprocess.run(["git","add","--",*sorted(changed)],check=True)
audit=Path("private_runtime/audit/g1-batch-0079");audit.mkdir(parents=True,exist_ok=True)
save(audit/"verification.json",{"base_main_sha":BASE,"source_head_sha":os.environ["GITHUB_SHA"],"exact":94,"reviewed_excluded":80,
"previous_exact_preserved":93,"new_events":items,"step9":"SOURCE_BLOCKED","evaluation_release_permitted":False,"deterministic_rebuild_matches":True})
print(json.dumps({"exact":94,"reviewed_excluded":80,"new_events":[x["event_id"] for x in items]},indent=2))
