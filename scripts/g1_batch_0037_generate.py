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
BASE="2f73f5b0507b5b654ea7a0950c9a892bc4fc459f"
WORKFLOW=".github/workflows/g1-public-batch-0037.yml"
SCRIPT="scripts/g1_batch_0037_generate.py"
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
assert len(events)==174 and len(old_exact)==44
exclusion_path=md/"g1_final_timing_exclusions.json"
exclusions=load(exclusion_path)
assert len(exclusions["exclusions"])==130

batch=Path("data/public/metadata/g1_announcement_times_batch_0037.csv")
evidence_path=Path("data/public/metadata/g1_public_batch_0037_evidence.json")
assert not batch.exists() and not evidence_path.exists()

specs=[
{"event_id":"HEJFE-8F17F6BEDF631C8B","historical_symbol":"MCRI","expected_trade":"2013-04-25 15:08:00",
 "clock":"2013-04-25T16:05:00-04:00","publisher_timestamp_text":"2013-04-25T20:05:00Z",
 "release_title":"Monarch Casino Reports 2013 First Quarter Results",
 "source_reference":"https://finance.yahoo.com/news/monarch-casino-reports-2013-first-200500949.html",
 "corroboration_reference":"https://www.sec.gov/Archives/edgar/data/907242/000110262413000482/monarchcasinoandresortinc.htm",
 "corroboration_basis":"Yahoo preserves the original Marketwired release with published_date 2013-04-25T20:05:00Z; the SEC-filed release independently matches Monarch, April 25 2013 and first-quarter 2013 results. No filing acceptance or inferred clock is used.",
 "expected_delta":3420},
{"event_id":"HEJFE-06AE65B9C8FB0395","historical_symbol":"STMP","expected_trade":"2013-04-24 15:28:00",
 "clock":"2013-04-24T16:30:00-04:00","publisher_timestamp_text":"2013-04-24T20:30:00Z",
 "release_title":"Stamps.com Announces Record Non-GAAP Earnings per Share of $0.57",
 "source_reference":"https://finance.yahoo.com/news/stamps-com-announces-record-non-203000566.html",
 "corroboration_reference":"https://www.sec.gov/Archives/edgar/data/1082923/000114036113017456/ex99_1.htm",
 "corroboration_basis":"Yahoo preserves the original Marketwired release with published_date 2013-04-24T20:30:00Z; SEC Exhibit 99.1 independently matches Stamps.com, April 24 2013, first-quarter 2013 results and $32.1 million revenue. The 5:00pm conference call is not used.",
 "expected_delta":3720}
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
      "corroboration_basis":spec["corroboration_basis"],"reviewed_on":"2026-09-29","information_asymmetry_seconds":delta}
    items.append(item)
    trial["validation_probes"].append(dict(item,probe_id=f"{spec['historical_symbol']}-batch0037",historical_event_match=True,
      exact_clock_observed=True,exact_public_release_ts=release.isoformat(),evidence_eligible=True))
research.validate_research_map(trial,exclusions)

fields=["event_id","historical_symbol","event_date","public_announcement_ts","timestamp_kind","source_grade","source_reference"]
s=io.StringIO(newline="");w=csv.DictWriter(s,fieldnames=fields,lineterminator="\n");w.writeheader()
for x in items:w.writerow({k:x[k] for k in fields})
batch.write_text(s.getvalue(),encoding="utf-8")
save(evidence_path,{"schema_version":"1","research_use_only":True,"base_main_sha":BASE,"batch_path":str(batch),"batch_sha256":sha(batch),
"items":items,"previous_exact_count":44,"expected_exact_count_after_batch":46,"expected_excluded_after_batch":128,
"previous_exact_timestamps":{k:r["public_announcement_ts"] for k,r in old_exact.items()},
"evidence_method":"Two Yahoo-preserved original Marketwired publication timestamps with independent SEC-filed release corroboration. CI verifies chronology, event identity and deterministic receipts.",
"prohibited_substitutes":["edgar_acceptance_time","scheduled_call_time","archive_capture_time","inferred_clock","date_only"]})

ids={x["event_id"] for x in items}
exclusions["exclusions"]=[r for r in exclusions["exclusions"] if r["event_id"] not in ids]
exclusions["base_main_sha"]=BASE
exclusions["g1_state"].update(exact_resolved=46,reviewed_excluded=128,raw_exact_time_evidence_gaps=128,exact_timing_analysis_eligible=46)
save(exclusion_path,exclusions)

contract_path=Path("config/metadata_sources.public_progress.json");contract=load(contract_path)
contract["sources"].insert(0,{"source_id":"public-marketwired-mcri-stmp-batch-0037","record_kind":"announcement_timestamp",
"source_family":"official_newswire_archive","path":str(batch),"enabled":True,"authorized":True,"data_classification":"public_official_data",
"delimiter":",","encoding":"utf-8","timezone":"America/New_York","column_map":{k:k for k in fields},
"license_reference":"Public Yahoo-preserved Marketwired publication metadata for Monarch Casino and Stamps.com with SEC-filed issuer release corroboration. No licensed vendor data used.",
"notes":"MCRI 2013-04-25 16:05 EDT; STMP 2013-04-24 16:30 EDT. Conference-call and EDGAR acceptance clocks are not used."})
contract["reviewed_announcement_exclusions"].update(expected_count=128,expected_sha256=sha(exclusion_path))
contract["purpose"]="Cumulative public point-in-time metadata: G1 has 46 exact release timestamps and 128 reviewed fail-closed exclusions; exact-timing and all independent non-synthetic release locks remain fail-closed."
save(contract_path,contract)

hints["base_main_sha"]=BASE
hints["current_g1_state"].update(public_exact_batch_count=37,exact_resolved_event_records=46,reviewed_excluded_event_records=128,
 note="The repository is at batch_0037; cumulative exact event records are 46 because some public batches resolve more than one historical event.")
for item in items:
    hints["validation_probes"].append(dict(item,probe_id=f"{item['historical_symbol']}-batch0037",historical_event_match=True,
      exact_clock_observed=True,exact_public_release_ts=item["public_announcement_ts"],evidence_eligible=False,
      disposition="RESOLVED_IN_BATCH_0037",reason="Promoted through reviewed preserved-wire evidence with SEC corroboration."))
save(hints_path,hints)

assert rebuild.rebuild(ROOT,publish=True)["after"]["up_to_date"]
fresh=rows(md/"announcement_resolutions.csv");by={r["event_id"]:r for r in fresh};assert len(by)==174
for eid,old in old_exact.items():assert by[eid]==old
expected={"HEJFE-8F17F6BEDF631C8B":"2013-04-25T20:05:00Z","HEJFE-06AE65B9C8FB0395":"2013-04-24T20:30:00Z"}
for item in items:
    r=by[item["event_id"]];assert r["resolution_status"]=="resolved_exact_public_timestamp" and r["public_announcement_ts"]==expected[item["event_id"]]
excluded=[r for r in fresh if r["resolution_status"]=="excluded_fail_closed"]
assert len(excluded)==128 and all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in excluded)
ready=load(md/"metadata_readiness_summary.json");assert ready["announcement_exact_resolved"]==46 and ready["announcement_events_excluded"]==128
assert ready["ready_g1_exact_timing_analysis"] is False

acq=Path("data/public/metadata/g1_acquisition_manifest.json");acq.write_text(acquisition.render_manifest(acquisition.build_manifest()),encoding="utf-8")
sd=Path("data/processed/real_data_release_sprint");cp=Path("data/processed/coverage_plan_real/coverage_summary.json")
sprint.refresh_coverage(coverage_summary_path=cp,metadata_readiness_path=md/"metadata_readiness_summary.json",
 metadata_quality_path=md/"metadata_quality_summary.json",requirements_manifest_path=sd/"requirements_manifest.json",
 unresolved_gates_path=cp.parent/"unresolved_gates.csv")
status=sprint.build_status(requirements_manifest_path=sd/"requirements_manifest.json",coverage_summary_path=cp,
 metadata_readiness_path=md/"metadata_readiness_summary.json",metadata_quality_path=md/"metadata_quality_summary.json",outpath=sd/"step_status.json")
step9=next(x for x in status["steps"] if x["step"]==9);assert step9["status"]=="SOURCE_BLOCKED" and "46/174" in step9["evidence"] and "128" in step9["evidence"]

for fn in ["tests/test_g1_source_research.py","tests/test_g1_acquisition_manifest.py","tests/test_real_data_release_sprint.py",
"tests/test_g1_public_batch_0032.py","tests/test_g1_public_batch_0034.py","tests/test_g1_public_batch_0035.py","tests/test_g1_public_batch_0036.py"]:
    p=Path(fn);t=p.read_text()
    t=t.replace("== (44,130)","== (46,128)").replace("len(excluded)==130","len(excluded)==128").replace("len(excluded) == 130","len(excluded) == 128")
    t=t.replace('"44/174" in step9["evidence"] and "130" in step9["evidence"]','"46/174" in step9["evidence"] and "128" in step9["evidence"]')
    t=t.replace('updated["missing_exact_announcement_timestamps"] == 130','updated["missing_exact_announcement_timestamps"] == 128')
    t=re.sub(r"== 44\b","== 46",t);t=re.sub(r"== 130\b","== 128",t)
    if fn.endswith("test_g1_source_research.py"):t=t.replace('state["public_exact_batch_count"] == 36','state["public_exact_batch_count"] == 37')
    ast.parse(t);p.write_text(t)

p=Path("docs/g1_announcement_times.md");t=p.read_text().replace("36 public exact-time batches / 44 exact-resolved","37 public exact-time batches / 46 exact-resolved")
t += """
### Batch 0037: Monarch Casino + Stamps.com

Yahoo Finance preserves the original Marketwired publication metadata for Monarch Casino at 2013-04-25 20:05 UTC and Stamps.com at 2013-04-24 20:30 UTC. Matching SEC-filed issuer releases independently corroborate both. These clocks are 3,420 and 3,720 seconds after the frozen first trades. This advances G1 from 44 exact / 130 reviewed exclusions to 46 exact / 128 reviewed exclusions. Scheduled calls, EDGAR acceptance and inferred clocks remain prohibited substitutes. Step 9 remains SOURCE_BLOCKED.
""";p.write_text(t)

tp=Path("tests/test_g1_public_batch_0037.py")
ts='''import csv,json,hashlib
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
def rr(p):
    with p.open(newline="",encoding="utf-8") as h:return list(csv.DictReader(h))
def test_batch_0037():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0037_evidence.json").read_text())
    events={r["event_id"]:r for r in rr(ROOT/"data/processed/historical_events.csv")}
    resolved={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    exp={"HEJFE-8F17F6BEDF631C8B":("MCRI","2013-04-25T20:05:00Z",3420),"HEJFE-06AE65B9C8FB0395":("STMP","2013-04-24T20:30:00Z",3720)}
    assert len(d["items"])==2
    for x in d["items"]:
        sym,utc,delta=exp[x["event_id"]];e=events[x["event_id"]]
        tr=datetime.fromisoformat(e["first_documented_illicit_trade_ts"]).replace(tzinfo=ZoneInfo("America/New_York"));rel=datetime.fromisoformat(x["public_announcement_ts"])
        assert e["historical_symbol"]==sym and tr<rel<=tr+timedelta(days=7) and int((rel-tr).total_seconds())==delta
        assert resolved[x["event_id"]]["public_announcement_ts"]==utc and x["corroboration_reference"].startswith("https://www.sec.gov/")
def test_batch_0037_preserves_prior():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0037_evidence.json").read_text())
    assert hashlib.sha256((ROOT/d["batch_path"]).read_bytes()).hexdigest()==d["batch_sha256"]
    by={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    for eid,ts in d["previous_exact_timestamps"].items():assert by[eid]["public_announcement_ts"]==ts
    ex=[r for r in by.values() if r["resolution_status"]=="excluded_fail_closed"];assert len(ex)==128
    assert all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in ex)
'''
ast.parse(ts);tp.write_text(ts)
assert rebuild.rebuild(ROOT,publish=False)["before"]["up_to_date"]

changed=set(subprocess.check_output(["git","diff","--name-only",BASE],text=True).splitlines());changed.update([str(batch),str(evidence_path),str(tp),SCRIPT])
permitted={WORKFLOW,SCRIPT,str(contract_path),str(exclusion_path),str(hints_path),str(acq),str(batch),str(evidence_path),str(tp),
"docs/g1_announcement_times.md","tests/test_g1_source_research.py","tests/test_g1_acquisition_manifest.py","tests/test_real_data_release_sprint.py",
"tests/test_g1_public_batch_0032.py","tests/test_g1_public_batch_0034.py","tests/test_g1_public_batch_0035.py","tests/test_g1_public_batch_0036.py",
str(cp),str(cp.parent/"unresolved_gates.csv"),str(sd/"step_status.json"),"data/processed/research_receipt_bundle.json",
"data/processed/real_data_replay/real_data_replay_status.json"} | {str(md/name) for name in rebuild.METADATA_RECEIPTS}
assert changed<=permitted,f"Unexpected {changed-permitted}"
allowp=Path("config/release_drift_allowlist.json");allow=load(allowp);reason="G1 batch 0037 Monarch Casino + Stamps.com preserved Marketwired timestamps; deterministic 46 exact / 128 reviewed exclusions with SEC corroboration."
for name in sorted(changed):
    sec="intentional_release_modifications" if name in allow["intentional_release_modifications"] else "repository_additions"
    allow[sec][name]={"expected_sha256":sha(name),"reason":reason}
save(allowp,allow);changed.add(str(allowp));subprocess.run(["git","add","--",*sorted(changed)],check=True)
audit=Path("private_runtime/audit/g1-batch-0037");audit.mkdir(parents=True,exist_ok=True)
save(audit/"verification.json",{"base_main_sha":BASE,"source_head_sha":os.environ["GITHUB_SHA"],"exact":46,"reviewed_excluded":128,
"previous_exact_preserved":44,"new_events":items,"step9":"SOURCE_BLOCKED","evaluation_release_permitted":False,"deterministic_rebuild_matches":True})
print(json.dumps({"exact":46,"reviewed_excluded":128,"new_events":[x["event_id"] for x in items]},indent=2))
