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
BASE="72506630f8822499b58eb7f3d8300c6dd2e0dd85"
WORKFLOW=".github/workflows/g1-public-batch-0071-worker-1.yml"
SCRIPT="scripts/g1_batch_0071_generate.py"
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
assert len(events)==174 and len(old_exact)==89
exclusion_path=md/"g1_final_timing_exclusions.json"
exclusions=load(exclusion_path)
assert len(exclusions["exclusions"])==85

batch=Path("data/public/metadata/g1_announcement_times_batch_0071.csv")
evidence_path=Path("data/public/metadata/g1_public_batch_0071_evidence.json")
assert not batch.exists() and not evidence_path.exists()

specs=[{
 "event_id":"HEJFE-66BA40A20548B7E3",
 "historical_symbol":"LRCX",
 "expected_trade":"2013-04-24 13:43:00",
 "clock":"2013-04-24T16:05:00-04:00",
 "publisher_timestamp_text":"GlobeNewswire historical archive: April 24, 2013 16:05 ET; release body identifies Marketwired",
 "release_title":"Lam Research Corporation Reports Financial Results for the Quarter Ended March 31, 2013",
 "source_reference":"https://www.globenewswire.com/news-release/2013/04/24/941552/0/en/lam-research-corporation-reports-financial-results-for-the-quarter-ended-march-31-2013.html",
 "corroboration_reference":"https://www.sec.gov/Archives/edgar/data/707549/000119312513170392/d526506dex991.htm",
 "corroboration_basis":"GlobeNewswire preserves the exact Marketwired release title and an explicit April 24, 2013 16:05 ET publication clock. SEC Exhibit 99.1 independently matches Lam Research Corporation, the April 24 2013 release title, reporting period and release content. The Lam newsroom CMS ITEMDATE, SEC acceptance time and scheduled 2:00 p.m. Pacific conference call are not used.",
 "timestamp_evidence_kind":"publisher_timestamp",
 "source_family":"official_newswire_archive",
 "source_grade":"A",
 "expected_delta":8520
}]
items=[]
hints_path=Path("data/public/metadata/g1_source_research_20260928.json")
hints=load(hints_path);trial=copy.deepcopy(hints)
trial["validation_probes"]=[r for r in trial.get("validation_probes",[]) if r.get("event_id")!="HEJFE-66BA40A20548B7E3"]
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
      "corroboration_basis":spec["corroboration_basis"],"reviewed_on":"2026-10-01","information_asymmetry_seconds":delta}
    items.append(item)
    trial["validation_probes"].append(dict(item,probe_id="LRCX-batch0071",historical_event_match=True,
      exact_clock_observed=True,exact_public_release_ts=release.isoformat(),evidence_eligible=True))
research.validate_research_map(trial,exclusions)

fields=["event_id","historical_symbol","event_date","public_announcement_ts","timestamp_kind","source_grade","source_reference"]
s=io.StringIO(newline="");w=csv.DictWriter(s,fieldnames=fields,lineterminator="\n");w.writeheader()
for x in items:w.writerow({k:x[k] for k in fields})
batch.write_text(s.getvalue(),encoding="utf-8")
save(evidence_path,{"schema_version":"1","research_use_only":True,"base_main_sha":BASE,"batch_path":str(batch),"batch_sha256":sha(batch),
"items":items,"previous_exact_count":89,"expected_exact_count_after_batch":90,"expected_excluded_after_batch":84,
"previous_exact_timestamps":{k:r["public_announcement_ts"] for k,r in old_exact.items()},
"evidence_method":"GlobeNewswire historical archive preserves Lam Research\'s Marketwired release with an explicit first-public clock of 16:05 ET, independently corroborated by matching SEC Exhibit 99.1. The Lam newsroom CMS ITEMDATE, SEC acceptance, scheduled conference-call, archive-capture, date-only and inferred times are not used.",
"prohibited_substitutes":["edgar_acceptance_time","scheduled_call_time","archive_capture_time","inferred_clock","date_only"]})

ids={x["event_id"] for x in items}
exclusions["exclusions"]=[r for r in exclusions["exclusions"] if r["event_id"] not in ids]
exclusions["base_main_sha"]=BASE
exclusions["g1_state"].update(exact_resolved=90,reviewed_excluded=84,raw_exact_time_evidence_gaps=84,exact_timing_analysis_eligible=90)
save(exclusion_path,exclusions)

contract_path=Path("config/metadata_sources.public_progress.json");contract=load(contract_path)
contract["sources"].insert(0,{"source_id":"public-worker1-lrcx-batch-0071","record_kind":"announcement_timestamp",
"source_family":"official_newswire_archive","path":str(batch),"enabled":True,"authorized":True,"data_classification":"public_official_data",
"delimiter":",","encoding":"utf-8","timezone":"America/New_York","column_map":{k:k for k in fields},
"license_reference":"Public GlobeNewswire historical archive preserving the Marketwired publication clock, independently corroborated by SEC Exhibit 99.1. No licensed vendor data used.",
"notes":"LRCX 2013-04-24 16:05 EDT. Lam CMS ITEMDATE, conference-call, EDGAR acceptance, archive-capture, scheduled-release, date-only and inferred times are not used."})
contract["reviewed_announcement_exclusions"].update(expected_count=84,expected_sha256=sha(exclusion_path))
contract["purpose"]="Cumulative public point-in-time metadata: G1 has 90 exact release timestamps and 84 reviewed fail-closed exclusions; exact-timing and all independent non-synthetic release locks remain fail-closed."
save(contract_path,contract)

hints["priority_events"]=[r for r in hints.get("priority_events",[]) if r.get("event_id") not in ids]
hints["validation_probes"]=[r for r in hints.get("validation_probes",[]) if r.get("event_id") not in ids]
hints["base_main_sha"]=BASE
hints["current_g1_state"].update(public_exact_batch_count=60,exact_resolved_event_records=90,reviewed_excluded_event_records=84,
 note="The latest integrated recovery is batch_0071; cumulative public exact-time batches are 60 and cumulative exact event records are 90 because some public batches resolve more than one historical event.")
for item in items:
    hints["validation_probes"].append(dict(item,probe_id="LRCX-batch0071",historical_event_match=True,
      exact_clock_observed=True,exact_public_release_ts=item["public_announcement_ts"],evidence_eligible=False,
      disposition="RESOLVED_IN_BATCH_0071",reason="Promoted through the timestamp-preserving GlobeNewswire historical archive for the Marketwired release, with independent SEC Exhibit 99.1 corroboration."))
save(hints_path,hints)

assert rebuild.rebuild(ROOT,publish=True)["after"]["up_to_date"]
fresh=rows(md/"announcement_resolutions.csv");by={r["event_id"]:r for r in fresh};assert len(by)==174
for eid,old in old_exact.items():assert by[eid]==old
expected={"HEJFE-66BA40A20548B7E3":"2013-04-24T20:05:00Z"}
for item in items:
    r=by[item["event_id"]];assert r["resolution_status"]=="resolved_exact_public_timestamp" and r["public_announcement_ts"]==expected[item["event_id"]]
excluded=[r for r in fresh if r["resolution_status"]=="excluded_fail_closed"]
assert len(excluded)==84 and all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in excluded)
ready=load(md/"metadata_readiness_summary.json");assert ready["announcement_exact_resolved"]==90 and ready["announcement_events_excluded"]==84
assert ready["ready_g1_exact_timing_analysis"] is False

acq=Path("data/public/metadata/g1_acquisition_manifest.json");acq.write_text(acquisition.render_manifest(acquisition.build_manifest()),encoding="utf-8")
sd=Path("data/processed/real_data_release_sprint");cp=Path("data/processed/coverage_plan_real/coverage_summary.json")
sprint.refresh_coverage(coverage_summary_path=cp,metadata_readiness_path=md/"metadata_readiness_summary.json",
 metadata_quality_path=md/"metadata_quality_summary.json",requirements_manifest_path=sd/"requirements_manifest.json",
 unresolved_gates_path=cp.parent/"unresolved_gates.csv")
status=sprint.build_status(requirements_manifest_path=sd/"requirements_manifest.json",coverage_summary_path=cp,
 metadata_readiness_path=md/"metadata_readiness_summary.json",metadata_quality_path=md/"metadata_quality_summary.json",outpath=sd/"step_status.json")
step9=next(x for x in status["steps"] if x["step"]==9);assert step9["status"]=="SOURCE_BLOCKED" and "90/174" in step9["evidence"] and "84" in step9["evidence"]

test_files=[
"tests/test_g1_source_research.py","tests/test_g1_acquisition_manifest.py","tests/test_real_data_release_sprint.py",
*sorted(str(x) for x in Path("tests").glob("test_g1_public_batch_*.py"))
]
for fn in test_files:
    p=Path(fn);txt=p.read_text()
    if fn.endswith("test_g1_source_research.py"):
        pairs=[
          ('report["exact_resolved_event_records"] == 89','report["exact_resolved_event_records"] == 90'),
          ('report["reviewed_excluded_event_records"] == 85','report["reviewed_excluded_event_records"] == 84'),
          ('state["public_exact_batch_count"] == 59','state["public_exact_batch_count"] == 60'),
          ('state["exact_resolved_event_records"] == 89','state["exact_resolved_event_records"] == 90'),
        ]
    elif fn.endswith("test_g1_acquisition_manifest.py"):
        pairs=[
          ('manifest["state"]["exact_resolved"] == 89','manifest["state"]["exact_resolved"] == 90'),
          ('manifest["state"]["acquisition_needed"] == 85','manifest["state"]["acquisition_needed"] == 84'),
          ('len(manifest["work_queue"]) == 85','len(manifest["work_queue"]) == 84'),
          ('len({row["dedupe_key"] for row in manifest["work_queue"]}) == 85','len({row["dedupe_key"] for row in manifest["work_queue"]}) == 84'),
          ('len(resolved) == 89','len(resolved) == 90'),
          ('len(unresolved) == 85','len(unresolved) == 84'),
        ]
    elif fn.endswith("test_real_data_release_sprint.py"):
        pairs=[('updated["missing_exact_announcement_timestamps"] == 85','updated["missing_exact_announcement_timestamps"] == 84')]
    else:
        pairs=[
          ('(readiness["announcement_exact_resolved"],readiness["announcement_events_excluded"]) == (89,85)','(readiness["announcement_exact_resolved"],readiness["announcement_events_excluded"]) == (90,84)'),
          ('(readiness["announcement_exact_resolved"], readiness["announcement_events_excluded"]) == (89, 85)','(readiness["announcement_exact_resolved"], readiness["announcement_events_excluded"]) == (90, 84)'),
          ('"89/174" in step9["evidence"] and "85" in step9["evidence"]','"90/174" in step9["evidence"] and "84" in step9["evidence"]'),
          ('len(excluded)==85','len(excluded)==84'),
          ('len(excluded) == 85','len(excluded) == 84'),
          ('len(ex)==85','len(ex)==84'),
          ('len(ex) == 85','len(ex) == 84'),
        ]
    for old,new in pairs:
        txt=txt.replace(old,new)
    ast.parse(txt);p.write_text(txt)

p=Path("docs/g1_announcement_times.md");txt=p.read_text()
assert "59 public exact-time batches / 89 exact-resolved" in txt
txt=txt.replace("59 public exact-time batches / 89 exact-resolved","60 public exact-time batches / 90 exact-resolved",1)
txt += """
### Batch 0071: Lam Research

GlobeNewswire's historical archive preserves the Marketwired release for Lam Research's March 2013 quarter results with an explicit publication clock of 2013-04-24 16:05 EDT (20:05 UTC), 8,520 seconds after the frozen 13:43 EDT illicit trade. SEC Exhibit 99.1 independently corroborates issuer, release title/date, reporting period, and release content. This advances G1 from 89 exact / 85 reviewed exclusions to 90 exact / 84 reviewed exclusions. The Lam newsroom CMS ITEMDATE, scheduled conference call, EDGAR acceptance, archive-capture, date-only, and inferred clocks are not used. Step 9 remains SOURCE_BLOCKED.
""";p.write_text(txt)

tp=Path("tests/test_g1_public_batch_0071.py")
ts='''import csv,json,hashlib
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
def rr(p):
    with p.open(newline="",encoding="utf-8") as h:return list(csv.DictReader(h))
def test_batch_0071():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0071_evidence.json").read_text())
    events={r["event_id"]:r for r in rr(ROOT/"data/processed/historical_events.csv")}
    resolved={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    exp={"HEJFE-66BA40A20548B7E3":("LRCX","2013-04-24T20:05:00Z",8520)}
    assert len(d["items"])==1
    for x in d["items"]:
        sym,utc,delta=exp[x["event_id"]];e=events[x["event_id"]]
        tr=datetime.fromisoformat(e["first_documented_illicit_trade_ts"]).replace(tzinfo=ZoneInfo("America/New_York"));rel=datetime.fromisoformat(x["public_announcement_ts"])
        assert e["historical_symbol"]==sym and tr<rel<=tr+timedelta(days=7) and int((rel-tr).total_seconds())==delta
        assert resolved[x["event_id"]]["public_announcement_ts"]==utc
        assert resolved[x["event_id"]]["resolution_status"]=="resolved_exact_public_timestamp"
        assert x["source_family"]=="official_newswire_archive" and x["source_grade"]=="A"
        assert x["timestamp_evidence_kind"]=="publisher_timestamp"
        assert x["source_reference"].startswith("https://www.globenewswire.com/news-release/2013/04/24/")
        assert x["corroboration_reference"].startswith("https://www.sec.gov/Archives/edgar/data/")
def test_batch_0071_preserves_prior():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0071_evidence.json").read_text())
    assert hashlib.sha256((ROOT/d["batch_path"]).read_bytes()).hexdigest()==d["batch_sha256"]
    by={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    for eid,stamp in d["previous_exact_timestamps"].items():assert by[eid]["public_announcement_ts"]==stamp
    ex=[r for r in by.values() if r["resolution_status"]=="excluded_fail_closed"];assert len(ex)==84
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
allowp=Path("config/release_drift_allowlist.json");allow=load(allowp);reason="G1 batch 0071 Worker-1 LRCX GlobeNewswire/Marketwired exact public clock; deterministic 90 exact / 84 reviewed exclusions with SEC corroboration and prior evidence preserved."
for name in sorted(changed):
    sec="intentional_release_modifications" if name in allow["intentional_release_modifications"] else "repository_additions"
    allow[sec][name]={"expected_sha256":sha(name),"reason":reason}
save(allowp,allow);changed.add(str(allowp));subprocess.run(["git","add","--",*sorted(changed)],check=True)
audit=Path("private_runtime/audit/g1-batch-0071");audit.mkdir(parents=True,exist_ok=True)
save(audit/"verification.json",{"base_main_sha":BASE,"source_head_sha":os.environ["GITHUB_SHA"],"exact":90,"reviewed_excluded":84,
"previous_exact_preserved":89,"new_events":items,"step9":"SOURCE_BLOCKED","evaluation_release_permitted":False,"deterministic_rebuild_matches":True})
print(json.dumps({"exact":90,"reviewed_excluded":84,"new_events":[x["event_id"] for x in items]},indent=2))
