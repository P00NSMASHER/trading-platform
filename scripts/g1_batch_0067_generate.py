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
BASE="0b4739b3997494c28dfffbfe7fe45a8be84ca638"
WORKFLOW=".github/workflows/g1-public-batch-0067-worker-2.yml"
SCRIPT="scripts/g1_batch_0067_generate.py"
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
assert len(events)==174 and len(old_exact)==84
exclusion_path=md/"g1_final_timing_exclusions.json"
exclusions=load(exclusion_path)
assert len(exclusions["exclusions"])==90

batch=Path("data/public/metadata/g1_announcement_times_batch_0067.csv")
evidence_path=Path("data/public/metadata/g1_public_batch_0067_evidence.json")
assert not batch.exists() and not evidence_path.exists()

specs=[
{"event_id":"HEJFE-ED329F780A1085DA","historical_symbol":"EW","expected_trade":"2013-04-23 13:28:00",
 "clock":"2013-04-23T16:01:00-04:00","publisher_timestamp_text":"SEC complaint: public distribution by Marketwired at 4:01 p.m. ET",
 "release_title":"EDWARDS LIFESCIENCES REPORTS FIRST QUARTER RESULTS",
 "source_reference":"https://www.sec.gov/files/litigation/complaints/2016/comp23471.pdf",
 "corroboration_reference":"https://www.sec.gov/Archives/edgar/data/1099800/000110465913031633/a13-10613_1ex99d1.htm",
 "corroboration_basis":"The SEC civil complaint states that Marketwired publicly distributed Edwards Lifesciences' earnings release on April 23, 2013 at 4:01 p.m.; SEC Exhibit 99.1 independently matches Edwards Lifesciences Corporation (NYSE: EW), the April 23 2013 release title, reporting period and results. The separately stated 5:00 p.m. ET conference call is not used.",
 "expected_delta":9180},
{"event_id":"HEJFE-2C887DA6F617936F","historical_symbol":"TIBX","expected_trade":"2013-09-19 15:29:00",
 "clock":"2013-09-19T16:05:00-04:00","publisher_timestamp_text":"SEC complaint table: Newswire Service 1 distributes TIBCO's 3Q earnings release to the public at 4:05 p.m. ET",
 "release_title":"TIBCO SOFTWARE REPORTS THIRD QUARTER RESULTS",
 "source_reference":"https://www.sec.gov/files/litigation/complaints/2015/comp-pr2015-163.pdf",
 "corroboration_reference":"https://www.sec.gov/Archives/edgar/data/1085280/000119312513371732/d600328dex991.htm",
 "corroboration_basis":"The SEC civil complaint states that Newswire Service 1 publicly disseminated TIBCO's third-quarter release on September 19, 2013 at 4:05 p.m. and its table labels the time column ET; SEC Exhibit 99.1 independently matches TIBCO Software Inc. (NASDAQ: TIBX), the September 19 2013 release title, reporting period and results. The separately scheduled 4:30 p.m. ET conference call is not used.",
 "expected_delta":2160}
]
items=[]
hints_path=Path("data/public/metadata/g1_source_research_20260928.json")
hints=load(hints_path);trial=copy.deepcopy(hints)
trial["validation_probes"]=[r for r in trial.get("validation_probes",[]) if r.get("event_id") not in {x["event_id"] for x in specs}]
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
      "timestamp_kind":"first_public_release","timestamp_evidence_kind":"explicit_release_clock","source_family":"sec_litigation_public_distribution_record",
      "source_grade":"A","publisher_timestamp_text":spec["publisher_timestamp_text"],"release_title":spec["release_title"],
      "public_distribution_explicit":True,
      "source_reference":spec["source_reference"],"corroboration_reference":spec["corroboration_reference"],
      "corroboration_basis":spec["corroboration_basis"],"reviewed_on":"2026-09-30","information_asymmetry_seconds":delta}
    items.append(item)
    trial["validation_probes"].append(dict(item,probe_id=f"{spec['historical_symbol']}-batch0067",historical_event_match=True,
      exact_clock_observed=True,exact_public_release_ts=release.isoformat(),evidence_eligible=True))
research.validate_research_map(trial,exclusions)

fields=["event_id","historical_symbol","event_date","public_announcement_ts","timestamp_kind","source_grade","source_reference"]
s=io.StringIO(newline="");w=csv.DictWriter(s,fieldnames=fields,lineterminator="\n");w.writeheader()
for x in items:w.writerow({k:x[k] for k in fields})
batch.write_text(s.getvalue(),encoding="utf-8")
save(evidence_path,{"schema_version":"1","research_use_only":True,"base_main_sha":BASE,"batch_path":str(batch),"batch_sha256":sha(batch),
"items":items,"previous_exact_count":84,"expected_exact_count_after_batch":86,"expected_excluded_after_batch":88,
"previous_exact_timestamps":{k:r["public_announcement_ts"] for k,r in old_exact.items()},
"evidence_method":"Two SEC civil complaints explicitly record the public distribution clock for the matching historical earnings releases: Edwards at 4:01 p.m. ET and TIBCO at 4:05 p.m. ET. Matching SEC Exhibits 99.1 independently corroborate issuer, title, date, reporting period and release content. The source-research validator admits this family only when the source is an SEC litigation complaint, the timestamp semantics are explicit_release_clock, public distribution is explicitly identified, and independent SEC Exhibit corroboration is present. Conference-call, EDGAR acceptance, archive-capture, scheduled-release, date-only and inferred times are not used.",
"prohibited_substitutes":["edgar_acceptance_time","scheduled_call_time","archive_capture_time","inferred_clock","date_only"]})

ids={x["event_id"] for x in items}
exclusions["exclusions"]=[r for r in exclusions["exclusions"] if r["event_id"] not in ids]
exclusions["base_main_sha"]=BASE
exclusions["g1_state"].update(exact_resolved=86,reviewed_excluded=88,raw_exact_time_evidence_gaps=88,exact_timing_analysis_eligible=86)
save(exclusion_path,exclusions)

contract_path=Path("config/metadata_sources.public_progress.json");contract=load(contract_path)
contract["sources"].insert(0,{"source_id":"public-sec-litigation-ew-tibx-batch-0067","record_kind":"announcement_timestamp",
"source_family":"sec_litigation_public_distribution_record","path":str(batch),"enabled":True,"authorized":True,"data_classification":"public_official_data",
"delimiter":",","encoding":"utf-8","timezone":"America/New_York","column_map":{k:k for k in fields},
"license_reference":"Public SEC civil complaints with explicit newswire public-distribution clocks, independently corroborated by matching SEC Exhibits 99.1. No licensed vendor data used.",
"notes":"EW 2013-04-23 16:01 EDT; TIBX 2013-09-19 16:05 EDT. The SEC litigation records explicitly identify public dissemination/distribution. Conference-call, EDGAR acceptance, archive-capture, scheduled-release, date-only and inferred times are not used."})
contract["reviewed_announcement_exclusions"].update(expected_count=88,expected_sha256=sha(exclusion_path))
contract["purpose"]="Cumulative public point-in-time metadata: G1 has 86 exact release timestamps and 88 reviewed fail-closed exclusions; exact-timing and all independent non-synthetic release locks remain fail-closed."
save(contract_path,contract)

hints["priority_events"]=[r for r in hints.get("priority_events",[]) if r.get("event_id") not in ids]
hints["validation_probes"]=[r for r in hints.get("validation_probes",[]) if r.get("event_id") not in ids]
hints["base_main_sha"]=BASE
hints["current_g1_state"].update(public_exact_batch_count=57,exact_resolved_event_records=86,reviewed_excluded_event_records=88,
 note="The latest integrated recovery is batch_0067; cumulative public exact-time batches are 57 and cumulative exact event records are 86 because some public batches resolve more than one historical event.")
for item in items:
    hints["validation_probes"].append(dict(item,probe_id=f"{item['historical_symbol']}-batch0067",historical_event_match=True,
      exact_clock_observed=True,exact_public_release_ts=item["public_announcement_ts"],evidence_eligible=False,
      disposition="RESOLVED_IN_BATCH_0067",reason="Promoted through an SEC civil-complaint record that explicitly identifies the first public distribution clock, with independent SEC Exhibit 99.1 corroboration."))
save(hints_path,hints)

assert rebuild.rebuild(ROOT,publish=True)["after"]["up_to_date"]
fresh=rows(md/"announcement_resolutions.csv");by={r["event_id"]:r for r in fresh};assert len(by)==174
for eid,old in old_exact.items():assert by[eid]==old
expected={"HEJFE-ED329F780A1085DA":"2013-04-23T20:01:00Z","HEJFE-2C887DA6F617936F":"2013-09-19T20:05:00Z"}
for item in items:
    r=by[item["event_id"]];assert r["resolution_status"]=="resolved_exact_public_timestamp" and r["public_announcement_ts"]==expected[item["event_id"]]
excluded=[r for r in fresh if r["resolution_status"]=="excluded_fail_closed"]
assert len(excluded)==88 and all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in excluded)
ready=load(md/"metadata_readiness_summary.json");assert ready["announcement_exact_resolved"]==86 and ready["announcement_events_excluded"]==88
assert ready["ready_g1_exact_timing_analysis"] is False

acq=Path("data/public/metadata/g1_acquisition_manifest.json");acq.write_text(acquisition.render_manifest(acquisition.build_manifest()),encoding="utf-8")
sd=Path("data/processed/real_data_release_sprint");cp=Path("data/processed/coverage_plan_real/coverage_summary.json")
sprint.refresh_coverage(coverage_summary_path=cp,metadata_readiness_path=md/"metadata_readiness_summary.json",
 metadata_quality_path=md/"metadata_quality_summary.json",requirements_manifest_path=sd/"requirements_manifest.json",
 unresolved_gates_path=cp.parent/"unresolved_gates.csv")
status=sprint.build_status(requirements_manifest_path=sd/"requirements_manifest.json",coverage_summary_path=cp,
 metadata_readiness_path=md/"metadata_readiness_summary.json",metadata_quality_path=md/"metadata_quality_summary.json",outpath=sd/"step_status.json")
step9=next(x for x in status["steps"] if x["step"]==9);assert step9["status"]=="SOURCE_BLOCKED" and "86/174" in step9["evidence"] and "88" in step9["evidence"]

test_files=[
"tests/test_g1_source_research.py","tests/test_g1_acquisition_manifest.py","tests/test_real_data_release_sprint.py",
*sorted(str(x) for x in Path("tests").glob("test_g1_public_batch_*.py"))
]
for fn in test_files:
    p=Path(fn);txt=p.read_text()
    if fn.endswith("test_g1_source_research.py"):
        pairs=[
          ('report["exact_resolved_event_records"] == 84','report["exact_resolved_event_records"] == 86'),
          ('report["reviewed_excluded_event_records"] == 90','report["reviewed_excluded_event_records"] == 88'),
          ('state["public_exact_batch_count"] == 56','state["public_exact_batch_count"] == 57'),
          ('state["exact_resolved_event_records"] == 84','state["exact_resolved_event_records"] == 86'),
        ]
    elif fn.endswith("test_g1_acquisition_manifest.py"):
        pairs=[
          ('manifest["state"]["exact_resolved"] == 84','manifest["state"]["exact_resolved"] == 86'),
          ('manifest["state"]["acquisition_needed"] == 90','manifest["state"]["acquisition_needed"] == 88'),
          ('len(manifest["work_queue"]) == 90','len(manifest["work_queue"]) == 88'),
          ('len({row["dedupe_key"] for row in manifest["work_queue"]}) == 90','len({row["dedupe_key"] for row in manifest["work_queue"]}) == 88'),
          ('len(resolved) == 84','len(resolved) == 86'),
          ('len(unresolved) == 90','len(unresolved) == 88'),
        ]
    elif fn.endswith("test_real_data_release_sprint.py"):
        pairs=[('updated["missing_exact_announcement_timestamps"] == 90','updated["missing_exact_announcement_timestamps"] == 88')]
    else:
        pairs=[
          ('(readiness["announcement_exact_resolved"],readiness["announcement_events_excluded"]) == (84,90)','(readiness["announcement_exact_resolved"],readiness["announcement_events_excluded"]) == (86,88)'),
          ('(readiness["announcement_exact_resolved"], readiness["announcement_events_excluded"]) == (84, 90)','(readiness["announcement_exact_resolved"], readiness["announcement_events_excluded"]) == (86, 88)'),
          ('"84/174" in step9["evidence"] and "90" in step9["evidence"]','"86/174" in step9["evidence"] and "88" in step9["evidence"]'),
          ('len(excluded)==90','len(excluded)==88'),
          ('len(excluded) == 90','len(excluded) == 88'),
          ('len(ex)==90','len(ex)==88'),
          ('len(ex) == 90','len(ex) == 88'),
        ]
    for old,new in pairs:
        txt=txt.replace(old,new)
    ast.parse(txt);p.write_text(txt)

p=Path("docs/g1_announcement_times.md");txt=p.read_text()
assert "56 public exact-time batches / 84 exact-resolved" in txt
txt=txt.replace("56 public exact-time batches / 84 exact-resolved","57 public exact-time batches / 86 exact-resolved",1)
txt += """
### Batch 0067: Edwards Lifesciences and TIBCO Software

SEC civil complaints explicitly record the first public newswire distribution clocks for two hacked-release events. Edwards Lifesciences' April 23, 2013 first-quarter release was publicly distributed at 16:01 EDT (20:01 UTC), 9,180 seconds after the frozen 13:28 EDT illicit trade. TIBCO Software's September 19, 2013 third-quarter release was publicly distributed at 16:05 EDT (20:05 UTC), 2,160 seconds after the frozen 15:29 EDT illicit trade. Matching SEC Exhibits 99.1 independently corroborate issuer, title, release date, reporting period, and release content. The regulator source family is fail-closed: only SEC litigation complaint URLs with explicit public-distribution language, explicit_release_clock semantics, and independent SEC Exhibit corroboration are admissible. This advances G1 from 84 exact / 90 reviewed exclusions to 86 exact / 88 reviewed exclusions. Conference-call, scheduled-release, EDGAR acceptance, archive-capture, date-only, and inferred clocks are not used. Step 9 remains SOURCE_BLOCKED.
""";p.write_text(txt)

tp=Path("tests/test_g1_public_batch_0067.py")
ts='''import csv,json,hashlib
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
def rr(p):
    with p.open(newline="",encoding="utf-8") as h:return list(csv.DictReader(h))
def test_batch_0067():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0067_evidence.json").read_text())
    events={r["event_id"]:r for r in rr(ROOT/"data/processed/historical_events.csv")}
    resolved={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    exp={"HEJFE-ED329F780A1085DA":("EW","2013-04-23T20:01:00Z",9180),"HEJFE-2C887DA6F617936F":("TIBX","2013-09-19T20:05:00Z",2160)}
    assert len(d["items"])==2
    for x in d["items"]:
        sym,utc,delta=exp[x["event_id"]];e=events[x["event_id"]]
        tr=datetime.fromisoformat(e["first_documented_illicit_trade_ts"]).replace(tzinfo=ZoneInfo("America/New_York"));rel=datetime.fromisoformat(x["public_announcement_ts"])
        assert e["historical_symbol"]==sym and tr<rel<=tr+timedelta(days=7) and int((rel-tr).total_seconds())==delta
        assert resolved[x["event_id"]]["public_announcement_ts"]==utc
        assert resolved[x["event_id"]]["resolution_status"]=="resolved_exact_public_timestamp"
        assert x["source_family"]=="sec_litigation_public_distribution_record" and x["source_grade"]=="A"
        assert x["timestamp_evidence_kind"]=="explicit_release_clock"
        assert x["public_distribution_explicit"] is True
        assert x["source_reference"].startswith("https://www.sec.gov/files/litigation/complaints/")
        assert x["corroboration_reference"].startswith("https://www.sec.gov/Archives/edgar/data/")
def test_batch_0067_preserves_prior():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0067_evidence.json").read_text())
    assert hashlib.sha256((ROOT/d["batch_path"]).read_bytes()).hexdigest()==d["batch_sha256"]
    by={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    for eid,stamp in d["previous_exact_timestamps"].items():assert by[eid]["public_announcement_ts"]==stamp
    ex=[r for r in by.values() if r["resolution_status"]=="excluded_fail_closed"];assert len(ex)==88
    assert all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in ex)
'''

ast.parse(ts);tp.write_text(ts)
assert rebuild.rebuild(ROOT,publish=False)["before"]["up_to_date"]

changed=set(subprocess.check_output(["git","diff","--name-only",BASE],text=True).splitlines());changed.update([str(batch),str(evidence_path),str(tp),SCRIPT])
permitted={WORKFLOW,SCRIPT,"src/g1_source_research.py","src/metadata_resolver.py","src/metadata_quality.py","tests/test_metadata_resolver.py",str(contract_path),str(exclusion_path),str(hints_path),str(acq),str(batch),str(evidence_path),str(tp),
"docs/g1_announcement_times.md","tests/test_g1_source_research.py","tests/test_g1_acquisition_manifest.py","tests/test_real_data_release_sprint.py",
str(cp),str(cp.parent/"unresolved_gates.csv"),str(sd/"step_status.json"),"data/processed/research_receipt_bundle.json",
"data/processed/real_data_replay/real_data_replay_status.json"} | {str(x) for x in Path("tests").glob("test_g1_public_batch_*.py")} | {str(md/name) for name in rebuild.METADATA_RECEIPTS}
assert changed<=permitted,f"Unexpected {changed-permitted}"
allowp=Path("config/release_drift_allowlist.json");allow=load(allowp);reason="G1 batch 0067 SEC civil-complaint explicit public-distribution clocks for Edwards Lifesciences and TIBCO; deterministic 86 exact / 88 reviewed exclusions, independent SEC Exhibit corroboration, strict regulator-source validation, and prior evidence preserved."
for name in sorted(changed):
    sec="intentional_release_modifications" if name in allow["intentional_release_modifications"] else "repository_additions"
    allow[sec][name]={"expected_sha256":sha(name),"reason":reason}
save(allowp,allow);changed.add(str(allowp));subprocess.run(["git","add","--",*sorted(changed)],check=True)
audit=Path("private_runtime/audit/g1-batch-0067");audit.mkdir(parents=True,exist_ok=True)
save(audit/"verification.json",{"base_main_sha":BASE,"source_head_sha":os.environ["GITHUB_SHA"],"exact":86,"reviewed_excluded":88,
"previous_exact_preserved":84,"new_events":items,"step9":"SOURCE_BLOCKED","evaluation_release_permitted":False,"deterministic_rebuild_matches":True})
print(json.dumps({"exact":86,"reviewed_excluded":88,"new_events":[x["event_id"] for x in items]},indent=2))