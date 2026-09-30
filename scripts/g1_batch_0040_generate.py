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
BASE="15e901307ca7cc9789b7ecd9ad4700a3b9db8f40"
WORKFLOW=".github/workflows/g1-public-batch-0040.yml"
SCRIPT="scripts/g1_batch_0040_generate.py"
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
assert len(events)==174 and len(old_exact)==50
exclusion_path=md/"g1_final_timing_exclusions.json"
exclusions=load(exclusion_path)
assert len(exclusions["exclusions"])==124

batch=Path("data/public/metadata/g1_announcement_times_batch_0040.csv")
evidence_path=Path("data/public/metadata/g1_public_batch_0040_evidence.json")
assert not batch.exists() and not evidence_path.exists()

specs=[
{"event_id":"HEJFE-977FEBE8CA3CFCB6","historical_symbol":"MDU","expected_trade":"2015-05-04 15:57:00",
 "clock":"2015-05-04T17:30:00-04:00","publisher_timestamp_text":"Published on 05/04/2015 at 05:30 pm EDT",
 "release_title":"MDU Resources Reports First Quarter Earnings",
 "source_reference":"https://www.marketscreener.com/quote/stock/MDU-RESOURCES-GROUP-INC-13482/news/MDU-Resources-Reports-First-Quarter-Earnings-20311156/",
 "corroboration_reference":"https://www.businesswire.com/news/home/20150504006584/en/MDU-Resources-Reports-Quarter-Earnings",
 "corroboration_basis":"MarketScreener preserves the Business Wire release with an explicit 05:30pm EDT publication clock; the original Business Wire release independently matches MDU Resources, May 4 2015, first-quarter 2015 earnings. The May 5 conference call is not used.",
 "expected_delta":5580},
{"event_id":"HEJFE-9DF82252ED78E41F","historical_symbol":"CBT","expected_trade":"2015-04-29 13:33:00",
 "clock":"2015-04-29T16:05:00-04:00","publisher_timestamp_text":"Published on 04/29/2015 at 04:05 pm EDT",
 "release_title":"Cabot Reports Second Quarter Adjusted EPS of $0.53 and Diluted EPS of $0.41",
 "source_reference":"https://www.marketscreener.com/quote/stock/CABOT-CORPORATION-11994/news/Cabot-Reports-Second-Quarter-Adjusted-EPS-of-0-53-and-Diluted-EPS-of-0-41-20281354/",
 "corroboration_reference":"https://investor.cabot-corp.com/node/10176/pdf",
 "corroboration_basis":"MarketScreener preserves the Business Wire release with an explicit 04:05pm EDT publication clock; Cabot's investor-relations PDF independently matches the April 29 2015 release, fiscal second-quarter results and $0.53 adjusted EPS. The April 30 analyst call is not used.",
 "expected_delta":9120},
{"event_id":"HEJFE-CFA461ED8BCCB889","historical_symbol":"OSK","expected_trade":"2015-04-27 15:29:00",
 "clock":"2015-04-28T07:00:00-04:00","publisher_timestamp_text":"Published on 04/28/2015 at 07:00 am EDT",
 "release_title":"Oshkosh Reports Fiscal 2015 Second Quarter Results",
 "source_reference":"https://www.marketscreener.com/quote/stock/OSHKOSH-CORPORATION-13922/news/Oshkosh-Reports-Fiscal-2015-Second-Quarter-Results-20268999/",
 "corroboration_reference":"https://www.sec.gov/Archives/edgar/data/0000775158/000110465915030777/a15-10025_18k.htm",
 "corroboration_basis":"MarketScreener preserves the Business Wire release with an explicit 07:00am EDT publication clock; Oshkosh's SEC-filed April 28 2015 Form 8-K independently identifies the matching fiscal 2015 second-quarter release as Exhibit 99.1. The 09:00am earnings call is not used.",
 "expected_delta":55860}
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
    trial["validation_probes"].append(dict(item,probe_id=f"{spec['historical_symbol']}-batch0040",historical_event_match=True,
      exact_clock_observed=True,exact_public_release_ts=release.isoformat(),evidence_eligible=True))
research.validate_research_map(trial,exclusions)

fields=["event_id","historical_symbol","event_date","public_announcement_ts","timestamp_kind","source_grade","source_reference"]
s=io.StringIO(newline="");w=csv.DictWriter(s,fieldnames=fields,lineterminator="\n");w.writeheader()
for x in items:w.writerow({k:x[k] for k in fields})
batch.write_text(s.getvalue(),encoding="utf-8")
save(evidence_path,{"schema_version":"1","research_use_only":True,"base_main_sha":BASE,"batch_path":str(batch),"batch_sha256":sha(batch),
"items":items,"previous_exact_count":50,"expected_exact_count_after_batch":53,"expected_excluded_after_batch":121,
"previous_exact_timestamps":{k:r["public_announcement_ts"] for k,r in old_exact.items()},
"evidence_method":"Three clustered MarketScreener-preserved Business Wire publication clocks with independent original-publisher/issuer/SEC corroboration. CI verifies chronology, event identity and deterministic receipts.",
"prohibited_substitutes":["edgar_acceptance_time","scheduled_call_time","archive_capture_time","inferred_clock","date_only"]})

ids={x["event_id"] for x in items}
exclusions["exclusions"]=[r for r in exclusions["exclusions"] if r["event_id"] not in ids]
exclusions["base_main_sha"]=BASE
exclusions["g1_state"].update(exact_resolved=53,reviewed_excluded=121,raw_exact_time_evidence_gaps=121,exact_timing_analysis_eligible=53)
save(exclusion_path,exclusions)

contract_path=Path("config/metadata_sources.public_progress.json");contract=load(contract_path)
contract["sources"].insert(0,{"source_id":"public-businesswire-mdu-cbt-osk-batch-0040","record_kind":"announcement_timestamp",
"source_family":"official_newswire_archive","path":str(batch),"enabled":True,"authorized":True,"data_classification":"public_official_data",
"delimiter":",","encoding":"utf-8","timezone":"America/New_York","column_map":{k:k for k in fields},
"license_reference":"Public MarketScreener-preserved Business Wire publication metadata for MDU Resources, Cabot and Oshkosh with original Business Wire, issuer IR and SEC corroboration. No licensed vendor data used.",
"notes":"MDU 2015-05-04 17:30 EDT; CBT 2015-04-29 16:05 EDT; OSK 2015-04-28 07:00 EDT. Scheduled conference calls and EDGAR acceptance times are not used."})
contract["reviewed_announcement_exclusions"].update(expected_count=121,expected_sha256=sha(exclusion_path))
contract["purpose"]="Cumulative public point-in-time metadata: G1 has 53 exact release timestamps and 121 reviewed fail-closed exclusions; exact-timing and all independent non-synthetic release locks remain fail-closed."
save(contract_path,contract)

hints["base_main_sha"]=BASE
hints["current_g1_state"].update(public_exact_batch_count=40,exact_resolved_event_records=53,reviewed_excluded_event_records=121,
 note="The repository is at batch_0040; cumulative exact event records are 53 because some public batches resolve more than one historical event.")
for item in items:
    hints["validation_probes"].append(dict(item,probe_id=f"{item['historical_symbol']}-batch0037",historical_event_match=True,
      exact_clock_observed=True,exact_public_release_ts=item["public_announcement_ts"],evidence_eligible=False,
      disposition="RESOLVED_IN_BATCH_0040",reason="Promoted through reviewed preserved-wire evidence with SEC corroboration."))
save(hints_path,hints)

assert rebuild.rebuild(ROOT,publish=True)["after"]["up_to_date"]
fresh=rows(md/"announcement_resolutions.csv");by={r["event_id"]:r for r in fresh};assert len(by)==174
for eid,old in old_exact.items():assert by[eid]==old
expected={"HEJFE-977FEBE8CA3CFCB6":"2015-05-04T21:30:00Z","HEJFE-9DF82252ED78E41F":"2015-04-29T20:05:00Z","HEJFE-CFA461ED8BCCB889":"2015-04-28T11:00:00Z"}
for item in items:
    r=by[item["event_id"]];assert r["resolution_status"]=="resolved_exact_public_timestamp" and r["public_announcement_ts"]==expected[item["event_id"]]
excluded=[r for r in fresh if r["resolution_status"]=="excluded_fail_closed"]
assert len(excluded)==121 and all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in excluded)
ready=load(md/"metadata_readiness_summary.json");assert ready["announcement_exact_resolved"]==53 and ready["announcement_events_excluded"]==121
assert ready["ready_g1_exact_timing_analysis"] is False

acq=Path("data/public/metadata/g1_acquisition_manifest.json");acq.write_text(acquisition.render_manifest(acquisition.build_manifest()),encoding="utf-8")
sd=Path("data/processed/real_data_release_sprint");cp=Path("data/processed/coverage_plan_real/coverage_summary.json")
sprint.refresh_coverage(coverage_summary_path=cp,metadata_readiness_path=md/"metadata_readiness_summary.json",
 metadata_quality_path=md/"metadata_quality_summary.json",requirements_manifest_path=sd/"requirements_manifest.json",
 unresolved_gates_path=cp.parent/"unresolved_gates.csv")
status=sprint.build_status(requirements_manifest_path=sd/"requirements_manifest.json",coverage_summary_path=cp,
 metadata_readiness_path=md/"metadata_readiness_summary.json",metadata_quality_path=md/"metadata_quality_summary.json",outpath=sd/"step_status.json")
step9=next(x for x in status["steps"] if x["step"]==9);assert step9["status"]=="SOURCE_BLOCKED" and "53/174" in step9["evidence"] and "121" in step9["evidence"]

for fn in ["tests/test_g1_source_research.py","tests/test_g1_acquisition_manifest.py","tests/test_real_data_release_sprint.py",
"tests/test_g1_public_batch_0032.py","tests/test_g1_public_batch_0034.py","tests/test_g1_public_batch_0035.py","tests/test_g1_public_batch_0036.py","tests/test_g1_public_batch_0037.py","tests/test_g1_public_batch_0038.py","tests/test_g1_public_batch_0039.py"]:
    p=Path(fn);t=p.read_text()
    t=t.replace("== (50,124)","== (53,121)").replace("len(excluded)==124","len(excluded)==121").replace("len(excluded) == 124","len(excluded) == 121").replace("len(ex)==124","len(ex)==121")
    t=t.replace('"50/174" in step9["evidence"] and "124" in step9["evidence"]','"53/174" in step9["evidence"] and "121" in step9["evidence"]')
    t=t.replace('updated["missing_exact_announcement_timestamps"] == 124','updated["missing_exact_announcement_timestamps"] == 121')
    t=re.sub(r"== 50\b","== 53",t);t=re.sub(r"== 124\b","== 121",t)
    if fn.endswith("test_g1_source_research.py"):t=t.replace('state["public_exact_batch_count"] == 39','state["public_exact_batch_count"] == 40')
    ast.parse(t);p.write_text(t)

p=Path("docs/g1_announcement_times.md");t=p.read_text().replace("39 public exact-time batches / 50 exact-resolved","40 public exact-time batches / 53 exact-resolved")
t += """
### Batch 0040: MDU Resources + Cabot + Oshkosh

A clustered public-wire sweep recovered MDU Resources at 2015-05-04 17:30 EDT (21:30 UTC), Cabot at 2015-04-29 16:05 EDT (20:05 UTC), and Oshkosh at 2015-04-28 07:00 EDT (11:00 UTC). MarketScreener preserves the Business Wire publication clocks; original Business Wire, issuer IR, and SEC-filed evidence independently corroborate the releases. The clocks are 5,580, 9,120, and 55,860 seconds after their frozen first trades. This advances G1 from 50 exact / 124 reviewed exclusions to 53 exact / 121 reviewed exclusions. Scheduled calls, EDGAR acceptance and inferred clocks remain prohibited substitutes. Step 9 remains SOURCE_BLOCKED.
""";p.write_text(t)

tp=Path("tests/test_g1_public_batch_0040.py")
ts='''import csv,json,hashlib
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
def rr(p):
    with p.open(newline="",encoding="utf-8") as h:return list(csv.DictReader(h))
def test_batch_0040():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0040_evidence.json").read_text())
    events={r["event_id"]:r for r in rr(ROOT/"data/processed/historical_events.csv")}
    resolved={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    exp={"HEJFE-977FEBE8CA3CFCB6":("MDU","2015-05-04T21:30:00Z",5580),"HEJFE-9DF82252ED78E41F":("CBT","2015-04-29T20:05:00Z",9120),"HEJFE-CFA461ED8BCCB889":("OSK","2015-04-28T11:00:00Z",55860)}
    assert len(d["items"])==3
    for x in d["items"]:
        sym,utc,delta=exp[x["event_id"]];e=events[x["event_id"]]
        tr=datetime.fromisoformat(e["first_documented_illicit_trade_ts"]).replace(tzinfo=ZoneInfo("America/New_York"));rel=datetime.fromisoformat(x["public_announcement_ts"])
        assert e["historical_symbol"]==sym and tr<rel<=tr+timedelta(days=7) and int((rel-tr).total_seconds())==delta
        assert resolved[x["event_id"]]["public_announcement_ts"]==utc
        assert resolved[x["event_id"]]["resolution_status"]=="resolved_exact_public_timestamp"
        assert x["corroboration_reference"].startswith("https://")
def test_batch_0040_preserves_prior():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0040_evidence.json").read_text())
    assert hashlib.sha256((ROOT/d["batch_path"]).read_bytes()).hexdigest()==d["batch_sha256"]
    by={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    for eid,ts in d["previous_exact_timestamps"].items():assert by[eid]["public_announcement_ts"]==ts
    ex=[r for r in by.values() if r["resolution_status"]=="excluded_fail_closed"];assert len(ex)==121
    assert all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in ex)
'''
ast.parse(ts);tp.write_text(ts)
assert rebuild.rebuild(ROOT,publish=False)["before"]["up_to_date"]

changed=set(subprocess.check_output(["git","diff","--name-only",BASE],text=True).splitlines());changed.update([str(batch),str(evidence_path),str(tp),SCRIPT])
permitted={WORKFLOW,SCRIPT,str(contract_path),str(exclusion_path),str(hints_path),str(acq),str(batch),str(evidence_path),str(tp),
"docs/g1_announcement_times.md","tests/test_g1_source_research.py","tests/test_g1_acquisition_manifest.py","tests/test_real_data_release_sprint.py",
"tests/test_g1_public_batch_0032.py","tests/test_g1_public_batch_0034.py","tests/test_g1_public_batch_0035.py","tests/test_g1_public_batch_0036.py","tests/test_g1_public_batch_0037.py","tests/test_g1_public_batch_0038.py","tests/test_g1_public_batch_0039.py",
str(cp),str(cp.parent/"unresolved_gates.csv"),str(sd/"step_status.json"),"data/processed/research_receipt_bundle.json",
"data/processed/real_data_replay/real_data_replay_status.json"} | {str(md/name) for name in rebuild.METADATA_RECEIPTS}
assert changed<=permitted,f"Unexpected {changed-permitted}"
allowp=Path("config/release_drift_allowlist.json");allow=load(allowp);reason="G1 batch 0040 clustered MDU Resources, Cabot and Oshkosh Business Wire timestamps; deterministic 53 exact / 121 reviewed exclusions with independent corroboration and prior evidence preserved."
for name in sorted(changed):
    sec="intentional_release_modifications" if name in allow["intentional_release_modifications"] else "repository_additions"
    allow[sec][name]={"expected_sha256":sha(name),"reason":reason}
save(allowp,allow);changed.add(str(allowp));subprocess.run(["git","add","--",*sorted(changed)],check=True)
audit=Path("private_runtime/audit/g1-batch-0040");audit.mkdir(parents=True,exist_ok=True)
save(audit/"verification.json",{"base_main_sha":BASE,"source_head_sha":os.environ["GITHUB_SHA"],"exact":53,"reviewed_excluded":121,
"previous_exact_preserved":50,"new_events":items,"step9":"SOURCE_BLOCKED","evaluation_release_permitted":False,"deterministic_rebuild_matches":True})
print(json.dumps({"exact":53,"reviewed_excluded":121,"new_events":[x["event_id"] for x in items]},indent=2))
