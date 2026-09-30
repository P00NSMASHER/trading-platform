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
BASE="896a3f5a17a5800aee202d22828ccaaa52f21ba4"
WORKFLOW=".github/workflows/g1-public-batch-0044.yml"
SCRIPT="scripts/g1_batch_0044_generate.py"
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
assert len(events)==174 and len(old_exact)==64
exclusion_path=md/"g1_final_timing_exclusions.json"
exclusions=load(exclusion_path)
assert len(exclusions["exclusions"])==110

batch=Path("data/public/metadata/g1_announcement_times_batch_0044.csv")
evidence_path=Path("data/public/metadata/g1_public_batch_0044_evidence.json")
assert not batch.exists() and not evidence_path.exists()

specs=[
{"event_id":"HEJFE-2F14F138D09BCA76","historical_symbol":"IBKC","expected_trade":"2012-01-24 13:53:00",
 "clock":"2012-01-25T16:30:00-05:00","publisher_timestamp_text":"Jan 25, 2012, 04:30 ET",
 "release_title":"IBERIABANK Corporation Reports Fourth Quarter Results",
 "source_reference":"https://www.prnewswire.com/news/iberiabank-corporation/?page=8&pagesize=25",
 "corroboration_reference":"https://www.sec.gov/Archives/edgar/data/933141/000119312512022713/d290001dex991.htm",
 "corroboration_basis":"PR Newswire's IBERIABANK archive shows the exact Jan. 25 2012 04:30 ET publication clock; SEC Exhibit 99.1 independently matches IBERIABANK Corporation, the January 25 2012 release title, and fourth-quarter 2011 results. The 9:00 a.m. Central conference call is not used.",
 "expected_delta":95820},
{"event_id":"HEJFE-830D52F9F7F1CEEB","historical_symbol":"MSCC","expected_trade":"2012-01-26 14:51:00",
 "clock":"2012-01-26T16:00:00-05:00","publisher_timestamp_text":"Jan 26, 2012, 04:00 ET",
 "release_title":"Microsemi Reports First Quarter 2012 Results",
 "source_reference":"https://www.prnewswire.com/news/microsemi-corporation/?page=20&pagesize=25",
 "corroboration_reference":"https://www.sec.gov/Archives/edgar/data/310568/000114420412004117/v300492_ex99-1.htm",
 "corroboration_basis":"PR Newswire's Microsemi archive shows the exact Jan. 26 2012 04:00 ET publication clock; SEC Exhibit 99.1 independently matches Microsemi Corporation, the January 26 2012 release title, and fiscal first-quarter 2012 results. Conference-call timing is not used.",
 "expected_delta":4140}
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
    trial["validation_probes"].append(dict(item,probe_id=f"{spec['historical_symbol']}-batch0044",historical_event_match=True,
      exact_clock_observed=True,exact_public_release_ts=release.isoformat(),evidence_eligible=True))
research.validate_research_map(trial,exclusions)

fields=["event_id","historical_symbol","event_date","public_announcement_ts","timestamp_kind","source_grade","source_reference"]
s=io.StringIO(newline="");w=csv.DictWriter(s,fieldnames=fields,lineterminator="\n");w.writeheader()
for x in items:w.writerow({k:x[k] for k in fields})
batch.write_text(s.getvalue(),encoding="utf-8")
save(evidence_path,{"schema_version":"1","research_use_only":True,"base_main_sha":BASE,"batch_path":str(batch),"batch_sha256":sha(batch),
"items":items,"previous_exact_count":64,"expected_exact_count_after_batch":66,"expected_excluded_after_batch":108,
"previous_exact_timestamps":{k:r["public_announcement_ts"] for k,r in old_exact.items()},
"evidence_method":"Two direct PR Newswire archive publication clocks for IBERIABANK and Microsemi with independent SEC issuer-release corroboration. CI verifies chronology, event identity and deterministic receipts; scheduled conference-call times are not used.",
"prohibited_substitutes":["edgar_acceptance_time","scheduled_call_time","archive_capture_time","inferred_clock","date_only"]})

ids={x["event_id"] for x in items}
exclusions["exclusions"]=[r for r in exclusions["exclusions"] if r["event_id"] not in ids]
exclusions["base_main_sha"]=BASE
exclusions["g1_state"].update(exact_resolved=66,reviewed_excluded=108,raw_exact_time_evidence_gaps=108,exact_timing_analysis_eligible=66)
save(exclusion_path,exclusions)

contract_path=Path("config/metadata_sources.public_progress.json");contract=load(contract_path)
contract["sources"].insert(0,{"source_id":"public-prnewswire-ibkc-mscc-batch-0044","record_kind":"announcement_timestamp",
"source_family":"official_newswire_archive","path":str(batch),"enabled":True,"authorized":True,"data_classification":"public_official_data",
"delimiter":",","encoding":"utf-8","timezone":"America/New_York","column_map":{k:k for k in fields},
"license_reference":"Public primary PR Newswire archive metadata for IBERIABANK Corporation and Microsemi with independent SEC Exhibit 99.1 corroboration. No licensed vendor data used.",
"notes":"IBKC 2012-01-25 16:30 EST; MSCC 2012-01-26 16:00 EST. Scheduled conference calls and EDGAR acceptance times are not used."})
contract["reviewed_announcement_exclusions"].update(expected_count=108,expected_sha256=sha(exclusion_path))
contract["purpose"]="Cumulative public point-in-time metadata: G1 has 66 exact release timestamps and 108 reviewed fail-closed exclusions; exact-timing and all independent non-synthetic release locks remain fail-closed."
save(contract_path,contract)

hints["base_main_sha"]=BASE
hints["current_g1_state"].update(public_exact_batch_count=44,exact_resolved_event_records=66,reviewed_excluded_event_records=108,
 note="The repository is at batch_0044; cumulative exact event records are 66 because some public batches resolve more than one historical event.")
for item in items:
    hints["validation_probes"].append(dict(item,probe_id=f"{item['historical_symbol']}-batch0044",historical_event_match=True,
      exact_clock_observed=True,exact_public_release_ts=item["public_announcement_ts"],evidence_eligible=False,
      disposition="RESOLVED_IN_BATCH_0044",reason="Promoted through direct primary-newswire timestamp evidence with SEC corroboration."))
save(hints_path,hints)

assert rebuild.rebuild(ROOT,publish=True)["after"]["up_to_date"]
fresh=rows(md/"announcement_resolutions.csv");by={r["event_id"]:r for r in fresh};assert len(by)==174
for eid,old in old_exact.items():assert by[eid]==old
expected={"HEJFE-2F14F138D09BCA76":"2012-01-25T21:30:00Z","HEJFE-830D52F9F7F1CEEB":"2012-01-26T21:00:00Z"}
for item in items:
    r=by[item["event_id"]];assert r["resolution_status"]=="resolved_exact_public_timestamp" and r["public_announcement_ts"]==expected[item["event_id"]]
excluded=[r for r in fresh if r["resolution_status"]=="excluded_fail_closed"]
assert len(excluded)==108 and all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in excluded)
ready=load(md/"metadata_readiness_summary.json");assert ready["announcement_exact_resolved"]==66 and ready["announcement_events_excluded"]==108
assert ready["ready_g1_exact_timing_analysis"] is False

acq=Path("data/public/metadata/g1_acquisition_manifest.json");acq.write_text(acquisition.render_manifest(acquisition.build_manifest()),encoding="utf-8")
sd=Path("data/processed/real_data_release_sprint");cp=Path("data/processed/coverage_plan_real/coverage_summary.json")
sprint.refresh_coverage(coverage_summary_path=cp,metadata_readiness_path=md/"metadata_readiness_summary.json",
 metadata_quality_path=md/"metadata_quality_summary.json",requirements_manifest_path=sd/"requirements_manifest.json",
 unresolved_gates_path=cp.parent/"unresolved_gates.csv")
status=sprint.build_status(requirements_manifest_path=sd/"requirements_manifest.json",coverage_summary_path=cp,
 metadata_readiness_path=md/"metadata_readiness_summary.json",metadata_quality_path=md/"metadata_quality_summary.json",outpath=sd/"step_status.json")
step9=next(x for x in status["steps"] if x["step"]==9);assert step9["status"]=="SOURCE_BLOCKED" and "66/174" in step9["evidence"] and "108" in step9["evidence"]

for fn in ["tests/test_g1_source_research.py","tests/test_g1_acquisition_manifest.py","tests/test_real_data_release_sprint.py",
"tests/test_g1_public_batch_0032.py","tests/test_g1_public_batch_0034.py","tests/test_g1_public_batch_0035.py","tests/test_g1_public_batch_0036.py","tests/test_g1_public_batch_0037.py","tests/test_g1_public_batch_0038.py","tests/test_g1_public_batch_0039.py","tests/test_g1_public_batch_0040.py","tests/test_g1_public_batch_0041.py","tests/test_g1_public_batch_0042.py","tests/test_g1_public_batch_0043.py"]:
    p=Path(fn);t=p.read_text()
    t=t.replace("== (64,110)","== (66,108)").replace("len(excluded)==110","len(excluded)==108").replace("len(excluded) == 110","len(excluded) == 108").replace("len(ex)==110","len(ex)==108")
    t=t.replace('"64/174" in step9["evidence"] and "110" in step9["evidence"]','"66/174" in step9["evidence"] and "108" in step9["evidence"]')
    t=t.replace('updated["missing_exact_announcement_timestamps"] == 110','updated["missing_exact_announcement_timestamps"] == 108')
    t=re.sub(r"== 64\b","== 66",t);t=re.sub(r"== 110\b","== 108",t)
    if fn.endswith("test_g1_source_research.py"):t=t.replace('state["public_exact_batch_count"] == 43','state["public_exact_batch_count"] == 44')
    ast.parse(t);p.write_text(t)

p=Path("docs/g1_announcement_times.md");t=p.read_text().replace("43 public exact-time batches / 64 exact-resolved","44 public exact-time batches / 66 exact-resolved")
t += """
### Batch 0044: IBERIABANK + Microsemi

A primary-newswire sweep recovered two additional exact first-public clocks: IBERIABANK Corporation at 2012-01-25 16:30 EST (21:30 UTC) and Microsemi at 2012-01-26 16:00 EST (21:00 UTC). PR Newswire historical company archives preserve the exact publication clocks, while SEC-filed Exhibit 99.1 releases independently corroborate issuer, title, date, and reporting period. The clocks are 95,820 and 4,140 seconds after their frozen first trades. This advances G1 from 64 exact / 110 reviewed exclusions to 66 exact / 108 reviewed exclusions. Scheduled calls, EDGAR acceptance, archive-capture, date-only, and inferred clocks remain prohibited substitutes. Step 9 remains SOURCE_BLOCKED.
""";p.write_text(t)

tp=Path("tests/test_g1_public_batch_0044.py")
ts='''import csv,json,hashlib
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
def rr(p):
    with p.open(newline="",encoding="utf-8") as h:return list(csv.DictReader(h))
def test_batch_0044():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0044_evidence.json").read_text())
    events={r["event_id"]:r for r in rr(ROOT/"data/processed/historical_events.csv")}
    resolved={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    exp={"HEJFE-2F14F138D09BCA76":("IBKC","2012-01-25T21:30:00Z",95820),"HEJFE-830D52F9F7F1CEEB":("MSCC","2012-01-26T21:00:00Z",4140)}
    assert len(d["items"])==2
    for x in d["items"]:
        sym,utc,delta=exp[x["event_id"]];e=events[x["event_id"]]
        tr=datetime.fromisoformat(e["first_documented_illicit_trade_ts"]).replace(tzinfo=ZoneInfo("America/New_York"));rel=datetime.fromisoformat(x["public_announcement_ts"])
        assert e["historical_symbol"]==sym and tr<rel<=tr+timedelta(days=7) and int((rel-tr).total_seconds())==delta
        assert resolved[x["event_id"]]["public_announcement_ts"]==utc
        assert resolved[x["event_id"]]["resolution_status"]=="resolved_exact_public_timestamp"
        assert x["source_family"]=="official_newswire_archive" and x["source_grade"]=="A"
        assert x["corroboration_reference"].startswith("https://www.sec.gov/")
def test_batch_0044_preserves_prior():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0044_evidence.json").read_text())
    assert hashlib.sha256((ROOT/d["batch_path"]).read_bytes()).hexdigest()==d["batch_sha256"]
    by={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    for eid,ts in d["previous_exact_timestamps"].items():assert by[eid]["public_announcement_ts"]==ts
    ex=[r for r in by.values() if r["resolution_status"]=="excluded_fail_closed"];assert len(ex)==108
    assert all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in ex)
'''
ast.parse(ts);tp.write_text(ts)
assert rebuild.rebuild(ROOT,publish=False)["before"]["up_to_date"]

changed=set(subprocess.check_output(["git","diff","--name-only",BASE],text=True).splitlines());changed.update([str(batch),str(evidence_path),str(tp),SCRIPT])
permitted={WORKFLOW,SCRIPT,str(contract_path),str(exclusion_path),str(hints_path),str(acq),str(batch),str(evidence_path),str(tp),
"docs/g1_announcement_times.md","tests/test_g1_source_research.py","tests/test_g1_acquisition_manifest.py","tests/test_real_data_release_sprint.py",
"tests/test_g1_public_batch_0032.py","tests/test_g1_public_batch_0034.py","tests/test_g1_public_batch_0035.py","tests/test_g1_public_batch_0036.py","tests/test_g1_public_batch_0037.py","tests/test_g1_public_batch_0038.py","tests/test_g1_public_batch_0039.py","tests/test_g1_public_batch_0040.py","tests/test_g1_public_batch_0041.py","tests/test_g1_public_batch_0042.py","tests/test_g1_public_batch_0043.py",
str(cp),str(cp.parent/"unresolved_gates.csv"),str(sd/"step_status.json"),"data/processed/research_receipt_bundle.json",
"data/processed/real_data_replay/real_data_replay_status.json"} | {str(md/name) for name in rebuild.METADATA_RECEIPTS}
assert changed<=permitted,f"Unexpected {changed-permitted}"
allowp=Path("config/release_drift_allowlist.json");allow=load(allowp);reason="G1 batch 0044 direct PR Newswire clocks for IBERIABANK Corporation and Microsemi; deterministic 66 exact / 108 reviewed exclusions with SEC corroboration and prior evidence preserved."
for name in sorted(changed):
    sec="intentional_release_modifications" if name in allow["intentional_release_modifications"] else "repository_additions"
    allow[sec][name]={"expected_sha256":sha(name),"reason":reason}
save(allowp,allow);changed.add(str(allowp));subprocess.run(["git","add","--",*sorted(changed)],check=True)
audit=Path("private_runtime/audit/g1-batch-0044");audit.mkdir(parents=True,exist_ok=True)
save(audit/"verification.json",{"base_main_sha":BASE,"source_head_sha":os.environ["GITHUB_SHA"],"exact":66,"reviewed_excluded":108,
"previous_exact_preserved":64,"new_events":items,"step9":"SOURCE_BLOCKED","evaluation_release_permitted":False,"deterministic_rebuild_matches":True})
print(json.dumps({"exact":66,"reviewed_excluded":108,"new_events":[x["event_id"] for x in items]},indent=2))
