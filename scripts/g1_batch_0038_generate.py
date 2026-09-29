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
BASE="d30ac479d21509ec8d7db171fde80f8f5fc68437"
WORKFLOW=".github/workflows/g1-public-batch-0038.yml"
SCRIPT="scripts/g1_batch_0038_generate.py"
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
assert len(events)==174 and len(old_exact)==46
exclusion_path=md/"g1_final_timing_exclusions.json"
exclusions=load(exclusion_path)
assert len(exclusions["exclusions"])==128

batch=Path("data/public/metadata/g1_announcement_times_batch_0038.csv")
evidence_path=Path("data/public/metadata/g1_public_batch_0038_evidence.json")
assert not batch.exists() and not evidence_path.exists()

specs=[
{"event_id":"HEJFE-7CA38C1FDA5EA4D0","historical_symbol":"CENX","expected_trade":"2013-04-25 15:22:00",
 "clock":"2013-04-25T16:00:00-04:00","publisher_timestamp_text":"2013-04-25T20:00:00Z",
 "release_title":"Century Reports First Quarter 2013 Results",
 "source_reference":"https://finance.yahoo.com/news/century-reports-first-quarter-2013-200000479.html",
 "corroboration_reference":"https://www.globenewswire.com/news-release/2013/04/26/541953/0/is/files/253109/0/CENTURYALUMINUM_8K_20130425.pdf",
 "corroboration_basis":"Yahoo preserves the original Marketwired release with published_date 2013-04-25T20:00:00Z; the filed 8-K/Exhibit 99.1 independently matches Century Aluminum, April 25 2013, first-quarter results and $321.3 million sales. The 5:00pm conference call is not used.",
 "expected_delta":2280},
{"event_id":"HEJFE-9527526FED86FA7D","historical_symbol":"EHTH","expected_trade":"2013-04-25 15:56:00",
 "clock":"2013-04-25T16:15:00-04:00","publisher_timestamp_text":"2013-04-25T20:15:00Z",
 "release_title":"eHealth, Inc. Announces First Quarter 2013 Results",
 "source_reference":"https://finance.yahoo.com/news/ehealth-inc-announces-first-quarter-201500765.html",
 "corroboration_reference":"https://www.sec.gov/Archives/edgar/data/1333493/000133349313000042/ehth-20130425ex991843dc3.htm",
 "corroboration_basis":"Yahoo preserves the original Marketwired release with published_date 2013-04-25T20:15:00Z; SEC Exhibit 99.1 independently matches eHealth, April 25 2013, first-quarter results and $43.2 million revenue. The 5:00pm conference call is not used.",
 "expected_delta":1140},
{"event_id":"HEJFE-8536AD777ECEEACB","historical_symbol":"GDI","expected_trade":"2013-04-25 15:17:00",
 "clock":"2013-04-26T09:44:00-04:00","publisher_timestamp_text":"Published on 04/26/2013 at 09:44 am EDT",
 "release_title":"Gardner Denver Reports First Quarter 2013 Results",
 "source_reference":"https://www.marketscreener.com/quote/stock/GARDNER-DENVER-INC-12725/news/Gardner-Denver-Inc-Gardner-Denver-Reports-First-Quarter-2013-Results-16778829/",
 "corroboration_reference":"https://www.sec.gov/Archives/edgar/data/916459/000119312513178171/d527260dex991.htm",
 "corroboration_basis":"MarketScreener preserves the Marketwired release and explicit 09:44am EDT publication clock; SEC Exhibit 99.1 independently matches Gardner Denver, April 26 2013, first-quarter results and $513.5 million revenue.",
 "expected_delta":66420}
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
    trial["validation_probes"].append(dict(item,probe_id=f"{spec['historical_symbol']}-batch0038",historical_event_match=True,
      exact_clock_observed=True,exact_public_release_ts=release.isoformat(),evidence_eligible=True))
research.validate_research_map(trial,exclusions)

fields=["event_id","historical_symbol","event_date","public_announcement_ts","timestamp_kind","source_grade","source_reference"]
s=io.StringIO(newline="");w=csv.DictWriter(s,fieldnames=fields,lineterminator="\n");w.writeheader()
for x in items:w.writerow({k:x[k] for k in fields})
batch.write_text(s.getvalue(),encoding="utf-8")
save(evidence_path,{"schema_version":"1","research_use_only":True,"base_main_sha":BASE,"batch_path":str(batch),"batch_sha256":sha(batch),
"items":items,"previous_exact_count":46,"expected_exact_count_after_batch":49,"expected_excluded_after_batch":125,
"previous_exact_timestamps":{k:r["public_announcement_ts"] for k,r in old_exact.items()},
"evidence_method":"Date-cluster recovery: two Yahoo-preserved Marketwired timestamps plus one MarketScreener-preserved Marketwired clock, each independently corroborated by issuer/SEC-filed release evidence. CI verifies chronology, event identity and deterministic receipts.",
"prohibited_substitutes":["edgar_acceptance_time","scheduled_call_time","archive_capture_time","inferred_clock","date_only"]})

ids={x["event_id"] for x in items}
exclusions["exclusions"]=[r for r in exclusions["exclusions"] if r["event_id"] not in ids]
exclusions["base_main_sha"]=BASE
exclusions["g1_state"].update(exact_resolved=49,reviewed_excluded=125,raw_exact_time_evidence_gaps=125,exact_timing_analysis_eligible=49)
save(exclusion_path,exclusions)

contract_path=Path("config/metadata_sources.public_progress.json");contract=load(contract_path)
contract["sources"].insert(0,{"source_id":"public-marketwired-cenx-ehth-gdi-batch-0038","record_kind":"announcement_timestamp",
"source_family":"official_newswire_archive","path":str(batch),"enabled":True,"authorized":True,"data_classification":"public_official_data",
"delimiter":",","encoding":"utf-8","timezone":"America/New_York","column_map":{k:k for k in fields},
"license_reference":"Public Yahoo/MarketScreener-preserved Marketwired publication metadata for Century Aluminum, eHealth and Gardner Denver with independent SEC/issuer release corroboration. No licensed vendor data used.",
"notes":"CENX 2013-04-25 16:00 EDT; EHTH 2013-04-25 16:15 EDT; GDI 2013-04-26 09:44 EDT. Conference-call and EDGAR acceptance clocks are not used."})
contract["reviewed_announcement_exclusions"].update(expected_count=125,expected_sha256=sha(exclusion_path))
contract["purpose"]="Cumulative public point-in-time metadata: G1 has 49 exact release timestamps and 125 reviewed fail-closed exclusions; exact-timing and all independent non-synthetic release locks remain fail-closed."
save(contract_path,contract)

hints["base_main_sha"]=BASE
hints["current_g1_state"].update(public_exact_batch_count=38,exact_resolved_event_records=49,reviewed_excluded_event_records=125,
 note="The repository is at batch_0038; cumulative exact event records are 49 because some public batches resolve more than one historical event.")
for item in items:
    hints["validation_probes"].append(dict(item,probe_id=f"{item['historical_symbol']}-batch0037",historical_event_match=True,
      exact_clock_observed=True,exact_public_release_ts=item["public_announcement_ts"],evidence_eligible=False,
      disposition="RESOLVED_IN_BATCH_0038",reason="Promoted through reviewed preserved-wire evidence with SEC corroboration."))
save(hints_path,hints)

assert rebuild.rebuild(ROOT,publish=True)["after"]["up_to_date"]
fresh=rows(md/"announcement_resolutions.csv");by={r["event_id"]:r for r in fresh};assert len(by)==174
for eid,old in old_exact.items():assert by[eid]==old
expected={"HEJFE-7CA38C1FDA5EA4D0":"2013-04-25T20:00:00Z","HEJFE-9527526FED86FA7D":"2013-04-25T20:15:00Z","HEJFE-8536AD777ECEEACB":"2013-04-26T13:44:00Z"}
for item in items:
    r=by[item["event_id"]];assert r["resolution_status"]=="resolved_exact_public_timestamp" and r["public_announcement_ts"]==expected[item["event_id"]]
excluded=[r for r in fresh if r["resolution_status"]=="excluded_fail_closed"]
assert len(excluded)==125 and all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in excluded)
ready=load(md/"metadata_readiness_summary.json");assert ready["announcement_exact_resolved"]==49 and ready["announcement_events_excluded"]==125
assert ready["ready_g1_exact_timing_analysis"] is False

acq=Path("data/public/metadata/g1_acquisition_manifest.json");acq.write_text(acquisition.render_manifest(acquisition.build_manifest()),encoding="utf-8")
sd=Path("data/processed/real_data_release_sprint");cp=Path("data/processed/coverage_plan_real/coverage_summary.json")
sprint.refresh_coverage(coverage_summary_path=cp,metadata_readiness_path=md/"metadata_readiness_summary.json",
 metadata_quality_path=md/"metadata_quality_summary.json",requirements_manifest_path=sd/"requirements_manifest.json",
 unresolved_gates_path=cp.parent/"unresolved_gates.csv")
status=sprint.build_status(requirements_manifest_path=sd/"requirements_manifest.json",coverage_summary_path=cp,
 metadata_readiness_path=md/"metadata_readiness_summary.json",metadata_quality_path=md/"metadata_quality_summary.json",outpath=sd/"step_status.json")
step9=next(x for x in status["steps"] if x["step"]==9);assert step9["status"]=="SOURCE_BLOCKED" and "49/174" in step9["evidence"] and "125" in step9["evidence"]

for fn in ["tests/test_g1_source_research.py","tests/test_g1_acquisition_manifest.py","tests/test_real_data_release_sprint.py",
"tests/test_g1_public_batch_0032.py","tests/test_g1_public_batch_0034.py","tests/test_g1_public_batch_0035.py","tests/test_g1_public_batch_0036.py","tests/test_g1_public_batch_0037.py"]:
    p=Path(fn);t=p.read_text()
    t=t.replace("== (46,128)","== (49,125)").replace("len(excluded)==128","len(excluded)==125").replace("len(excluded) == 128","len(excluded) == 125").replace("len(ex)==128","len(ex)==125")
    t=t.replace('"46/174" in step9["evidence"] and "128" in step9["evidence"]','"49/174" in step9["evidence"] and "125" in step9["evidence"]')
    t=t.replace('updated["missing_exact_announcement_timestamps"] == 128','updated["missing_exact_announcement_timestamps"] == 125')
    t=re.sub(r"== 46\b","== 49",t);t=re.sub(r"== 128\b","== 125",t)
    if fn.endswith("test_g1_source_research.py"):t=t.replace('state["public_exact_batch_count"] == 37','state["public_exact_batch_count"] == 38')
    ast.parse(t);p.write_text(t)

p=Path("docs/g1_announcement_times.md");t=p.read_text().replace("37 public exact-time batches / 46 exact-resolved","38 public exact-time batches / 49 exact-resolved")
t += """
### Batch 0038: Century Aluminum + eHealth + Gardner Denver

A clustered 2013-04-25 sweep recovered Century Aluminum at 2013-04-25 20:00 UTC, eHealth at 2013-04-25 20:15 UTC, and Gardner Denver at 2013-04-26 13:44 UTC. Yahoo/MarketScreener preserve the Marketwired publication clocks and independent SEC/issuer releases corroborate all three. The clocks are 2,280, 1,140, and 66,420 seconds after the frozen first trades. This advances G1 from 46 exact / 128 reviewed exclusions to 49 exact / 125 reviewed exclusions. Scheduled calls, EDGAR acceptance and inferred clocks remain prohibited substitutes. Step 9 remains SOURCE_BLOCKED.
""";p.write_text(t)

tp=Path("tests/test_g1_public_batch_0038.py")
ts='''import csv,json,hashlib
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
def rr(p):
    with p.open(newline="",encoding="utf-8") as h:return list(csv.DictReader(h))
def test_batch_0038():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0038_evidence.json").read_text())
    events={r["event_id"]:r for r in rr(ROOT/"data/processed/historical_events.csv")}
    resolved={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    exp={"HEJFE-7CA38C1FDA5EA4D0":("CENX","2013-04-25T20:00:00Z",2280),"HEJFE-9527526FED86FA7D":("EHTH","2013-04-25T20:15:00Z",1140),"HEJFE-8536AD777ECEEACB":("GDI","2013-04-26T13:44:00Z",66420)}
    assert len(d["items"])==3
    for x in d["items"]:
        sym,utc,delta=exp[x["event_id"]];e=events[x["event_id"]]
        tr=datetime.fromisoformat(e["first_documented_illicit_trade_ts"]).replace(tzinfo=ZoneInfo("America/New_York"));rel=datetime.fromisoformat(x["public_announcement_ts"])
        assert e["historical_symbol"]==sym and tr<rel<=tr+timedelta(days=7) and int((rel-tr).total_seconds())==delta
        assert resolved[x["event_id"]]["public_announcement_ts"]==utc and x["corroboration_reference"].startswith("https://")
def test_batch_0038_preserves_prior():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0038_evidence.json").read_text())
    assert hashlib.sha256((ROOT/d["batch_path"]).read_bytes()).hexdigest()==d["batch_sha256"]
    by={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    for eid,ts in d["previous_exact_timestamps"].items():assert by[eid]["public_announcement_ts"]==ts
    ex=[r for r in by.values() if r["resolution_status"]=="excluded_fail_closed"];assert len(ex)==125
    assert all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in ex)
'''
ast.parse(ts);tp.write_text(ts)
assert rebuild.rebuild(ROOT,publish=False)["before"]["up_to_date"]

changed=set(subprocess.check_output(["git","diff","--name-only",BASE],text=True).splitlines());changed.update([str(batch),str(evidence_path),str(tp),SCRIPT])
permitted={WORKFLOW,SCRIPT,str(contract_path),str(exclusion_path),str(hints_path),str(acq),str(batch),str(evidence_path),str(tp),
"docs/g1_announcement_times.md","tests/test_g1_source_research.py","tests/test_g1_acquisition_manifest.py","tests/test_real_data_release_sprint.py",
"tests/test_g1_public_batch_0032.py","tests/test_g1_public_batch_0034.py","tests/test_g1_public_batch_0035.py","tests/test_g1_public_batch_0036.py","tests/test_g1_public_batch_0037.py",
str(cp),str(cp.parent/"unresolved_gates.csv"),str(sd/"step_status.json"),"data/processed/research_receipt_bundle.json",
"data/processed/real_data_replay/real_data_replay_status.json"} | {str(md/name) for name in rebuild.METADATA_RECEIPTS}
assert changed<=permitted,f"Unexpected {changed-permitted}"
allowp=Path("config/release_drift_allowlist.json");allow=load(allowp);reason="G1 batch 0038 clustered recovery for Century Aluminum, eHealth and Gardner Denver; deterministic 49 exact / 125 reviewed exclusions with independent corroboration."
for name in sorted(changed):
    sec="intentional_release_modifications" if name in allow["intentional_release_modifications"] else "repository_additions"
    allow[sec][name]={"expected_sha256":sha(name),"reason":reason}
save(allowp,allow);changed.add(str(allowp));subprocess.run(["git","add","--",*sorted(changed)],check=True)
audit=Path("private_runtime/audit/g1-batch-0038");audit.mkdir(parents=True,exist_ok=True)
save(audit/"verification.json",{"base_main_sha":BASE,"source_head_sha":os.environ["GITHUB_SHA"],"exact":49,"reviewed_excluded":125,
"previous_exact_preserved":46,"new_events":items,"step9":"SOURCE_BLOCKED","evaluation_release_permitted":False,"deterministic_rebuild_matches":True})
print(json.dumps({"exact":49,"reviewed_excluded":125,"new_events":[x["event_id"] for x in items]},indent=2))
