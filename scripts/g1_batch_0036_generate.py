from __future__ import annotations
import ast, copy, csv, hashlib, io, json, os, re, subprocess
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import g1_source_research as research
import g1_acquisition_manifest as acquisition
import research_receipt_rebuild as rebuild
import real_data_release_sprint as sprint

ROOT=Path.cwd()
BASE="1692ee04dbd6beb715b9f2b8f5ec621713640368"
WORKFLOW=".github/workflows/g1-public-batch-0036.yml"
SCRIPT="scripts/g1_batch_0036_generate.py"

def load(path): return json.loads(Path(path).read_text(encoding="utf-8"))
def save(path,obj): Path(path).write_text(json.dumps(obj,indent=2,sort_keys=True)+"\n",encoding="utf-8")
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def rows(path):
    with Path(path).open(newline="",encoding="utf-8") as handle: return list(csv.DictReader(handle))

corpus=Path("data/processed/historical_events.csv")
assert sha(corpus)=="43fb221eed14c2a00a0e9d4531fe365dd264128625877a6cfc986cf50f862f12"
md=Path("data/processed/authorized_input_real")
events=rows(corpus)
old_exact={r["event_id"]:r for r in rows(md/"announcement_resolutions.csv") if r["resolution_status"]=="resolved_exact_public_timestamp"}
assert len(events)==174 and len(old_exact)==42
exclusion_path=md/"g1_final_timing_exclusions.json"
exclusions=load(exclusion_path)
assert len(exclusions["exclusions"])==132

batch=Path("data/public/metadata/g1_announcement_times_batch_0036.csv")
evidence_path=Path("data/public/metadata/g1_public_batch_0036_evidence.json")
assert not batch.exists() and not evidence_path.exists()

specs=[
{
"event_id":"HEJFE-489E74F74AFB5AFA","historical_symbol":"MCRL","expected_trade":"2013-04-25 14:32:00",
"clock":"2013-04-25T16:01:00-04:00","publisher_timestamp_text":"2013-04-25T20:01:00Z",
"release_title":"Micrel Reports 2013 First Quarter Financial Results",
"source_reference":"https://finance.yahoo.com/news/micrel-reports-2013-first-quarter-200100018.html",
"corroboration_reference":"https://www.sec.gov/Archives/edgar/data/932111/000093211113000020/exhibit991earningsrelease4.htm",
"corroboration_basis":"Yahoo preserves the original Marketwired release with published_date 2013-04-25T20:01:00Z; SEC Exhibit 99.1 independently matches Micrel, April 25 2013, first-quarter 2013 results and $59.7 million revenue. The 4:30pm conference call is not used.",
"expected_delta":5340},
{
"event_id":"HEJFE-E61095F8DC4132DE","historical_symbol":"JNPR","expected_trade":"2013-07-23 15:03:00",
"clock":"2013-07-23T16:05:00-04:00","publisher_timestamp_text":"2013-07-23T20:05:00Z",
"release_title":"Juniper Networks Reports Preliminary Second Quarter 2013 Financial Results and Announces Additional $1 Billion Share Repurchase Authorization",
"source_reference":"https://finance.yahoo.com/news/juniper-networks-reports-preliminary-second-200500973.html",
"corroboration_reference":"https://www.sec.gov/Archives/edgar/data/1043604/000119312513298913/d572332dex991.htm",
"corroboration_basis":"Yahoo preserves the original Marketwired release with published_date 2013-07-23T20:05:00Z; SEC Exhibit 99.1 independently matches Juniper, July 23 2013, second-quarter 2013 results and $1.151 billion revenue. The 5:00pm EDT conference call is not used.",
"expected_delta":3720},
{
"event_id":"HEJFE-8F17F6BEDF631C8B","historical_symbol":"MCRI","expected_trade":"2013-04-25 15:08:00",
"clock":"2013-04-25T16:05:00-04:00","publisher_timestamp_text":"2013-04-25T20:05:00Z",
"release_title":"Monarch Casino Reports 2013 First Quarter Results",
"source_reference":"https://finance.yahoo.com/news/monarch-casino-reports-2013-first-200500949.html",
"corroboration_reference":"https://www.sec.gov/Archives/edgar/data/907242/000110262413000482/monarchcasinoandresortinc.htm",
"corroboration_basis":"Yahoo preserves the original Marketwired release with published_date 2013-04-25T20:05:00Z; the SEC-filed release independently matches Monarch, April 25 2013 and first-quarter 2013 results. No later filing or inferred clock is used.",
"expected_delta":3420}
]

items=[]
hints_path=Path("data/public/metadata/g1_source_research_20260928.json")
hints=load(hints_path); trial=copy.deepcopy(hints)
for spec in specs:
    event=next(r for r in events if r["event_id"]==spec["event_id"])
    assert event["historical_symbol"]==spec["historical_symbol"]
    assert event["first_documented_illicit_trade_ts"]==spec["expected_trade"]
    assert spec["event_id"] not in old_exact
    assert sum(r["event_id"]==spec["event_id"] for r in exclusions["exclusions"])==1
    trade=datetime.fromisoformat(event["first_documented_illicit_trade_ts"]).replace(tzinfo=ZoneInfo("America/New_York"))
    release=datetime.fromisoformat(spec["clock"])
    assert trade < release <= trade+timedelta(days=7)
    delta=int((release-trade).total_seconds()); assert delta==spec["expected_delta"]
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
    items.append(item)
    trial["validation_probes"].append(dict(item,probe_id=f"{spec['historical_symbol']}-{spec['event_id'][-6:]}-batch0036",
      historical_event_match=True,exact_clock_observed=True,exact_public_release_ts=release.isoformat(),evidence_eligible=True))
research.validate_research_map(trial,exclusions)

fields=["event_id","historical_symbol","event_date","public_announcement_ts","timestamp_kind","source_grade","source_reference"]
out=io.StringIO(newline=""); w=csv.DictWriter(out,fieldnames=fields,lineterminator="\n"); w.writeheader()
for item in items: w.writerow({k:item[k] for k in fields})
batch.write_text(out.getvalue(),encoding="utf-8")
save(evidence_path,{
"schema_version":"1","research_use_only":True,"base_main_sha":BASE,"batch_path":str(batch),"batch_sha256":sha(batch),
"items":items,"previous_exact_count":42,"expected_exact_count_after_batch":45,"expected_excluded_after_batch":129,
"previous_exact_timestamps":{k:r["public_announcement_ts"] for k,r in old_exact.items()},
"evidence_method":"Three preserved Yahoo copies of original Marketwired earnings releases with exact published_date metadata and independent SEC-filed release corroboration. CI checks event identity, chronology, normalization and deterministic receipts.",
"prohibited_substitutes":["edgar_acceptance_time","scheduled_call_time","archive_capture_time","inferred_clock","date_only"]})

resolved_ids={x["event_id"] for x in items}
exclusions["exclusions"]=[r for r in exclusions["exclusions"] if r["event_id"] not in resolved_ids]
exclusions["base_main_sha"]=BASE
exclusions["g1_state"].update(exact_resolved=45,reviewed_excluded=129,raw_exact_time_evidence_gaps=129,exact_timing_analysis_eligible=45)
save(exclusion_path,exclusions)

contract_path=Path("config/metadata_sources.public_progress.json"); contract=load(contract_path)
contract["sources"].insert(0,{
"source_id":"public-marketwired-mcrl-jnpr-mcri-batch-0036","record_kind":"announcement_timestamp",
"source_family":"official_newswire_archive","path":str(batch),"enabled":True,"authorized":True,
"data_classification":"public_official_data","delimiter":",","encoding":"utf-8","timezone":"America/New_York",
"column_map":{k:k for k in fields},
"license_reference":"Public Yahoo-preserved Marketwired publication metadata for Micrel, Juniper and Monarch Casino, independently corroborated by SEC-filed issuer releases. No licensed vendor data used.",
"notes":"MCRL 2013-04-25 16:01 EDT; JNPR 2013-07-23 16:05 EDT; MCRI 2013-04-25 16:05 EDT. Conference-call and EDGAR acceptance clocks are not used."})
contract["reviewed_announcement_exclusions"].update(expected_count=129,expected_sha256=sha(exclusion_path))
contract["purpose"]="Cumulative public point-in-time metadata: G1 has 45 exact release timestamps and 129 reviewed fail-closed exclusions; exact-timing and all independent non-synthetic release locks remain fail-closed."
save(contract_path,contract)

hints["base_main_sha"]=BASE
hints["current_g1_state"].update(public_exact_batch_count=36,exact_resolved_event_records=45,reviewed_excluded_event_records=129,
 note="The repository is at batch_0036; cumulative exact event records are 45 because some public batches resolve more than one historical event.")
for item in items:
    hints["validation_probes"].append(dict(item,probe_id=f"{item['historical_symbol']}-{item['event_id'][-6:]}-batch0036",
      historical_event_match=True,exact_clock_observed=True,exact_public_release_ts=item["public_announcement_ts"],
      evidence_eligible=False,disposition="RESOLVED_IN_BATCH_0036",
      reason="Promoted through separately reviewed preserved-wire evidence with SEC corroboration. This research hint cannot resolve events by itself."))
save(hints_path,hints)

assert rebuild.rebuild(ROOT,publish=True)["after"]["up_to_date"]
fresh=rows(md/"announcement_resolutions.csv"); by_id={r["event_id"]:r for r in fresh}; assert len(by_id)==174
for old_id,old in old_exact.items(): assert by_id[old_id]==old
expected_utc={
"HEJFE-489E74F74AFB5AFA":"2013-04-25T20:01:00Z",
"HEJFE-E61095F8DC4132DE":"2013-07-23T20:05:00Z",
"HEJFE-8F17F6BEDF631C8B":"2013-04-25T20:05:00Z"}
for item in items:
    row=by_id[item["event_id"]]
    assert row["resolution_status"]=="resolved_exact_public_timestamp"
    assert row["public_announcement_ts"]==expected_utc[item["event_id"]]
    assert row["source_grade"]=="B"
    assert int(row["information_asymmetry_seconds"])==item["information_asymmetry_seconds"]
excluded=[r for r in fresh if r["resolution_status"]=="excluded_fail_closed"]
assert len(excluded)==129 and all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in excluded)
ready=load(md/"metadata_readiness_summary.json")
assert ready["announcement_exact_resolved"]==45 and ready["announcement_events_excluded"]==129
assert ready["ready_g1_exact_timing_analysis"] is False and ready["ready_for_non_synthetic_model_evaluation_metadata"] is False

acquisition_path=Path("data/public/metadata/g1_acquisition_manifest.json")
acquisition_path.write_text(acquisition.render_manifest(acquisition.build_manifest()),encoding="utf-8")
sd=Path("data/processed/real_data_release_sprint"); cp=Path("data/processed/coverage_plan_real/coverage_summary.json")
sprint.refresh_coverage(coverage_summary_path=cp,metadata_readiness_path=md/"metadata_readiness_summary.json",
 metadata_quality_path=md/"metadata_quality_summary.json",requirements_manifest_path=sd/"requirements_manifest.json",
 unresolved_gates_path=cp.parent/"unresolved_gates.csv")
status=sprint.build_status(requirements_manifest_path=sd/"requirements_manifest.json",coverage_summary_path=cp,
 metadata_readiness_path=md/"metadata_readiness_summary.json",metadata_quality_path=md/"metadata_quality_summary.json",
 outpath=sd/"step_status.json")
step9=next(r for r in status["steps"] if r["step"]==9)
assert step9["status"]=="SOURCE_BLOCKED" and "45/174" in step9["evidence"] and "129" in step9["evidence"]
assert not status["all_12_genuinely_complete"]

for filename in [
"tests/test_g1_source_research.py","tests/test_g1_acquisition_manifest.py","tests/test_real_data_release_sprint.py",
"tests/test_g1_public_batch_0032.py","tests/test_g1_public_batch_0034.py","tests/test_g1_public_batch_0035.py"]:
    p=Path(filename); txt=p.read_text()
    txt=txt.replace("== (42,132)","== (45,129)")
    txt=txt.replace("len(excluded)==132","len(excluded)==129").replace("len(excluded) == 132","len(excluded) == 129")
    txt=txt.replace('"42/174" in step9["evidence"] and "132" in step9["evidence"]',
                    '"45/174" in step9["evidence"] and "129" in step9["evidence"]')
    txt=txt.replace('updated["missing_exact_announcement_timestamps"] == 132',
                    'updated["missing_exact_announcement_timestamps"] == 129')
    txt=re.sub(r"== 42\b","== 45",txt); txt=re.sub(r"== 132\b","== 129",txt)
    if filename.endswith("test_g1_source_research.py"):
        txt=txt.replace('state["public_exact_batch_count"] == 35','state["public_exact_batch_count"] == 36')
    ast.parse(txt); p.write_text(txt)

p=Path("docs/g1_announcement_times.md")
txt=p.read_text().replace("35 public exact-time batches / 42 exact-resolved","36 public exact-time batches / 45 exact-resolved")
txt += """
### Batch 0036: Micrel + Juniper + Monarch Casino

Yahoo Finance preserves the original Marketwired publication metadata for Micrel at 2013-04-25 20:01 UTC, Juniper at 2013-07-23 20:05 UTC, and Monarch Casino at 2013-04-25 20:05 UTC. Matching SEC-filed issuer releases independently corroborate all three. These clocks are 5,340, 3,720 and 3,420 seconds after their frozen first trades respectively. This advances G1 from 42 exact / 132 reviewed exclusions to 45 exact / 129 reviewed exclusions. Conference-call times, EDGAR acceptance timestamps and inferred clocks remain prohibited substitutes. Step 9 remains SOURCE_BLOCKED.
"""
p.write_text(txt)

test_path=Path("tests/test_g1_public_batch_0036.py")
test_source='''from __future__ import annotations
import csv,hashlib,json
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
def rr(p):
    with p.open(newline="",encoding="utf-8") as h:return list(csv.DictReader(h))
def test_batch_0036_exact_clocks():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0036_evidence.json").read_text())
    events={r["event_id"]:r for r in rr(ROOT/"data/processed/historical_events.csv")}
    resolved={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    expected={
      "HEJFE-489E74F74AFB5AFA":("MCRL","2013-04-25T20:01:00Z",5340),
      "HEJFE-E61095F8DC4132DE":("JNPR","2013-07-23T20:05:00Z",3720),
      "HEJFE-8F17F6BEDF631C8B":("MCRI","2013-04-25T20:05:00Z",3420)}
    assert len(d["items"])==3
    for item in d["items"]:
        sym,utc,delta=expected[item["event_id"]]
        e=events[item["event_id"]]
        trade=datetime.fromisoformat(e["first_documented_illicit_trade_ts"]).replace(tzinfo=ZoneInfo("America/New_York"))
        release=datetime.fromisoformat(item["public_announcement_ts"])
        assert e["historical_symbol"]==sym and trade < release <= trade+timedelta(days=7)
        assert int((release-trade).total_seconds())==delta
        assert resolved[item["event_id"]]["public_announcement_ts"]==utc
        assert resolved[item["event_id"]]["resolution_status"]=="resolved_exact_public_timestamp"
        assert item["corroboration_reference"].startswith("https://www.sec.gov/")
def test_batch_0036_preserves_prior_and_fail_closed_remainder():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0036_evidence.json").read_text())
    assert hashlib.sha256((ROOT/d["batch_path"]).read_bytes()).hexdigest()==d["batch_sha256"]
    by={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    for eid,ts in d["previous_exact_timestamps"].items():
        assert by[eid]["public_announcement_ts"]==ts and by[eid]["resolution_status"]=="resolved_exact_public_timestamp"
    excluded=[r for r in by.values() if r["resolution_status"]=="excluded_fail_closed"]
    assert len(excluded)==129
    assert all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in excluded)
'''
ast.parse(test_source); test_path.write_text(test_source)
assert rebuild.rebuild(ROOT,publish=False)["before"]["up_to_date"]

changed=set(subprocess.check_output(["git","diff","--name-only",BASE],text=True).splitlines())
changed.update([str(batch),str(evidence_path),str(test_path),SCRIPT])
permitted={WORKFLOW,SCRIPT,str(contract_path),str(exclusion_path),str(hints_path),str(acquisition_path),
 str(batch),str(evidence_path),str(test_path),"docs/g1_announcement_times.md","tests/test_g1_source_research.py",
 "tests/test_g1_acquisition_manifest.py","tests/test_real_data_release_sprint.py","tests/test_g1_public_batch_0032.py",
 "tests/test_g1_public_batch_0034.py","tests/test_g1_public_batch_0035.py",str(cp),str(cp.parent/"unresolved_gates.csv"),
 str(sd/"step_status.json"),"data/processed/research_receipt_bundle.json","data/processed/real_data_replay/real_data_replay_status.json"} | {str(md/name) for name in rebuild.METADATA_RECEIPTS}
assert changed <= permitted, f"Unexpected changes: {changed-permitted}"

allowpath=Path("config/release_drift_allowlist.json"); allow=load(allowpath)
reason="G1 batch 0036: Micrel, Juniper and Monarch preserved Marketwired timestamps; deterministic 45 exact / 129 reviewed exclusions with SEC corroboration and all prior exact evidence preserved."
for name in sorted(changed):
    section="intentional_release_modifications" if name in allow["intentional_release_modifications"] else "repository_additions"
    allow[section][name]={"expected_sha256":sha(name),"reason":reason}
save(allowpath,allow); changed.add(str(allowpath))
subprocess.run(["git","add","--",*sorted(changed)],check=True)

audit=Path("private_runtime/audit/g1-batch-0036"); audit.mkdir(parents=True,exist_ok=True)
save(audit/"verification.json",{"base_main_sha":BASE,"source_head_sha":os.environ["GITHUB_SHA"],"exact":45,
"reviewed_excluded":129,"previous_exact_preserved":42,"new_events":items,"step9":"SOURCE_BLOCKED",
"evaluation_release_permitted":False,"deterministic_rebuild_matches":True,
"tracked_change_sha256":{name:sha(name) for name in sorted(changed)}})
print(json.dumps({"exact":45,"reviewed_excluded":129,"new_events":[x["event_id"] for x in items],"step9":"SOURCE_BLOCKED"},indent=2))
