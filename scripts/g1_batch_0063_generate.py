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
BASE="7a1ff5e583ef27f2fd20517d7bd0398f2f2bf7b8"
WORKFLOW=".github/workflows/g1-public-batch-0063-worker-3.yml"
SCRIPT="scripts/g1_batch_0063_generate.py"
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
assert len(events)==174 and len(old_exact)==80
exclusion_path=md/"g1_final_timing_exclusions.json"
exclusions=load(exclusion_path)
assert len(exclusions["exclusions"])==94

batch=Path("data/public/metadata/g1_announcement_times_batch_0063.csv")
evidence_path=Path("data/public/metadata/g1_public_batch_0063_evidence.json")
assert not batch.exists() and not evidence_path.exists()

specs=[
{"event_id":"HEJFE-F9E72EEF6E5BD373","historical_symbol":"NATI","expected_trade":"2015-01-29 15:51:00",
 "clock":"2015-01-29T16:01:00-05:00","publisher_timestamp_text":"Published on 01/29/2015 at 04:01 pm EST",
 "release_title":"National Instruments Reports Record Revenue and Net Income for 2014",
 "source_reference":"https://www.marketscreener.com/quote/stock/NATIONAL-INSTRUMENTS-CORP-10156/news/National-Instruments-Reports-Record-Revenue-and-Net-Income-for-2014-19785765/",
 "corroboration_reference":"https://www.sec.gov/Archives/edgar/data/935494/000093549415000002/ex99-1.htm",
 "corroboration_basis":"MarketScreener's timestamp-preserving Business Wire mirror explicitly distinguishes Published on 01/29/2015 at 04:01 pm EST from a 04:03 pm modification time on the exact National Instruments 2014 results release; SEC Exhibit 99.1 independently matches National Instruments Corporation, the release title/date, reporting period, and results. The separately stated 4:00 p.m. CT conference call is not used.",
 "expected_delta":600},
{"event_id":"HEJFE-D35C7804C2F5326C","historical_symbol":"CREE","expected_trade":"2015-04-21 15:29:00",
 "clock":"2015-04-21T16:01:00-04:00","publisher_timestamp_text":"Published on 04/21/2015 at 04:01 pm EDT",
 "release_title":"Cree Reports Financial Results for the Third Quarter of Fiscal Year 2015",
 "source_reference":"https://www.marketscreener.com/quote/stock/WOLFSPEED-INC-8892/news/Cree-Reports-Financial-Results-for-the-Third-Quarter-of-Fiscal-Year-2015-20231088/",
 "corroboration_reference":"https://www.sec.gov/Archives/edgar/data/895419/000089541915000024/ex9913qfy2015.htm",
 "corroboration_basis":"MarketScreener's timestamp-preserving Business Wire mirror explicitly distinguishes Published on 04/21/2015 at 04:01 pm EDT from a 04:02 pm modification time on the exact Cree fiscal-2015 third-quarter release; SEC Exhibit 99.1 independently matches Cree, Inc., the release title/date, reporting period, and results. The separately stated 5:00 p.m. conference call is not used.",
 "expected_delta":1920}
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
      "corroboration_basis":spec["corroboration_basis"],"reviewed_on":"2026-09-30","information_asymmetry_seconds":delta}
    items.append(item)
    trial["validation_probes"].append(dict(item,probe_id=f"{spec['historical_symbol']}-batch0063",historical_event_match=True,
      exact_clock_observed=True,exact_public_release_ts=release.isoformat(),evidence_eligible=True))
research.validate_research_map(trial,exclusions)

fields=["event_id","historical_symbol","event_date","public_announcement_ts","timestamp_kind","source_grade","source_reference"]
s=io.StringIO(newline="");w=csv.DictWriter(s,fieldnames=fields,lineterminator="\n");w.writeheader()
for x in items:w.writerow({k:x[k] for k in fields})
batch.write_text(s.getvalue(),encoding="utf-8")
save(evidence_path,{"schema_version":"1","research_use_only":True,"base_main_sha":BASE,"batch_path":str(batch),"batch_sha256":sha(batch),
"items":items,"previous_exact_count":80,"expected_exact_count_after_batch":82,"expected_excluded_after_batch":92,
"previous_exact_timestamps":{k:r["public_announcement_ts"] for k,r in old_exact.items()},
"evidence_method":"Two timestamp-preserving MarketScreener mirrors of Business Wire publication clocks for National Instruments and Cree with independent SEC issuer-release corroboration. CI verifies chronology, event identity and deterministic receipts; conference-call, EDGAR acceptance, archive-capture, scheduled-release, date-only and inferred times are not used.",
"prohibited_substitutes":["edgar_acceptance_time","scheduled_call_time","archive_capture_time","inferred_clock","date_only"]})

ids={x["event_id"] for x in items}
exclusions["exclusions"]=[r for r in exclusions["exclusions"] if r["event_id"] not in ids]
exclusions["base_main_sha"]=BASE
exclusions["g1_state"].update(exact_resolved=82,reviewed_excluded=92,raw_exact_time_evidence_gaps=92,exact_timing_analysis_eligible=82)
save(exclusion_path,exclusions)

contract_path=Path("config/metadata_sources.public_progress.json");contract=load(contract_path)
contract["sources"].insert(0,{"source_id":"public-marketscreener-businesswire-nati-cree-batch-0063","record_kind":"announcement_timestamp",
"source_family":"official_newswire_archive","path":str(batch),"enabled":True,"authorized":True,"data_classification":"public_official_data",
"delimiter":",","encoding":"utf-8","timezone":"America/New_York","column_map":{k:k for k in fields},
"license_reference":"Public timestamp-preserving MarketScreener mirrors of Business Wire publication clocks for National Instruments and Cree with independent SEC Exhibit 99.1 corroboration. No licensed vendor data used.",
"notes":"NATI 2015-01-29 16:01 EST; CREE 2015-04-21 16:01 EDT. Conference-call, EDGAR acceptance, archive-capture, scheduled-release, date-only and inferred times are not used."})
contract["reviewed_announcement_exclusions"].update(expected_count=92,expected_sha256=sha(exclusion_path))
contract["purpose"]="Cumulative public point-in-time metadata: G1 has 82 exact release timestamps and 92 reviewed fail-closed exclusions; exact-timing and all independent non-synthetic release locks remain fail-closed."
save(contract_path,contract)

hints["priority_events"]=[r for r in hints.get("priority_events",[]) if r.get("event_id") not in ids]
hints["base_main_sha"]=BASE
hints["current_g1_state"].update(public_exact_batch_count=55,exact_resolved_event_records=82,reviewed_excluded_event_records=92,
 note="The repository is at batch_0063; cumulative exact event records are 82 because some public batches resolve more than one historical event.")
for item in items:
    hints["validation_probes"].append(dict(item,probe_id=f"{item['historical_symbol']}-batch0063",historical_event_match=True,
      exact_clock_observed=True,exact_public_release_ts=item["public_announcement_ts"],evidence_eligible=False,
      disposition="RESOLVED_IN_BATCH_0063",reason="Promoted through timestamp-preserving MarketScreener Business Wire mirror evidence with SEC corroboration."))
save(hints_path,hints)

assert rebuild.rebuild(ROOT,publish=True)["after"]["up_to_date"]
fresh=rows(md/"announcement_resolutions.csv");by={r["event_id"]:r for r in fresh};assert len(by)==174
for eid,old in old_exact.items():assert by[eid]==old
expected={"HEJFE-F9E72EEF6E5BD373":"2015-01-29T21:01:00Z","HEJFE-D35C7804C2F5326C":"2015-04-21T20:01:00Z"}
for item in items:
    r=by[item["event_id"]];assert r["resolution_status"]=="resolved_exact_public_timestamp" and r["public_announcement_ts"]==expected[item["event_id"]]
excluded=[r for r in fresh if r["resolution_status"]=="excluded_fail_closed"]
assert len(excluded)==92 and all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in excluded)
ready=load(md/"metadata_readiness_summary.json");assert ready["announcement_exact_resolved"]==82 and ready["announcement_events_excluded"]==92
assert ready["ready_g1_exact_timing_analysis"] is False

acq=Path("data/public/metadata/g1_acquisition_manifest.json");acq.write_text(acquisition.render_manifest(acquisition.build_manifest()),encoding="utf-8")
sd=Path("data/processed/real_data_release_sprint");cp=Path("data/processed/coverage_plan_real/coverage_summary.json")
sprint.refresh_coverage(coverage_summary_path=cp,metadata_readiness_path=md/"metadata_readiness_summary.json",
 metadata_quality_path=md/"metadata_quality_summary.json",requirements_manifest_path=sd/"requirements_manifest.json",
 unresolved_gates_path=cp.parent/"unresolved_gates.csv")
status=sprint.build_status(requirements_manifest_path=sd/"requirements_manifest.json",coverage_summary_path=cp,
 metadata_readiness_path=md/"metadata_readiness_summary.json",metadata_quality_path=md/"metadata_quality_summary.json",outpath=sd/"step_status.json")
step9=next(x for x in status["steps"] if x["step"]==9);assert step9["status"]=="SOURCE_BLOCKED" and "82/174" in step9["evidence"] and "92" in step9["evidence"]

for fn in ["tests/test_g1_source_research.py","tests/test_g1_acquisition_manifest.py","tests/test_real_data_release_sprint.py",
"tests/test_g1_public_batch_0032.py","tests/test_g1_public_batch_0034.py","tests/test_g1_public_batch_0035.py","tests/test_g1_public_batch_0036.py","tests/test_g1_public_batch_0037.py","tests/test_g1_public_batch_0038.py","tests/test_g1_public_batch_0039.py","tests/test_g1_public_batch_0040.py","tests/test_g1_public_batch_0041.py","tests/test_g1_public_batch_0042.py","tests/test_g1_public_batch_0043.py","tests/test_g1_public_batch_0044.py","tests/test_g1_public_batch_0045.py","tests/test_g1_public_batch_0046.py","tests/test_g1_public_batch_0047.py","tests/test_g1_public_batch_0048.py","tests/test_g1_public_batch_0049.py","tests/test_g1_public_batch_0050.py","tests/test_g1_public_batch_0051.py","tests/test_g1_public_batch_0052.py","tests/test_g1_public_batch_0053.py","tests/test_g1_public_batch_0061.py"]:
    p=Path(fn);t=p.read_text()
    t=t.replace("== (80,94)","== (82,92)").replace("len(excluded)==94","len(excluded)==92").replace("len(excluded) == 94","len(excluded) == 92").replace("len(ex)==94","len(ex)==92")
    t=t.replace('"80/174" in step9["evidence"] and "94" in step9["evidence"]','"82/174" in step9["evidence"] and "92" in step9["evidence"]')
    t=t.replace('updated["missing_exact_announcement_timestamps"] == 94','updated["missing_exact_announcement_timestamps"] == 92')
    t=re.sub(r"== 80\b","== 82",t);t=re.sub(r"== 94\b","== 92",t)
    if fn.endswith("test_g1_source_research.py"):
        t=t.replace('state["public_exact_batch_count"] == 54','state["public_exact_batch_count"] == 55')
        t=t.replace('report["priority_event_count"] == 6','report["priority_event_count"] == 5')
        t=t.replace('assert [row["historical_symbol"] for row in report["queue"]] == [\n        "QLIK", "TNGO", "CAKE", "NKE", "NATI", "NATI"\n    ]','assert [row["historical_symbol"] for row in report["queue"]] == [\n        "QLIK", "TNGO", "CAKE", "NKE", "NATI"\n    ]')
    if fn.endswith("test_g1_acquisition_manifest.py"):
        t=t.replace('manifest["work_queue"][:6]] == [\n        "QLIK", "TNGO", "CAKE", "NKE", "NATI", "NATI"\n    ]','manifest["work_queue"][:5]] == [\n        "QLIK", "TNGO", "CAKE", "NKE", "NATI"\n    ]')
        t=t.replace('manifest["work_queue"][:6]] == [1, 2, 3, 4, 5, 6]','manifest["work_queue"][:5]] == [1, 2, 3, 4, 6]')
        t=t.replace('len(manifest["work_queue"]) == 94','len(manifest["work_queue"]) == 92')
        t=t.replace('len({row["dedupe_key"] for row in manifest["work_queue"]}) == 94','len({row["dedupe_key"] for row in manifest["work_queue"]}) == 92')
    ast.parse(t);p.write_text(t)

p=Path("docs/g1_announcement_times.md");t=p.read_text().replace("54 public exact-time batches / 80 exact-resolved","55 public exact-time batches / 82 exact-resolved")
t += """
### Batch 0063: National Instruments and Cree

Timestamp-preserving MarketScreener mirrors of the original Business Wire releases establish National Instruments' exact first-public clock at 2015-01-29 16:01 EST (21:01 UTC), 600 seconds after the frozen 15:51 EST trade, and Cree's exact first-public clock at 2015-04-21 16:01 EDT (20:01 UTC), 1,920 seconds after the frozen 15:29 EDT trade. Matching SEC Exhibits 99.1 independently corroborate each issuer, title, date, reporting period, and release body. Each mirror explicitly distinguishes the publication clock from a later modification time. This advances G1 from 80 exact / 94 reviewed exclusions to 82 exact / 92 reviewed exclusions. Conference-call, EDGAR acceptance, archive-capture, update, date-only, scheduled-release, and inferred clocks are not used. Step 9 remains SOURCE_BLOCKED.
""";p.write_text(t)

tp=Path("tests/test_g1_public_batch_0063.py")
ts='''import csv,json,hashlib
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
def rr(p):
    with p.open(newline="",encoding="utf-8") as h:return list(csv.DictReader(h))
def test_batch_0063():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0063_evidence.json").read_text())
    events={r["event_id"]:r for r in rr(ROOT/"data/processed/historical_events.csv")}
    resolved={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    exp={"HEJFE-F9E72EEF6E5BD373":("NATI","2015-01-29T21:01:00Z",600),"HEJFE-D35C7804C2F5326C":("CREE","2015-04-21T20:01:00Z",1920)}
    assert len(d["items"])==2
    for x in d["items"]:
        sym,utc,delta=exp[x["event_id"]];e=events[x["event_id"]]
        tr=datetime.fromisoformat(e["first_documented_illicit_trade_ts"]).replace(tzinfo=ZoneInfo("America/New_York"));rel=datetime.fromisoformat(x["public_announcement_ts"])
        assert e["historical_symbol"]==sym and tr<rel<=tr+timedelta(days=7) and int((rel-tr).total_seconds())==delta
        assert resolved[x["event_id"]]["public_announcement_ts"]==utc
        assert resolved[x["event_id"]]["resolution_status"]=="resolved_exact_public_timestamp"
        assert x["source_family"]=="preserved_wire_mirror" and x["source_grade"]=="B"
        assert x["corroboration_reference"].startswith("https://www.sec.gov/")
def test_batch_0063_preserves_prior():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0063_evidence.json").read_text())
    assert hashlib.sha256((ROOT/d["batch_path"]).read_bytes()).hexdigest()==d["batch_sha256"]
    by={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    for eid,ts in d["previous_exact_timestamps"].items():assert by[eid]["public_announcement_ts"]==ts
    ex=[r for r in by.values() if r["resolution_status"]=="excluded_fail_closed"];assert len(ex)==92
    assert all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in ex)
'''
ast.parse(ts);tp.write_text(ts)
assert rebuild.rebuild(ROOT,publish=False)["before"]["up_to_date"]

changed=set(subprocess.check_output(["git","diff","--name-only",BASE],text=True).splitlines());changed.update([str(batch),str(evidence_path),str(tp),SCRIPT])
permitted={WORKFLOW,SCRIPT,str(contract_path),str(exclusion_path),str(hints_path),str(acq),str(batch),str(evidence_path),str(tp),
"docs/g1_announcement_times.md","tests/test_g1_source_research.py","tests/test_g1_acquisition_manifest.py","tests/test_real_data_release_sprint.py",
"tests/test_g1_public_batch_0032.py","tests/test_g1_public_batch_0034.py","tests/test_g1_public_batch_0035.py","tests/test_g1_public_batch_0036.py","tests/test_g1_public_batch_0037.py","tests/test_g1_public_batch_0038.py","tests/test_g1_public_batch_0039.py","tests/test_g1_public_batch_0040.py","tests/test_g1_public_batch_0041.py","tests/test_g1_public_batch_0042.py","tests/test_g1_public_batch_0043.py","tests/test_g1_public_batch_0044.py","tests/test_g1_public_batch_0045.py","tests/test_g1_public_batch_0046.py","tests/test_g1_public_batch_0047.py","tests/test_g1_public_batch_0048.py","tests/test_g1_public_batch_0049.py","tests/test_g1_public_batch_0050.py","tests/test_g1_public_batch_0051.py","tests/test_g1_public_batch_0052.py","tests/test_g1_public_batch_0053.py","tests/test_g1_public_batch_0061.py",
str(cp),str(cp.parent/"unresolved_gates.csv"),str(sd/"step_status.json"),"data/processed/research_receipt_bundle.json",
"data/processed/real_data_replay/real_data_replay_status.json"} | {str(md/name) for name in rebuild.METADATA_RECEIPTS}
assert changed<=permitted,f"Unexpected {changed-permitted}"
allowp=Path("config/release_drift_allowlist.json");allow=load(allowp);reason="G1 batch 0063 timestamp-preserving MarketScreener Business Wire mirror clocks for National Instruments and Cree; deterministic 82 exact / 92 reviewed exclusions with SEC corroboration and prior evidence preserved."
for name in sorted(changed):
    sec="intentional_release_modifications" if name in allow["intentional_release_modifications"] else "repository_additions"
    allow[sec][name]={"expected_sha256":sha(name),"reason":reason}
save(allowp,allow);changed.add(str(allowp));subprocess.run(["git","add","--",*sorted(changed)],check=True)
audit=Path("private_runtime/audit/g1-batch-0063");audit.mkdir(parents=True,exist_ok=True)
save(audit/"verification.json",{"base_main_sha":BASE,"source_head_sha":os.environ["GITHUB_SHA"],"exact":82,"reviewed_excluded":92,
"previous_exact_preserved":80,"new_events":items,"step9":"SOURCE_BLOCKED","evaluation_release_permitted":False,"deterministic_rebuild_matches":True})
print(json.dumps({"exact":82,"reviewed_excluded":92,"new_events":[x["event_id"] for x in items]},indent=2))