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
BASE="844db2085fdcdbda4f3d788def181b3f506a67d6"
WORKFLOW=".github/workflows/g1-public-batch-0061-worker-1.yml"
SCRIPT="scripts/g1_batch_0061_generate.py"
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
assert len(events)==174 and len(old_exact)==79
exclusion_path=md/"g1_final_timing_exclusions.json"
exclusions=load(exclusion_path)
assert len(exclusions["exclusions"])==95

batch=Path("data/public/metadata/g1_announcement_times_batch_0061.csv")
evidence_path=Path("data/public/metadata/g1_public_batch_0061_evidence.json")
assert not batch.exists() and not evidence_path.exists()

specs=[
{"event_id":"HEJFE-9B84208BA575EAC4","historical_symbol":"RH","expected_trade":"2015-03-26 15:41:00",
 "clock":"2015-03-26T13:04:00-07:00","publisher_timestamp_text":"March 26, 2015 1:04 PM PDT",
 "release_title":"RH Reports Record Fourth Quarter and Fiscal Year 2014 Financial Results",
 "source_reference":"https://ir.rh.com/news-events/detail/180/rh-reports-record-fourth-quarter-and-fiscal-year-2014-financial-results",
 "corroboration_reference":"https://www.sec.gov/Archives/edgar/data/1528849/000119312515106973/d896261dex991.htm",
 "corroboration_basis":"RH's issuer investor-relations release page explicitly displays March 26, 2015 1:04 PM PDT for the target Business Wire earnings release; SEC Exhibit 99.1 independently matches issuer, exact release title, date, and fourth-quarter/fiscal-2014 results. No conference-call, EDGAR acceptance, archive-capture, scheduled-release, date-only, or inferred time is used.",
 "expected_delta":1380}
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
      "timestamp_kind":"first_public_release","timestamp_evidence_kind":"publisher_timestamp","source_family":"official_newswire_archive",
      "source_grade":"A","publisher_timestamp_text":spec["publisher_timestamp_text"],"release_title":spec["release_title"],
      "source_reference":spec["source_reference"],"corroboration_reference":spec["corroboration_reference"],
      "corroboration_basis":spec["corroboration_basis"],"reviewed_on":"2026-09-30","information_asymmetry_seconds":delta}
    items.append(item)
    trial["validation_probes"].append(dict(item,probe_id=f"{spec['historical_symbol']}-batch0061",historical_event_match=True,
      exact_clock_observed=True,exact_public_release_ts=release.isoformat(),evidence_eligible=True))
research.validate_research_map(trial,exclusions)

fields=["event_id","historical_symbol","event_date","public_announcement_ts","timestamp_kind","source_grade","source_reference"]
s=io.StringIO(newline="");w=csv.DictWriter(s,fieldnames=fields,lineterminator="\n");w.writeheader()
for x in items:w.writerow({k:x[k] for k in fields})
batch.write_text(s.getvalue(),encoding="utf-8")
save(evidence_path,{"schema_version":"1","research_use_only":True,"base_main_sha":BASE,"batch_path":str(batch),"batch_sha256":sha(batch),
"items":items,"previous_exact_count":79,"expected_exact_count_after_batch":80,"expected_excluded_after_batch":94,
"previous_exact_timestamps":{k:r["public_announcement_ts"] for k,r in old_exact.items()},
"evidence_method":"One direct issuer investor-relations publication clock for RH with independent SEC Exhibit 99.1 corroboration. CI verifies chronology, event identity and deterministic receipts; conference-call, EDGAR acceptance, archive-capture, scheduled-release, date-only and inferred times are not used.",
"prohibited_substitutes":["edgar_acceptance_time","scheduled_call_time","archive_capture_time","inferred_clock","date_only"]})

ids={x["event_id"] for x in items}
exclusions["exclusions"]=[r for r in exclusions["exclusions"] if r["event_id"] not in ids]
exclusions["base_main_sha"]=BASE
exclusions["g1_state"].update(exact_resolved=80,reviewed_excluded=94,raw_exact_time_evidence_gaps=94,exact_timing_analysis_eligible=80)
save(exclusion_path,exclusions)

contract_path=Path("config/metadata_sources.public_progress.json");contract=load(contract_path)
contract["sources"].insert(0,{"source_id":"public-issuer-rh-batch-0061","record_kind":"announcement_timestamp",
"source_family":"official_newswire_archive","path":str(batch),"enabled":True,"authorized":True,"data_classification":"public_official_data",
"delimiter":",","encoding":"utf-8","timezone":"America/New_York","column_map":{k:k for k in fields},
"license_reference":"Public issuer investor-relations publication metadata for RH with independent SEC Exhibit 99.1 corroboration. No licensed vendor data used.",
"notes":"RH 2015-03-26 13:04 PDT. Conference-call, EDGAR acceptance, archive-capture, scheduled-release, date-only and inferred times are not used."})
contract["reviewed_announcement_exclusions"].update(expected_count=94,expected_sha256=sha(exclusion_path))
contract["purpose"]="Cumulative public point-in-time metadata: G1 has 80 exact release timestamps and 94 reviewed fail-closed exclusions; exact-timing and all independent non-synthetic release locks remain fail-closed."
save(contract_path,contract)

hints["base_main_sha"]=BASE
hints["current_g1_state"].update(public_exact_batch_count=54,exact_resolved_event_records=80,reviewed_excluded_event_records=94,
 note="The repository is at batch_0061; cumulative exact event records are 80 because some public batches resolve more than one historical event.")
for item in items:
    hints["validation_probes"].append(dict(item,probe_id=f"{item['historical_symbol']}-batch0061",historical_event_match=True,
      exact_clock_observed=True,exact_public_release_ts=item["public_announcement_ts"],evidence_eligible=False,
      disposition="RESOLVED_IN_BATCH_0061",reason="Promoted through direct issuer investor-relations publication timestamp evidence with SEC corroboration."))
save(hints_path,hints)

assert rebuild.rebuild(ROOT,publish=True)["after"]["up_to_date"]
fresh=rows(md/"announcement_resolutions.csv");by={r["event_id"]:r for r in fresh};assert len(by)==174
for eid,old in old_exact.items():assert by[eid]==old
expected={"HEJFE-9B84208BA575EAC4":"2015-03-26T20:04:00Z"}
for item in items:
    r=by[item["event_id"]];assert r["resolution_status"]=="resolved_exact_public_timestamp" and r["public_announcement_ts"]==expected[item["event_id"]]
excluded=[r for r in fresh if r["resolution_status"]=="excluded_fail_closed"]
assert len(excluded)==94 and all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in excluded)
ready=load(md/"metadata_readiness_summary.json");assert ready["announcement_exact_resolved"]==80 and ready["announcement_events_excluded"]==94
assert ready["ready_g1_exact_timing_analysis"] is False

acq=Path("data/public/metadata/g1_acquisition_manifest.json");acq.write_text(acquisition.render_manifest(acquisition.build_manifest()),encoding="utf-8")
sd=Path("data/processed/real_data_release_sprint");cp=Path("data/processed/coverage_plan_real/coverage_summary.json")
sprint.refresh_coverage(coverage_summary_path=cp,metadata_readiness_path=md/"metadata_readiness_summary.json",
 metadata_quality_path=md/"metadata_quality_summary.json",requirements_manifest_path=sd/"requirements_manifest.json",
 unresolved_gates_path=cp.parent/"unresolved_gates.csv")
status=sprint.build_status(requirements_manifest_path=sd/"requirements_manifest.json",coverage_summary_path=cp,
 metadata_readiness_path=md/"metadata_readiness_summary.json",metadata_quality_path=md/"metadata_quality_summary.json",outpath=sd/"step_status.json")
step9=next(x for x in status["steps"] if x["step"]==9);assert step9["status"]=="SOURCE_BLOCKED" and "80/174" in step9["evidence"] and "94" in step9["evidence"]

for fn in ["tests/test_g1_source_research.py","tests/test_g1_acquisition_manifest.py","tests/test_real_data_release_sprint.py",
"tests/test_g1_public_batch_0032.py","tests/test_g1_public_batch_0034.py","tests/test_g1_public_batch_0035.py","tests/test_g1_public_batch_0036.py","tests/test_g1_public_batch_0037.py","tests/test_g1_public_batch_0038.py","tests/test_g1_public_batch_0039.py","tests/test_g1_public_batch_0040.py","tests/test_g1_public_batch_0041.py","tests/test_g1_public_batch_0042.py","tests/test_g1_public_batch_0043.py","tests/test_g1_public_batch_0044.py","tests/test_g1_public_batch_0045.py","tests/test_g1_public_batch_0046.py","tests/test_g1_public_batch_0047.py","tests/test_g1_public_batch_0048.py","tests/test_g1_public_batch_0049.py","tests/test_g1_public_batch_0050.py","tests/test_g1_public_batch_0051.py","tests/test_g1_public_batch_0052.py","tests/test_g1_public_batch_0053.py"]:
    p=Path(fn);t=p.read_text()
    t=t.replace("== (79,95)","== (80,94)").replace("len(excluded)==95","len(excluded)==94").replace("len(excluded) == 95","len(excluded) == 94").replace("len(ex)==95","len(ex)==94")
    t=t.replace('"79/174" in step9["evidence"] and "95" in step9["evidence"]','"80/174" in step9["evidence"] and "94" in step9["evidence"]')
    t=t.replace('updated["missing_exact_announcement_timestamps"] == 95','updated["missing_exact_announcement_timestamps"] == 94')
    t=re.sub(r"== 79\b","== 80",t);t=re.sub(r"== 95\b","== 94",t)
    if fn.endswith("test_g1_source_research.py"):t=t.replace('state["public_exact_batch_count"] == 53','state["public_exact_batch_count"] == 54')
    ast.parse(t);p.write_text(t)

p=Path("docs/g1_announcement_times.md");t=p.read_text().replace("53 public exact-time batches / 79 exact-resolved","54 public exact-time batches / 80 exact-resolved")
t += """
### Batch 0061: RH

RH's issuer investor-relations archive explicitly records the Business Wire fourth-quarter and fiscal-2014 results release at 2015-03-26 13:04 PDT (20:04 UTC), 1,380 seconds after the frozen 2015-03-26 15:41 EDT trade. SEC Exhibit 99.1 independently corroborates issuer, exact title, date, and reported results. This advances G1 from 79 exact / 95 reviewed exclusions to 80 exact / 94 reviewed exclusions. Conference-call, scheduled-release, EDGAR acceptance, archive-capture, date-only, and inferred clocks remain prohibited substitutes. Step 9 remains SOURCE_BLOCKED.
""";p.write_text(t)

tp=Path("tests/test_g1_public_batch_0061.py")
ts='''import csv,json,hashlib
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
def rr(p):
    with p.open(newline="",encoding="utf-8") as h:return list(csv.DictReader(h))
def test_batch_0061():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0061_evidence.json").read_text())
    events={r["event_id"]:r for r in rr(ROOT/"data/processed/historical_events.csv")}
    resolved={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    exp={"HEJFE-9B84208BA575EAC4":("RH","2015-03-26T20:04:00Z",1380)}
    assert len(d["items"])==1
    for x in d["items"]:
        sym,utc,delta=exp[x["event_id"]];e=events[x["event_id"]]
        tr=datetime.fromisoformat(e["first_documented_illicit_trade_ts"]).replace(tzinfo=ZoneInfo("America/New_York"));rel=datetime.fromisoformat(x["public_announcement_ts"])
        assert e["historical_symbol"]==sym and tr<rel<=tr+timedelta(days=7) and int((rel-tr).total_seconds())==delta
        assert resolved[x["event_id"]]["public_announcement_ts"]==utc
        assert resolved[x["event_id"]]["resolution_status"]=="resolved_exact_public_timestamp"
        assert x["source_family"]=="official_newswire_archive" and x["source_grade"]=="A"
def test_batch_0061_preserves_prior():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0061_evidence.json").read_text())
    assert hashlib.sha256((ROOT/d["batch_path"]).read_bytes()).hexdigest()==d["batch_sha256"]
    by={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    for eid,ts in d["previous_exact_timestamps"].items():assert by[eid]["public_announcement_ts"]==ts
    ex=[r for r in by.values() if r["resolution_status"]=="excluded_fail_closed"];assert len(ex)==94
    assert all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in ex)
'''
ast.parse(ts);tp.write_text(ts)
assert rebuild.rebuild(ROOT,publish=False)["before"]["up_to_date"]

changed=set(subprocess.check_output(["git","diff","--name-only",BASE],text=True).splitlines());changed.update([str(batch),str(evidence_path),str(tp),SCRIPT])
permitted={WORKFLOW,SCRIPT,str(contract_path),str(exclusion_path),str(hints_path),str(acq),str(batch),str(evidence_path),str(tp),
"docs/g1_announcement_times.md","tests/test_g1_source_research.py","tests/test_g1_acquisition_manifest.py","tests/test_real_data_release_sprint.py",
"tests/test_g1_public_batch_0032.py","tests/test_g1_public_batch_0034.py","tests/test_g1_public_batch_0035.py","tests/test_g1_public_batch_0036.py","tests/test_g1_public_batch_0037.py","tests/test_g1_public_batch_0038.py","tests/test_g1_public_batch_0039.py","tests/test_g1_public_batch_0040.py","tests/test_g1_public_batch_0041.py","tests/test_g1_public_batch_0042.py","tests/test_g1_public_batch_0043.py","tests/test_g1_public_batch_0044.py","tests/test_g1_public_batch_0045.py","tests/test_g1_public_batch_0046.py","tests/test_g1_public_batch_0047.py","tests/test_g1_public_batch_0048.py","tests/test_g1_public_batch_0049.py","tests/test_g1_public_batch_0050.py","tests/test_g1_public_batch_0051.py","tests/test_g1_public_batch_0052.py","tests/test_g1_public_batch_0053.py",
str(cp),str(cp.parent/"unresolved_gates.csv"),str(sd/"step_status.json"),"data/processed/research_receipt_bundle.json",
"data/processed/real_data_replay/real_data_replay_status.json"} | {str(md/name) for name in rebuild.METADATA_RECEIPTS}
assert changed<=permitted,f"Unexpected {changed-permitted}"
allowp=Path("config/release_drift_allowlist.json");allow=load(allowp);reason="G1 batch 0061 issuer IR clock for RH; deterministic 80 exact / 94 reviewed exclusions with SEC corroboration and prior evidence preserved."
for name in sorted(changed):
    sec="intentional_release_modifications" if name in allow["intentional_release_modifications"] else "repository_additions"
    allow[sec][name]={"expected_sha256":sha(name),"reason":reason}
save(allowp,allow);changed.add(str(allowp));subprocess.run(["git","add","--",*sorted(changed)],check=True)
audit=Path("private_runtime/audit/g1-batch-0061");audit.mkdir(parents=True,exist_ok=True)
save(audit/"verification.json",{"base_main_sha":BASE,"source_head_sha":os.environ["GITHUB_SHA"],"exact":80,"reviewed_excluded":94,
"previous_exact_preserved":79,"new_events":items,"step9":"SOURCE_BLOCKED","evaluation_release_permitted":False,"deterministic_rebuild_matches":True})
print(json.dumps({"exact":80,"reviewed_excluded":94,"new_events":[x["event_id"] for x in items]},indent=2))