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
BASE="55eb6e4c600d2e21bb4a26b616feb6a3ec9e6d00"
WORKFLOW=".github/workflows/g1-public-batch-0119-worker-4.yml"
SCRIPT="scripts/g1_batch_0119_generate.py"
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
assert len(events)==174 and len(old_exact)==165
exclusion_path=md/"g1_final_timing_exclusions.json"
exclusions=load(exclusion_path)
assert len(exclusions["exclusions"])==9

batch=Path("data/public/metadata/g1_announcement_times_batch_0119.csv")
evidence_path=Path("data/public/metadata/g1_public_batch_0119_evidence.json")
assert not batch.exists() and not evidence_path.exists()

specs=[
  {
    "event_id": "HEJFE-CCC7747CFBDE893E",
    "historical_symbol": "PNRA",
    "expected_trade": "2013-04-23 14:25:00",
    "clock": "2013-04-23T16:00:00-04:00",
    "explicit_release_clock_text": "GX 8002 row 1657 explicitly records Press Release / Distribution Time 2013-04-23 16:00 Eastern",
    "release_title": "Panera Bread Company Reports Q1 2013 diluted EPS of $1.64, up 17%",
    "source_reference": "https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf",
    "corroboration_reference": "https://www.sec.gov/Archives/edgar/data/724606/000072460613000016/a20130326ex991pressrelease.htm",
    "corroboration_basis": "GX 8002 row 1657 is the unique PNRA 2013-04-23 earnings row and explicitly records the public-distribution clock. Official SEC Exhibit 99.1 independently corroborates exact ticker/date/headline/content; the broader canonical first documented illicit trade precedes the court row's Earliest Order Time, which is a mapping-method difference rather than release-identity ambiguity.",
    "timestamp_evidence_kind": "explicit_release_clock",
    "source_family": "federal_court_public_distribution_record",
    "source_grade": "A",
    "public_distribution_explicit": True,
    "expected_delta": 5700,
    "court_docket_reference": "https://www.courtlistener.com/docket/4324653/united-states-v-korchevsky/",
    "gx8002_row_id": "1657",
    "wire_source_code": "MW",
    "corroborating_release_member_path": "2013/QTR2/76695_20130423_1.txt"
  }
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
      "source_grade":spec["source_grade"],"explicit_release_clock_text":spec["explicit_release_clock_text"],"release_title":spec["release_title"],
      "source_reference":spec["source_reference"],"corroboration_reference":spec["corroboration_reference"],
      "corroboration_basis":spec["corroboration_basis"],"public_distribution_explicit":spec["public_distribution_explicit"],
      "court_docket_reference":spec["court_docket_reference"],"gx8002_row_id":spec["gx8002_row_id"],
      "wire_source_code":spec["wire_source_code"],"corroborating_release_member_path":spec["corroborating_release_member_path"],
      "reviewed_on":"2026-10-05","information_asymmetry_seconds":delta}
    items.append(item)
    trial["validation_probes"].append(dict(item,probe_id=f'{spec["historical_symbol"]}-batch0119',historical_event_match=True,
      exact_clock_observed=True,exact_public_release_ts=release.isoformat(),evidence_eligible=True))
research.validate_research_map(trial,exclusions)

fields=["event_id","historical_symbol","event_date","public_announcement_ts","timestamp_kind","source_grade","source_reference"]
s=io.StringIO(newline="");w=csv.DictWriter(s,fieldnames=fields,lineterminator="\n");w.writeheader()
for x in items:w.writerow({k:x[k] for k in fields})
batch.write_text(s.getvalue(),encoding="utf-8")
save(evidence_path,{"schema_version":"1","research_use_only":True,"base_main_sha":BASE,"batch_path":str(batch),"batch_sha256":sha(batch),
"items":items,"previous_exact_count":165,"expected_exact_count_after_batch":166,"expected_excluded_after_batch":8,
"previous_exact_timestamps":{k:r["public_announcement_ts"] for k,r in old_exact.items()},
"court_artifact":{
  "workflow_run_id": 37268374589,
  "artifact_id": 11326693734,
  "artifact_digest_sha256": "254e78dcb6218e3cd31cc9bf50a6ec639c966a037957629912af181432a6990e",
  "mapping_head_sha": "2592192e4fd38b14a021d36de7319db332379e38"
},
"evidence_method":"Filed federal-court GX 8002 explicitly records the press-release/public-distribution date and clock. Exact target identity/date is corroborated by PR #355's pinned public press-release archive mapping and official SEC Exhibit 99.x where available. Eastern offsets follow America/New_York date rules; BW/MW provider codes are not treated as timezones. CI verifies chronology, ownership, unresolved state and deterministic receipts. EDGAR acceptance, call/webcast, schedule, approximation, date-only, capture, neighboring-release and inferred clocks are not used.",
"prohibited_substitutes":["edgar_acceptance_time","scheduled_call_time","webcast_time","archive_capture_time","inferred_clock","date_only","neighboring_release"]})
evidence_snapshot=evidence_path.read_bytes()

ids={x["event_id"] for x in items}
exclusions["exclusions"]=[r for r in exclusions["exclusions"] if r["event_id"] not in ids]
exclusions["base_main_sha"]=BASE
exclusions["g1_state"].update(exact_resolved=166,reviewed_excluded=8,raw_exact_time_evidence_gaps=8,exact_timing_analysis_eligible=166)
save(exclusion_path,exclusions)

contract_path=Path("config/metadata_sources.public_progress.json");contract=load(contract_path)
contract["sources"].insert(0,{"source_id":"public-worker3-federal-court-gx8002-batch-0119","record_kind":"announcement_timestamp",
"source_family":"federal_court_public_distribution_record","path":str(batch),"enabled":True,"authorized":True,"data_classification":"public_official_data",
"delimiter":",","encoding":"utf-8","timezone":"America/New_York","column_map":{k:k for k in fields},
"license_reference":"Filed E.D.N.Y. GX 8002 Document 367-2 explicit press-release/public-distribution clocks, with exact release identity/date corroborated by pinned public press-release members and SEC Exhibits 99.x. No licensed vendor data used.",
"notes":"One exact first-public distribution clock; prohibited substitute times are not used."})
contract["reviewed_announcement_exclusions"].update(expected_count=8,expected_sha256=sha(exclusion_path))
contract["purpose"]="Cumulative public point-in-time metadata: G1 has 166 exact release timestamps and 8 reviewed fail-closed exclusions; exact-timing and all independent non-synthetic release locks remain fail-closed."
save(contract_path,contract)

hints["priority_events"]=[r for r in hints.get("priority_events",[]) if r.get("event_id") not in ids]
hints["validation_probes"]=[r for r in hints.get("validation_probes",[]) if r.get("event_id") not in ids]
hints["base_main_sha"]=BASE
hints["current_g1_state"].update(public_exact_batch_count=86,exact_resolved_event_records=166,reviewed_excluded_event_records=8,
 note="The latest integrated recovery is batch_0119; cumulative public exact-time batches are 86 and cumulative exact event records are 166 because some public batches resolve more than one historical event.")
for item in items:
    hints["validation_probes"].append(dict(item,probe_id=f'{item["historical_symbol"]}-batch0119',historical_event_match=True,
      exact_clock_observed=True,exact_public_release_ts=item["public_announcement_ts"],evidence_eligible=False,
      disposition="RESOLVED_IN_BATCH_0119",reason="Promoted from filed federal-court GX 8002 explicit public-distribution clock with pinned press-release/SEC identity corroboration."))
save(hints_path,hints)

assert rebuild.rebuild(ROOT,publish=True)["after"]["up_to_date"]
fresh=rows(md/"announcement_resolutions.csv");by={r["event_id"]:r for r in fresh};assert len(by)==174
for eid,old in old_exact.items():assert by[eid]==old
expected={item["event_id"]:datetime.fromisoformat(item["public_announcement_ts"]).astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00","Z") for item in items}
for item in items:
    r=by[item["event_id"]];assert r["resolution_status"]=="resolved_exact_public_timestamp" and r["public_announcement_ts"]==expected[item["event_id"]]
excluded=[r for r in fresh if r["resolution_status"]=="excluded_fail_closed"]
assert len(excluded)==8 and all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in excluded)
ready=load(md/"metadata_readiness_summary.json");assert ready["announcement_exact_resolved"]==166 and ready["announcement_events_excluded"]==8
assert ready["ready_g1_exact_timing_analysis"] is False

acq=Path("data/public/metadata/g1_acquisition_manifest.json");acq.write_text(acquisition.render_manifest(acquisition.build_manifest()),encoding="utf-8")
sd=Path("data/processed/real_data_release_sprint");cp=Path("data/processed/coverage_plan_real/coverage_summary.json")
sprint.refresh_coverage(coverage_summary_path=cp,metadata_readiness_path=md/"metadata_readiness_summary.json",
 metadata_quality_path=md/"metadata_quality_summary.json",requirements_manifest_path=sd/"requirements_manifest.json",
 unresolved_gates_path=cp.parent/"unresolved_gates.csv")
status=sprint.build_status(requirements_manifest_path=sd/"requirements_manifest.json",coverage_summary_path=cp,
 metadata_readiness_path=md/"metadata_readiness_summary.json",metadata_quality_path=md/"metadata_quality_summary.json",outpath=sd/"step_status.json")
step9=next(x for x in status["steps"] if x["step"]==9);assert step9["status"]=="SOURCE_BLOCKED" and "166/174" in step9["evidence"] and "8" in step9["evidence"]

test_files=[
"tests/test_g1_source_research.py","tests/test_g1_acquisition_manifest.py","tests/test_real_data_release_sprint.py",
*sorted(str(x) for x in Path("tests").glob("test_g1_public_batch_*.py"))
]
for fn in test_files:
    p=Path(fn);txt=p.read_text()
    if fn.endswith("test_g1_source_research.py"):
        pairs=[
          ('report["exact_resolved_event_records"] == 165','report["exact_resolved_event_records"] == 166'),
          ('report["reviewed_excluded_event_records"] == 9','report["reviewed_excluded_event_records"] == 8'),
          ('state["public_exact_batch_count"] == 85','state["public_exact_batch_count"] == 86'),
          ('state["exact_resolved_event_records"] == 165','state["exact_resolved_event_records"] == 166'),
        ]
    elif fn.endswith("test_g1_acquisition_manifest.py"):
        pairs=[
          ('manifest["state"]["exact_resolved"] == 165','manifest["state"]["exact_resolved"] == 166'),
          ('manifest["state"]["acquisition_needed"] == 9','manifest["state"]["acquisition_needed"] == 8'),
          ('len(manifest["work_queue"]) == 9','len(manifest["work_queue"]) == 8'),
          ('len({row["dedupe_key"] for row in manifest["work_queue"]}) == 9','len({row["dedupe_key"] for row in manifest["work_queue"]}) == 8'),
          ('len(resolved) == 165','len(resolved) == 166'),
          ('len(unresolved) == 9','len(unresolved) == 8'),
          ('"EW", "PNRA", "GNTX", "CREE", "NUAN"','"EW", "GNTX", "CREE", "NUAN", "PNRA"'),
        ]
    elif fn.endswith("test_real_data_release_sprint.py"):
        pairs=[('updated["missing_exact_announcement_timestamps"] == 9','updated["missing_exact_announcement_timestamps"] == 8')]
    else:
        pairs=[
          ('(readiness["announcement_exact_resolved"],readiness["announcement_events_excluded"]) == (165,9)','(readiness["announcement_exact_resolved"],readiness["announcement_events_excluded"]) == (166,8)'),
          ('(readiness["announcement_exact_resolved"], readiness["announcement_events_excluded"]) == (165, 9)','(readiness["announcement_exact_resolved"], readiness["announcement_events_excluded"]) == (166, 8)'),
          ('"165/174" in step9["evidence"] and "9" in step9["evidence"]','"166/174" in step9["evidence"] and "8" in step9["evidence"]'),
          ('len(excluded)==9','len(excluded)==8'),
          ('len(excluded) == 9','len(excluded) == 8'),
          ('len(ex)==9','len(ex)==8'),
          ('len(ex) == 9','len(ex) == 8'),
        ]
    for old,new in pairs:
        txt=txt.replace(old,new)
    ast.parse(txt);p.write_text(txt)

p=Path("docs/g1_announcement_times.md");txt=p.read_text()
assert "85 public exact-time batches / 165 exact-resolved" in txt
txt=txt.replace("85 public exact-time batches / 165 exact-resolved","86 public exact-time batches / 166 exact-resolved",1)
txt += """
### Batch 0119: PNRA 2013

Filed E.D.N.Y. GX 8002 Document 367-2 row 1657 supplies the explicit first-public press-release distribution clock for Panera Bread on 2013-04-23 at 16:00 EDT. Official SEC Exhibit 99.1 independently corroborates the exact release identity, headline, content and date. The canonical first documented illicit trade at 14:25 EDT predates the court row's 15:00 Earliest Order Time; the latter was used only by the original research mapper and is not substituted for the canonical trade timestamp. This advances G1 from 165 exact / 9 reviewed exclusions to 166 exact / 8 reviewed exclusions. Step 9 remains SOURCE_BLOCKED.
""";p.write_text(txt)

tp=Path("tests/test_g1_public_batch_0119.py")
ts='''import csv,json,hashlib
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
def rr(p):
    with p.open(newline="",encoding="utf-8") as h:return list(csv.DictReader(h))
def test_batch_0119():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0119_evidence.json").read_text())
    events={r["event_id"]:r for r in rr(ROOT/"data/processed/historical_events.csv")}
    resolved={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    exp={"HEJFE-CCC7747CFBDE893E":("PNRA","2013-04-23T20:00:00Z",5700)}
    assert len(d["items"])==1
    for x in d["items"]:
        sym,utc,delta=exp[x["event_id"]];e=events[x["event_id"]]
        tr=datetime.fromisoformat(e["first_documented_illicit_trade_ts"]).replace(tzinfo=ZoneInfo("America/New_York"));rel=datetime.fromisoformat(x["public_announcement_ts"])
        assert e["historical_symbol"]==sym and tr<rel<=tr+timedelta(days=7) and int((rel-tr).total_seconds())==delta
        assert resolved[x["event_id"]]["public_announcement_ts"]==utc
        assert resolved[x["event_id"]]["resolution_status"]=="resolved_exact_public_timestamp"
        assert x["source_family"]=="federal_court_public_distribution_record" and x["source_grade"]=="A"
        assert x["timestamp_evidence_kind"]=="explicit_release_clock" and x["public_distribution_explicit"] is True
        assert x["gx8002_row_id"]=="1657" and x["wire_source_code"]=="MW"
        assert x["source_reference"].startswith("https://storage.courtlistener.com/recap/")
        assert x["corroboration_reference"].startswith("https://www.sec.gov/Archives/edgar/data/")
def test_batch_0119_preserves_prior():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0119_evidence.json").read_text())
    assert hashlib.sha256((ROOT/d["batch_path"]).read_bytes()).hexdigest()==d["batch_sha256"]
    by={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    for eid,stamp in d["previous_exact_timestamps"].items():assert by[eid]["public_announcement_ts"]==stamp
    ex=[r for r in by.values() if r["resolution_status"]=="excluded_fail_closed"];assert len(ex)==8
    assert all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in ex)
def test_batch_0119_worker4_shard_ownership():
    event_ids={"HEJFE-CCC7747CFBDE893E"}
    assert 119 >= 64 and (119-64) % 5 == 0
    assert all(int(hashlib.sha256(eid.encode("utf-8")).hexdigest(),16) % 5 == 4 for eid in event_ids)
'''
ast.parse(ts);tp.write_text(ts)
assert rebuild.rebuild(ROOT,publish=False)["before"]["up_to_date"]
if not evidence_path.exists(): evidence_path.write_bytes(evidence_snapshot)

for prep_only in (Path("data/public/metadata/g1_public_batch_0119_prep_evidence.json"),Path("tests/test_g1_public_batch_0119_prep.py")):
    if prep_only.exists():prep_only.unlink()

changed=set(subprocess.check_output(["git","diff","--name-only",BASE],text=True).splitlines());changed.update([str(batch),str(evidence_path),str(tp),SCRIPT])
permitted={WORKFLOW,SCRIPT,str(contract_path),str(exclusion_path),str(hints_path),str(acq),str(batch),str(evidence_path),str(tp),
"docs/g1_announcement_times.md","src/metadata_resolver.py","tests/test_metadata_resolver.py","tests/test_g1_source_research.py","tests/test_g1_acquisition_manifest.py","tests/test_real_data_release_sprint.py",
str(cp),str(cp.parent/"unresolved_gates.csv"),str(sd/"step_status.json"),"data/processed/research_receipt_bundle.json",
"data/processed/real_data_replay/real_data_replay_status.json","data/public/metadata/g1_public_batch_0119_integration_spec.json","data/public/metadata/g1_public_batch_0119_prep_evidence.json","tests/test_g1_public_batch_0119_prep.py"} | {str(x) for x in Path("tests").glob("test_g1_public_batch_*.py")} | {str(md/name) for name in rebuild.METADATA_RECEIPTS}
assert changed<=permitted,f"Unexpected {changed-permitted}"
allowp=Path("config/release_drift_allowlist.json");allow=load(allowp);reason="G1 batch 0119 Worker-4 filed federal-court public-distribution clock for PNRA 2013; deterministic 166 exact / 8 reviewed exclusions with SEC identity corroboration and prior evidence preserved."
for name in sorted(changed):
    sec="intentional_release_modifications" if name in allow["intentional_release_modifications"] else "repository_additions"
    allow[sec][name]={"expected_sha256":sha(name),"reason":reason}
save(allowp,allow);changed.add(str(allowp));subprocess.run(["git","add","--",*sorted(changed)],check=True)
audit=Path("private_runtime/audit/g1-batch-0119");audit.mkdir(parents=True,exist_ok=True)
save(audit/"verification.json",{"base_main_sha":BASE,"source_head_sha":os.environ["GITHUB_SHA"],"exact":166,"reviewed_excluded":8,
"previous_exact_preserved":165,"new_events":items,"step9":"SOURCE_BLOCKED","evaluation_release_permitted":False,"deterministic_rebuild_matches":True})
print(json.dumps({"exact":166,"reviewed_excluded":8,"new_events":[x["event_id"] for x in items]},indent=2))
