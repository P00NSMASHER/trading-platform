from __future__ import annotations
import ast,csv,hashlib,io,json,os,re,subprocess
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import g1_source_research as research
import g1_acquisition_manifest as acquisition
import research_receipt_rebuild as rebuild
import real_data_release_sprint as sprint

ROOT=Path.cwd()
BASE="3433103ea5b1f8111141aad2fc607206a390bedc"
WORKFLOW=".github/workflows/g1-public-batch-0039.yml"
SCRIPT="scripts/g1_batch_0039_generate.py"

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
assert len(events)==174 and len(old_exact)==49
exclusion_path=md/"g1_final_timing_exclusions.json"
exclusions=load(exclusion_path)
assert len(exclusions["exclusions"])==125

spec={
    "event_id":"HEJFE-3046057647A0FC5C",
    "historical_symbol":"BRKR",
    "expected_trade":"2015-05-06 15:30:00",
    "clock":"2015-05-06T16:01:00-04:00",
    "publisher_timestamp_text":"May 6, 2015 4:01 PM EDT",
    "release_title":"Bruker Reports First Quarter 2015 Financial Results",
    "source_reference":"https://www.streetinsider.com/Press+Releases/Bruker+Reports+First+Quarter+2015+Financial+Results/10529926.html",
    "corroboration_reference":"https://www.sec.gov/Archives/edgar/data/1109354/000110465915034867/a15-10964_1ex99d1.htm",
    "corroboration_basis":"StreetInsider preserves the original Business Wire release and displays May 6, 2015 4:01 PM EDT; SEC Exhibit 99.1 independently matches Bruker, May 6 2015, first-quarter 2015 results and $353.5 million revenue. The 4:45pm earnings call is not used.",
    "expected_delta":1860,
}
event=next(r for r in events if r["event_id"]==spec["event_id"])
assert event["historical_symbol"]==spec["historical_symbol"]
assert event["first_documented_illicit_trade_ts"]==spec["expected_trade"]
assert spec["event_id"] not in old_exact
assert sum(r["event_id"]==spec["event_id"] for r in exclusions["exclusions"])==1
trade=datetime.fromisoformat(event["first_documented_illicit_trade_ts"]).replace(tzinfo=ZoneInfo("America/New_York"))
release=datetime.fromisoformat(spec["clock"])
assert trade<release<=trade+timedelta(days=7)
delta=int((release-trade).total_seconds())
assert delta==spec["expected_delta"]
item={
    "event_id":spec["event_id"],"historical_symbol":spec["historical_symbol"],"event_date":trade.date().isoformat(),
    "first_documented_illicit_trade_ts":event["first_documented_illicit_trade_ts"],
    "public_announcement_ts":release.isoformat(),"timestamp_kind":"first_public_release",
    "timestamp_evidence_kind":"publisher_timestamp","source_family":"preserved_wire_mirror","source_grade":"B",
    "publisher_timestamp_text":spec["publisher_timestamp_text"],"release_title":spec["release_title"],
    "source_reference":spec["source_reference"],"corroboration_reference":spec["corroboration_reference"],
    "corroboration_basis":spec["corroboration_basis"],"reviewed_on":"2026-09-29",
    "information_asymmetry_seconds":delta,
}

hints_path=Path("data/public/metadata/g1_source_research_20260928.json")
hints=load(hints_path)
trial=json.loads(json.dumps(hints))
trial["validation_probes"].append(dict(item,probe_id="BRKR-batch0039",historical_event_match=True,
    exact_clock_observed=True,exact_public_release_ts=release.isoformat(),evidence_eligible=True))
research.validate_research_map(trial,exclusions)

batch=Path("data/public/metadata/g1_announcement_times_batch_0039.csv")
evidence_path=Path("data/public/metadata/g1_public_batch_0039_evidence.json")
assert not batch.exists() and not evidence_path.exists()
fields=["event_id","historical_symbol","event_date","public_announcement_ts","timestamp_kind","source_grade","source_reference"]
buf=io.StringIO(newline="")
w=csv.DictWriter(buf,fieldnames=fields,lineterminator="\n");w.writeheader();w.writerow({k:item[k] for k in fields})
batch.write_text(buf.getvalue(),encoding="utf-8")
save(evidence_path,{
    "schema_version":"1","research_use_only":True,"base_main_sha":BASE,
    "batch_path":str(batch),"batch_sha256":sha(batch),"items":[item],
    "previous_exact_count":49,"expected_exact_count_after_batch":50,"expected_excluded_after_batch":124,
    "previous_exact_timestamps":{k:r["public_announcement_ts"] for k,r in old_exact.items()},
    "evidence_method":"StreetInsider preserves the original Business Wire publication timestamp for Bruker at 4:01 PM EDT; SEC Exhibit 99.1 independently corroborates issuer, date, reporting period and financial content.",
    "prohibited_substitutes":["edgar_acceptance_time","scheduled_call_time","archive_capture_time","inferred_clock","date_only"],
})

exclusions["exclusions"]=[r for r in exclusions["exclusions"] if r["event_id"]!=spec["event_id"]]
exclusions["base_main_sha"]=BASE
exclusions["g1_state"].update(exact_resolved=50,reviewed_excluded=124,raw_exact_time_evidence_gaps=124,exact_timing_analysis_eligible=50)
save(exclusion_path,exclusions)

contract_path=Path("config/metadata_sources.public_progress.json")
contract=load(contract_path)
contract["sources"].insert(0,{
    "source_id":"public-businesswire-preserved-brkr-batch-0039",
    "record_kind":"announcement_timestamp","source_family":"official_newswire_archive",
    "path":str(batch),"enabled":True,"authorized":True,"data_classification":"public_official_data",
    "delimiter":",","encoding":"utf-8","timezone":"America/New_York",
    "column_map":{k:k for k in fields},
    "license_reference":"Public StreetInsider-preserved Business Wire publication metadata for Bruker with SEC Exhibit 99.1 corroboration. No licensed vendor data used.",
    "notes":"BRKR 2015-05-06 16:01 EDT. The 4:45pm earnings call and EDGAR acceptance timestamp are not used.",
})
contract["reviewed_announcement_exclusions"].update(expected_count=124,expected_sha256=sha(exclusion_path))
contract["purpose"]="Cumulative public point-in-time metadata: G1 has 50 exact release timestamps and 124 reviewed fail-closed exclusions; exact-timing and all independent non-synthetic release locks remain fail-closed."
save(contract_path,contract)

hints["base_main_sha"]=BASE
hints["current_g1_state"].update(public_exact_batch_count=39,exact_resolved_event_records=50,reviewed_excluded_event_records=124,
    note="The repository is at batch_0039; cumulative exact event records are 50 because some public batches resolve more than one historical event.")
hints["validation_probes"].append(dict(item,probe_id="BRKR-batch0039",historical_event_match=True,
    exact_clock_observed=True,exact_public_release_ts=item["public_announcement_ts"],evidence_eligible=False,
    disposition="RESOLVED_IN_BATCH_0039",reason="Promoted through reviewed original Business Wire evidence preserved by StreetInsider with SEC corroboration."))
save(hints_path,hints)

assert rebuild.rebuild(ROOT,publish=True)["after"]["up_to_date"]
fresh=rows(md/"announcement_resolutions.csv")
by={r["event_id"]:r for r in fresh}
assert len(by)==174
for eid,old in old_exact.items(): assert by[eid]==old
row=by[spec["event_id"]]
assert row["resolution_status"]=="resolved_exact_public_timestamp"
assert row["public_announcement_ts"]=="2015-05-06T20:01:00Z"
assert int(row["information_asymmetry_seconds"])==1860
excluded=[r for r in fresh if r["resolution_status"]=="excluded_fail_closed"]
assert len(excluded)==124
assert all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in excluded)

ready=load(md/"metadata_readiness_summary.json")
assert ready["announcement_exact_resolved"]==50
assert ready["announcement_events_excluded"]==124
assert ready["ready_g1_exact_timing_analysis"] is False
assert ready["ready_for_non_synthetic_model_evaluation_metadata"] is False

acq=Path("data/public/metadata/g1_acquisition_manifest.json")
acq.write_text(acquisition.render_manifest(acquisition.build_manifest()),encoding="utf-8")
sd=Path("data/processed/real_data_release_sprint")
cp=Path("data/processed/coverage_plan_real/coverage_summary.json")
sprint.refresh_coverage(coverage_summary_path=cp,metadata_readiness_path=md/"metadata_readiness_summary.json",
    metadata_quality_path=md/"metadata_quality_summary.json",requirements_manifest_path=sd/"requirements_manifest.json",
    unresolved_gates_path=cp.parent/"unresolved_gates.csv")
status=sprint.build_status(requirements_manifest_path=sd/"requirements_manifest.json",coverage_summary_path=cp,
    metadata_readiness_path=md/"metadata_readiness_summary.json",metadata_quality_path=md/"metadata_quality_summary.json",
    outpath=sd/"step_status.json")
step9=next(x for x in status["steps"] if x["step"]==9)
assert step9["status"]=="SOURCE_BLOCKED"
assert "50/174" in step9["evidence"] and "124" in step9["evidence"]
assert not status["all_12_genuinely_complete"]

regressions=[
"tests/test_g1_source_research.py","tests/test_g1_acquisition_manifest.py","tests/test_real_data_release_sprint.py",
"tests/test_g1_public_batch_0032.py","tests/test_g1_public_batch_0034.py","tests/test_g1_public_batch_0035.py",
"tests/test_g1_public_batch_0036.py","tests/test_g1_public_batch_0037.py","tests/test_g1_public_batch_0038.py"]
for fn in regressions:
    p=Path(fn);t=p.read_text()
    t=t.replace("== (49,125)","== (50,124)")
    t=t.replace("len(excluded)==125","len(excluded)==124").replace("len(excluded) == 125","len(excluded) == 124").replace("len(ex)==125","len(ex)==124")
    t=t.replace('"49/174" in step9["evidence"] and "125" in step9["evidence"]','"50/174" in step9["evidence"] and "124" in step9["evidence"]')
    t=t.replace('updated["missing_exact_announcement_timestamps"] == 125','updated["missing_exact_announcement_timestamps"] == 124')
    t=re.sub(r"== 49\b","== 50",t)
    t=re.sub(r"== 125\b","== 124",t)
    if fn.endswith("test_g1_source_research.py"):
        t=t.replace('state["public_exact_batch_count"] == 38','state["public_exact_batch_count"] == 39')
    ast.parse(t);p.write_text(t)

doc=Path("docs/g1_announcement_times.md")
dt=doc.read_text()
dt=dt.replace("38 public exact-time batches / 49 exact-resolved","39 public exact-time batches / 50 exact-resolved")
dt += """
### Batch 0039: Bruker preserved Business Wire clock

StreetInsider preserves the original Business Wire release for Bruker's first-quarter 2015 results at 2015-05-06 16:01 EDT (20:01 UTC), independently corroborated by SEC Exhibit 99.1. The release is 1,860 seconds after the frozen first trade. This advances G1 from 49 exact / 125 reviewed exclusions to 50 exact / 124 reviewed exclusions. The 4:45pm earnings call, EDGAR acceptance timestamps and inferred clocks remain prohibited substitutes. Step 9 remains SOURCE_BLOCKED.
"""
doc.write_text(dt)

tp=Path("tests/test_g1_public_batch_0039.py")
ts='''import csv,json,hashlib
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
def rr(p):
    with p.open(newline="",encoding="utf-8") as h:return list(csv.DictReader(h))
def test_batch_0039_bruker_clock():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0039_evidence.json").read_text())
    assert len(d["items"])==1
    x=d["items"][0]
    events={r["event_id"]:r for r in rr(ROOT/"data/processed/historical_events.csv")}
    resolved={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    e=events[x["event_id"]]
    tr=datetime.fromisoformat(e["first_documented_illicit_trade_ts"]).replace(tzinfo=ZoneInfo("America/New_York"))
    rel=datetime.fromisoformat(x["public_announcement_ts"])
    assert x["event_id"]=="HEJFE-3046057647A0FC5C"
    assert e["historical_symbol"]=="BRKR"
    assert tr<rel<=tr+timedelta(days=7)
    assert int((rel-tr).total_seconds())==1860
    assert resolved[x["event_id"]]["public_announcement_ts"]=="2015-05-06T20:01:00Z"
    assert resolved[x["event_id"]]["resolution_status"]=="resolved_exact_public_timestamp"
def test_batch_0039_preserves_prior_and_remainder():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0039_evidence.json").read_text())
    assert hashlib.sha256((ROOT/d["batch_path"]).read_bytes()).hexdigest()==d["batch_sha256"]
    by={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    for eid,ts in d["previous_exact_timestamps"].items(): assert by[eid]["public_announcement_ts"]==ts
    ex=[r for r in by.values() if r["resolution_status"]=="excluded_fail_closed"]
    assert len(ex)==124
    assert all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in ex)
'''
ast.parse(ts);tp.write_text(ts)
assert rebuild.rebuild(ROOT,publish=False)["before"]["up_to_date"]

changed=set(subprocess.check_output(["git","diff","--name-only",BASE],text=True).splitlines())
changed.update([str(batch),str(evidence_path),str(tp),SCRIPT])
permitted={WORKFLOW,SCRIPT,str(contract_path),str(exclusion_path),str(hints_path),str(acq),str(batch),str(evidence_path),str(tp),
"docs/g1_announcement_times.md","tests/test_g1_source_research.py","tests/test_g1_acquisition_manifest.py","tests/test_real_data_release_sprint.py",
"tests/test_g1_public_batch_0032.py","tests/test_g1_public_batch_0034.py","tests/test_g1_public_batch_0035.py","tests/test_g1_public_batch_0036.py",
"tests/test_g1_public_batch_0037.py","tests/test_g1_public_batch_0038.py",str(cp),str(cp.parent/"unresolved_gates.csv"),
str(sd/"step_status.json"),"data/processed/research_receipt_bundle.json","data/processed/real_data_replay/real_data_replay_status.json"} | {str(md/name) for name in rebuild.METADATA_RECEIPTS}
assert changed<=permitted,f"Unexpected changes: {changed-permitted}"

allowp=Path("config/release_drift_allowlist.json")
allow=load(allowp)
reason="G1 batch 0039: Bruker original Business Wire timestamp preserved by StreetInsider; deterministic 50 exact / 124 reviewed exclusions with SEC corroboration."
for name in sorted(changed):
    section="intentional_release_modifications" if name in allow["intentional_release_modifications"] else "repository_additions"
    allow[section][name]={"expected_sha256":sha(name),"reason":reason}
save(allowp,allow);changed.add(str(allowp))
subprocess.run(["git","add","--",*sorted(changed)],check=True)

audit=Path("private_runtime/audit/g1-batch-0039");audit.mkdir(parents=True,exist_ok=True)
save(audit/"verification.json",{"base_main_sha":BASE,"source_head_sha":os.environ["GITHUB_SHA"],"exact":50,"reviewed_excluded":124,
"previous_exact_preserved":49,"new_events":[item],"step9":"SOURCE_BLOCKED","evaluation_release_permitted":False,"deterministic_rebuild_matches":True})
print(json.dumps({"exact":50,"reviewed_excluded":124,"new_events":[item["event_id"]]},indent=2))

# trigger batch 0039 workflow
