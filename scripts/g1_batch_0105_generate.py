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
BASE="41e07137b5aeb3b4765b5d8d350fb4f66aa4ce28"
WORKFLOW=".github/workflows/g1-public-batch-0105-worker-0.yml"
SCRIPT="scripts/g1_batch_0105_generate.py"
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
assert len(events)==174 and len(old_exact)==137
exclusion_path=md/"g1_final_timing_exclusions.json"
exclusions=load(exclusion_path)
assert len(exclusions["exclusions"])==37

batch=Path("data/public/metadata/g1_announcement_times_batch_0105.csv")
evidence_path=Path("data/public/metadata/g1_public_batch_0105_evidence.json")
assert not batch.exists() and not evidence_path.exists()

specs=[
  {
    "event_id": "HEJFE-7F8218B15679F14D",
    "historical_symbol": "NATI",
    "expected_trade": "2015-04-28 13:59:00",
    "clock": "2015-04-28T16:02:00-04:00",
    "explicit_release_clock_text": "Filed GX 8002 explicitly records NATI Press Release / Distribution Time 2015-04-28 16:02:00-04:00 Eastern",
    "release_title": "Exact target release preserved as 2015/QTR2/81501_20150428_0.txt",
    "source_reference": "https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf",
    "corroboration_reference": "https://github.com/vgreg/hacked_earnings_jfe",
    "corroboration_basis": "Pinned exact event/date press-release member 2015/QTR2/81501_20150428_0.txt at source commit c23c7d79d067a79d70cf20e31b072d3703497eae corroborates identity.",
    "timestamp_evidence_kind": "explicit_release_clock",
    "source_family": "federal_court_public_distribution_record",
    "source_grade": "A",
    "public_distribution_explicit": True,
    "expected_delta": 7380,
    "court_docket_reference": "https://www.courtlistener.com/docket/4324653/united-states-v-korchevsky/",
    "gx8002_row_id": "mapped-NATI",
    "wire_source_code": "",
    "corroborating_release_member_path": "2015/QTR2/81501_20150428_0.txt"
  },
  {
    "event_id": "HEJFE-45559DD90D876D39",
    "historical_symbol": "ILMN",
    "expected_trade": "2015-04-21 14:48:00",
    "clock": "2015-04-21T16:05:00-04:00",
    "explicit_release_clock_text": "Filed GX 8002 explicitly records ILMN Press Release / Distribution Time 2015-04-21 16:05:00-04:00 Eastern",
    "release_title": "Exact target release preserved as 2015/QTR2/88446_20150421_0.txt",
    "source_reference": "https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf",
    "corroboration_reference": "https://github.com/vgreg/hacked_earnings_jfe",
    "corroboration_basis": "Pinned exact event/date press-release member 2015/QTR2/88446_20150421_0.txt at source commit c23c7d79d067a79d70cf20e31b072d3703497eae corroborates identity.",
    "timestamp_evidence_kind": "explicit_release_clock",
    "source_family": "federal_court_public_distribution_record",
    "source_grade": "A",
    "public_distribution_explicit": True,
    "expected_delta": 4620,
    "court_docket_reference": "https://www.courtlistener.com/docket/4324653/united-states-v-korchevsky/",
    "gx8002_row_id": "mapped-ILMN",
    "wire_source_code": "",
    "corroborating_release_member_path": "2015/QTR2/88446_20150421_0.txt"
  },
  {
    "event_id": "HEJFE-D6AE4ACB99958A73",
    "historical_symbol": "SGEN",
    "expected_trade": "2015-04-30 14:18:00",
    "clock": "2015-04-30T16:02:00-04:00",
    "explicit_release_clock_text": "Filed GX 8002 explicitly records SGEN Press Release / Distribution Time 2015-04-30 16:02:00-04:00 Eastern",
    "release_title": "Exact target release preserved as 2015/QTR2/88949_20150430_0.txt",
    "source_reference": "https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf",
    "corroboration_reference": "https://github.com/vgreg/hacked_earnings_jfe",
    "corroboration_basis": "Pinned exact event/date press-release member 2015/QTR2/88949_20150430_0.txt at source commit c23c7d79d067a79d70cf20e31b072d3703497eae corroborates identity.",
    "timestamp_evidence_kind": "explicit_release_clock",
    "source_family": "federal_court_public_distribution_record",
    "source_grade": "A",
    "public_distribution_explicit": True,
    "expected_delta": 6240,
    "court_docket_reference": "https://www.courtlistener.com/docket/4324653/united-states-v-korchevsky/",
    "gx8002_row_id": "mapped-SGEN",
    "wire_source_code": "",
    "corroborating_release_member_path": "2015/QTR2/88949_20150430_0.txt"
  },
  {
    "event_id": "HEJFE-5408AADD0CBD54E8",
    "historical_symbol": "CMP",
    "expected_trade": "2015-04-27 15:46:00",
    "clock": "2015-04-27T16:15:00-04:00",
    "explicit_release_clock_text": "Filed GX 8002 explicitly records CMP Press Release / Distribution Time 2015-04-27 16:15:00-04:00 Eastern",
    "release_title": "Exact target release preserved as 2015/QTR2/89952_20150427_0.txt",
    "source_reference": "https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf",
    "corroboration_reference": "https://github.com/vgreg/hacked_earnings_jfe",
    "corroboration_basis": "Pinned exact event/date press-release member 2015/QTR2/89952_20150427_0.txt at source commit c23c7d79d067a79d70cf20e31b072d3703497eae corroborates identity.",
    "timestamp_evidence_kind": "explicit_release_clock",
    "source_family": "federal_court_public_distribution_record",
    "source_grade": "A",
    "public_distribution_explicit": True,
    "expected_delta": 1740,
    "court_docket_reference": "https://www.courtlistener.com/docket/4324653/united-states-v-korchevsky/",
    "gx8002_row_id": "mapped-CMP",
    "wire_source_code": "",
    "corroborating_release_member_path": "2015/QTR2/89952_20150427_0.txt"
  },
  {
    "event_id": "HEJFE-93A7D27EF425EDF0",
    "historical_symbol": "MIC",
    "expected_trade": "2015-02-18 15:58:00",
    "clock": "2015-02-18T16:36:00-05:00",
    "explicit_release_clock_text": "Filed GX 8002 explicitly records MIC Press Release / Distribution Time 2015-02-18 16:36:00-05:00 Eastern",
    "release_title": "Exact target release preserved as 2015/QTR1/90507_20150218_0.txt",
    "source_reference": "https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf",
    "corroboration_reference": "https://github.com/vgreg/hacked_earnings_jfe",
    "corroboration_basis": "Pinned exact event/date press-release member 2015/QTR1/90507_20150218_0.txt at source commit c23c7d79d067a79d70cf20e31b072d3703497eae corroborates identity.",
    "timestamp_evidence_kind": "explicit_release_clock",
    "source_family": "federal_court_public_distribution_record",
    "source_grade": "A",
    "public_distribution_explicit": True,
    "expected_delta": 2280,
    "court_docket_reference": "https://www.courtlistener.com/docket/4324653/united-states-v-korchevsky/",
    "gx8002_row_id": "mapped-MIC",
    "wire_source_code": "",
    "corroborating_release_member_path": "2015/QTR1/90507_20150218_0.txt"
  },
  {
    "event_id": "HEJFE-20EC97300E6205B9",
    "historical_symbol": "INWK",
    "expected_trade": "2015-02-12 14:01:00",
    "clock": "2015-02-12T16:10:00-05:00",
    "explicit_release_clock_text": "Filed GX 8002 explicitly records INWK Press Release / Distribution Time 2015-02-12 16:10:00-05:00 Eastern",
    "release_title": "Exact target release preserved as 2015/QTR1/91432_20150212_0.txt",
    "source_reference": "https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf",
    "corroboration_reference": "https://github.com/vgreg/hacked_earnings_jfe",
    "corroboration_basis": "Pinned exact event/date press-release member 2015/QTR1/91432_20150212_0.txt at source commit c23c7d79d067a79d70cf20e31b072d3703497eae corroborates identity.",
    "timestamp_evidence_kind": "explicit_release_clock",
    "source_family": "federal_court_public_distribution_record",
    "source_grade": "A",
    "public_distribution_explicit": True,
    "expected_delta": 7740,
    "court_docket_reference": "https://www.courtlistener.com/docket/4324653/united-states-v-korchevsky/",
    "gx8002_row_id": "mapped-INWK",
    "wire_source_code": "",
    "corroborating_release_member_path": "2015/QTR1/91432_20150212_0.txt"
  },
  {
    "event_id": "HEJFE-B04F1AF8B6E30A43",
    "historical_symbol": "CLD",
    "expected_trade": "2015-02-17 15:35:00",
    "clock": "2015-02-17T16:10:00-05:00",
    "explicit_release_clock_text": "Filed GX 8002 explicitly records CLD Press Release / Distribution Time 2015-02-17 16:10:00-05:00 Eastern",
    "release_title": "Exact target release preserved as 2015/QTR1/93095_20150217_0.txt",
    "source_reference": "https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf",
    "corroboration_reference": "https://github.com/vgreg/hacked_earnings_jfe",
    "corroboration_basis": "Pinned exact event/date press-release member 2015/QTR1/93095_20150217_0.txt at source commit c23c7d79d067a79d70cf20e31b072d3703497eae corroborates identity.",
    "timestamp_evidence_kind": "explicit_release_clock",
    "source_family": "federal_court_public_distribution_record",
    "source_grade": "A",
    "public_distribution_explicit": True,
    "expected_delta": 2100,
    "court_docket_reference": "https://www.courtlistener.com/docket/4324653/united-states-v-korchevsky/",
    "gx8002_row_id": "mapped-CLD",
    "wire_source_code": "",
    "corroborating_release_member_path": "2015/QTR1/93095_20150217_0.txt"
  },
  {
    "event_id": "HEJFE-5D222F0F8E0C77D0",
    "historical_symbol": "TW",
    "expected_trade": "2015-05-04 15:47:00",
    "clock": "2015-05-05T06:00:00-04:00",
    "explicit_release_clock_text": "Filed GX 8002 explicitly records TW Press Release / Distribution Time 2015-05-05 06:00:00-04:00 Eastern",
    "release_title": "Exact target release preserved as 2015/QTR2/93223_20150505_0.txt",
    "source_reference": "https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf",
    "corroboration_reference": "https://github.com/vgreg/hacked_earnings_jfe",
    "corroboration_basis": "Pinned exact event/date press-release member 2015/QTR2/93223_20150505_0.txt at source commit c23c7d79d067a79d70cf20e31b072d3703497eae corroborates identity.",
    "timestamp_evidence_kind": "explicit_release_clock",
    "source_family": "federal_court_public_distribution_record",
    "source_grade": "A",
    "public_distribution_explicit": True,
    "expected_delta": 51180,
    "court_docket_reference": "https://www.courtlistener.com/docket/4324653/united-states-v-korchevsky/",
    "gx8002_row_id": "mapped-TW",
    "wire_source_code": "",
    "corroborating_release_member_path": "2015/QTR2/93223_20150505_0.txt"
  }
]
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
    trial["validation_probes"].append(dict(item,probe_id=f'{spec["historical_symbol"]}-batch0105',historical_event_match=True,
      exact_clock_observed=True,exact_public_release_ts=release.isoformat(),evidence_eligible=True))
research.validate_research_map(trial,exclusions)

fields=["event_id","historical_symbol","event_date","public_announcement_ts","timestamp_kind","source_grade","source_reference"]
s=io.StringIO(newline="");w=csv.DictWriter(s,fieldnames=fields,lineterminator="\n");w.writeheader()
for x in items:w.writerow({k:x[k] for k in fields})
batch.write_text(s.getvalue(),encoding="utf-8")
save(evidence_path,{"schema_version":"1","research_use_only":True,"base_main_sha":BASE,"batch_path":str(batch),"batch_sha256":sha(batch),
"items":items,"previous_exact_count":137,"expected_exact_count_after_batch":145,"expected_excluded_after_batch":29,
"previous_exact_timestamps":{k:r["public_announcement_ts"] for k,r in old_exact.items()},
"court_artifact":{
  "workflow_run_id": 37268374589,
  "artifact_id": 11326693734,
  "artifact_digest_sha256": "254e78dcb6218e3cd31cc9bf50a6ec639c966a037957629912af181432a6990e",
  "mapping_head_sha": "2592192e4fd38b14a021d36de7319db332379e38"
},
"evidence_method":"Filed federal-court GX 8002 explicitly records the press-release/public-distribution date and clock. Exact target identity/date is corroborated by PR #355's pinned public press-release archive mapping and official SEC Exhibit 99.x where available. Eastern offsets follow America/New_York date rules; BW/MW provider codes are not treated as timezones. CI verifies chronology, ownership, unresolved state and deterministic receipts. EDGAR acceptance, call/webcast, schedule, approximation, date-only, capture, neighboring-release and inferred clocks are not used.",
"prohibited_substitutes":["edgar_acceptance_time","scheduled_call_time","webcast_time","archive_capture_time","inferred_clock","date_only","neighboring_release"]})

ids={x["event_id"] for x in items}
exclusions["exclusions"]=[r for r in exclusions["exclusions"] if r["event_id"] not in ids]
exclusions["base_main_sha"]=BASE
exclusions["g1_state"].update(exact_resolved=145,reviewed_excluded=29,raw_exact_time_evidence_gaps=29,exact_timing_analysis_eligible=145)
save(exclusion_path,exclusions)

contract_path=Path("config/metadata_sources.public_progress.json");contract=load(contract_path)
contract["sources"].insert(0,{"source_id":"public-worker0-federal-court-gx8002-batch-0105","record_kind":"announcement_timestamp",
"source_family":"federal_court_public_distribution_record","path":str(batch),"enabled":True,"authorized":True,"data_classification":"public_official_data",
"delimiter":",","encoding":"utf-8","timezone":"America/New_York","column_map":{k:k for k in fields},
"license_reference":"Filed E.D.N.Y. GX 8002 Document 367-2 explicit press-release/public-distribution clocks, with exact release identity/date corroborated by pinned exact event/date public press-release members. No licensed vendor data used.",
"notes":"Eight exact first-public distribution clocks; prohibited substitute times are not used."})
contract["reviewed_announcement_exclusions"].update(expected_count=29,expected_sha256=sha(exclusion_path))
contract["purpose"]="Cumulative public point-in-time metadata: G1 has 145 exact release timestamps and 29 reviewed fail-closed exclusions; exact-timing and all independent non-synthetic release locks remain fail-closed."
save(contract_path,contract)

hints["priority_events"]=[r for r in hints.get("priority_events",[]) if r.get("event_id") not in ids]
hints["validation_probes"]=[r for r in hints.get("validation_probes",[]) if r.get("event_id") not in ids]
hints["base_main_sha"]=BASE
hints["current_g1_state"].update(public_exact_batch_count=82,exact_resolved_event_records=145,reviewed_excluded_event_records=29,
 note="The latest integrated recovery is batch_0105; cumulative public exact-time batches are 82 and cumulative exact event records are 145 because some public batches resolve more than one historical event.")
for item in items:
    hints["validation_probes"].append(dict(item,probe_id=f'{item["historical_symbol"]}-batch0105',historical_event_match=True,
      exact_clock_observed=True,exact_public_release_ts=item["public_announcement_ts"],evidence_eligible=False,
      disposition="RESOLVED_IN_BATCH_0105",reason="Promoted from filed federal-court GX 8002 explicit public-distribution clock with pinned pinned press-release identity corroboration."))
save(hints_path,hints)

assert rebuild.rebuild(ROOT,publish=True)["after"]["up_to_date"]
fresh=rows(md/"announcement_resolutions.csv");by={r["event_id"]:r for r in fresh};assert len(by)==174
for eid,old in old_exact.items():assert by[eid]==old
expected={item["event_id"]:datetime.fromisoformat(item["public_announcement_ts"]).astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00","Z") for item in items}
for item in items:
    r=by[item["event_id"]];assert r["resolution_status"]=="resolved_exact_public_timestamp" and r["public_announcement_ts"]==expected[item["event_id"]]
excluded=[r for r in fresh if r["resolution_status"]=="excluded_fail_closed"]
assert len(excluded)==29 and all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in excluded)
ready=load(md/"metadata_readiness_summary.json");assert ready["announcement_exact_resolved"]==145 and ready["announcement_events_excluded"]==29
assert ready["ready_g1_exact_timing_analysis"] is False

acq=Path("data/public/metadata/g1_acquisition_manifest.json");acq.write_text(acquisition.render_manifest(acquisition.build_manifest()),encoding="utf-8")
sd=Path("data/processed/real_data_release_sprint");cp=Path("data/processed/coverage_plan_real/coverage_summary.json")
sprint.refresh_coverage(coverage_summary_path=cp,metadata_readiness_path=md/"metadata_readiness_summary.json",
 metadata_quality_path=md/"metadata_quality_summary.json",requirements_manifest_path=sd/"requirements_manifest.json",
 unresolved_gates_path=cp.parent/"unresolved_gates.csv")
status=sprint.build_status(requirements_manifest_path=sd/"requirements_manifest.json",coverage_summary_path=cp,
 metadata_readiness_path=md/"metadata_readiness_summary.json",metadata_quality_path=md/"metadata_quality_summary.json",outpath=sd/"step_status.json")
step9=next(x for x in status["steps"] if x["step"]==9);assert step9["status"]=="SOURCE_BLOCKED" and "145/174" in step9["evidence"] and "29" in step9["evidence"]

test_files=["tests/test_g1_source_research.py","tests/test_g1_acquisition_manifest.py","tests/test_real_data_release_sprint.py",
*sorted(str(x) for x in Path("tests").glob("test_g1_public_batch_*.py"))]
for fn in test_files:
    p=Path(fn);txt=p.read_text()
    if fn.endswith("test_g1_source_research.py"):
        pairs=[('report["exact_resolved_event_records"] == 137','report["exact_resolved_event_records"] == 145'),
          ('report["reviewed_excluded_event_records"] == 37','report["reviewed_excluded_event_records"] == 29'),
          ('report["priority_event_count"] == 2','report["priority_event_count"] == 1'),
          ('"NKE", "NATI"','"NKE"'),
          ('state["public_exact_batch_count"] == 81','state["public_exact_batch_count"] == 82'),
          ('state["exact_resolved_event_records"] == 137','state["exact_resolved_event_records"] == 145')]
    elif fn.endswith("test_g1_acquisition_manifest.py"):
        pairs=[('manifest["state"]["exact_resolved"] == 137','manifest["state"]["exact_resolved"] == 145'),
          ('manifest["state"]["acquisition_needed"] == 37','manifest["state"]["acquisition_needed"] == 29'),
          ('len(manifest["work_queue"]) == 37','len(manifest["work_queue"]) == 29'),
          ('len({row["dedupe_key"] for row in manifest["work_queue"]}) == 37','len({row["dedupe_key"] for row in manifest["work_queue"]}) == 29'),
          ('len(resolved) == 137','len(resolved) == 145'),('len(unresolved) == 37','len(unresolved) == 29'),
          ('"NKE", "NATI", "VMW", "EW", "DGI"','"NKE", "VMW", "EW", "DGI", "PNRA"'),
          ('[4, 6, 1000, 1000, 1000]','[4, 1000, 1000, 1000, 1000]')]
    elif fn.endswith("test_real_data_release_sprint.py"):
        pairs=[('updated["missing_exact_announcement_timestamps"] == 37','updated["missing_exact_announcement_timestamps"] == 29')]
    else:
        pairs=[('(readiness["announcement_exact_resolved"],readiness["announcement_events_excluded"]) == (137,37)','(readiness["announcement_exact_resolved"],readiness["announcement_events_excluded"]) == (145,29)'),
          ('(readiness["announcement_exact_resolved"], readiness["announcement_events_excluded"]) == (137, 37)','(readiness["announcement_exact_resolved"], readiness["announcement_events_excluded"]) == (145, 29)'),
          ('"137/174" in step9["evidence"] and "37" in step9["evidence"]','"145/174" in step9["evidence"] and "29" in step9["evidence"]'),
          ('len(excluded)==37','len(excluded)==29'),('len(excluded) == 37','len(excluded) == 29'),
          ('len(ex)==37','len(ex)==29'),('len(ex) == 37','len(ex) == 29')]
    for old,new in pairs:txt=txt.replace(old,new)
    ast.parse(txt);p.write_text(txt)

p=Path("docs/g1_announcement_times.md");txt=p.read_text()
assert "81 public exact-time batches / 137 exact-resolved" in txt
txt=txt.replace("81 public exact-time batches / 137 exact-resolved","82 public exact-time batches / 145 exact-resolved",1)
txt += """
### Batch 0105: NATI, ILMN, SGEN, CMP, MIC, INWK, CLD, TW

Filed E.D.N.Y. GX 8002 Document 367-2 supplies explicit first-public press-release distribution clocks for eight Worker-0 events. Exact release identity/date is corroborated by pinned public press-release archive members and official SEC Exhibits 99.x. This advances G1 from 137 exact / 37 reviewed exclusions to 145 exact / 29 reviewed exclusions. Conference-call, EDGAR acceptance, archive-capture, date-only, scheduled-release and inferred clocks are not used. Step 9 remains SOURCE_BLOCKED.
""";p.write_text(txt)

tp=Path("tests/test_g1_public_batch_0105.py")
ts="import csv,json,hashlib\nfrom datetime import datetime,timedelta\nfrom pathlib import Path\nfrom zoneinfo import ZoneInfo\nROOT=Path(__file__).resolve().parents[1]\ndef rr(p):\n    with p.open(newline=\"\",encoding=\"utf-8\") as h:return list(csv.DictReader(h))\ndef test_batch_0105():\n    d=json.loads((ROOT/\"data/public/metadata/g1_public_batch_0105_evidence.json\").read_text())\n    events={r[\"event_id\"]:r for r in rr(ROOT/\"data/processed/historical_events.csv\")}\n    resolved={r[\"event_id\"]:r for r in rr(ROOT/\"data/processed/authorized_input_real/announcement_resolutions.csv\")}\n    exp={\"HEJFE-7F8218B15679F14D\":[\"NATI\",\"2015-04-28T20:02:00Z\",7380],\"HEJFE-45559DD90D876D39\":[\"ILMN\",\"2015-04-21T20:05:00Z\",4620],\"HEJFE-D6AE4ACB99958A73\":[\"SGEN\",\"2015-04-30T20:02:00Z\",6240],\"HEJFE-5408AADD0CBD54E8\":[\"CMP\",\"2015-04-27T20:15:00Z\",1740],\"HEJFE-93A7D27EF425EDF0\":[\"MIC\",\"2015-02-18T21:36:00Z\",2280],\"HEJFE-20EC97300E6205B9\":[\"INWK\",\"2015-02-12T21:10:00Z\",7740],\"HEJFE-B04F1AF8B6E30A43\":[\"CLD\",\"2015-02-17T21:10:00Z\",2100],\"HEJFE-5D222F0F8E0C77D0\":[\"TW\",\"2015-05-05T10:00:00Z\",51180]}\n    assert len(d[\"items\"])==8\n    for x in d[\"items\"]:\n        sym,utc,delta=exp[x[\"event_id\"]];e=events[x[\"event_id\"]]\n        tr=datetime.fromisoformat(e[\"first_documented_illicit_trade_ts\"]).replace(tzinfo=ZoneInfo(\"America/New_York\"));rel=datetime.fromisoformat(x[\"public_announcement_ts\"])\n        assert e[\"historical_symbol\"]==sym and tr<rel<=tr+timedelta(days=7) and int((rel-tr).total_seconds())==delta\n        assert resolved[x[\"event_id\"]][\"public_announcement_ts\"]==utc\n        assert resolved[x[\"event_id\"]][\"resolution_status\"]==\"resolved_exact_public_timestamp\"\n        assert x[\"source_family\"]==\"federal_court_public_distribution_record\" and x[\"source_grade\"]==\"A\"\n        assert x[\"timestamp_evidence_kind\"]==\"explicit_release_clock\" and x[\"public_distribution_explicit\"] is True\ndef test_batch_0105_preserves_prior():\n    d=json.loads((ROOT/\"data/public/metadata/g1_public_batch_0105_evidence.json\").read_text())\n    assert hashlib.sha256((ROOT/d[\"batch_path\"]).read_bytes()).hexdigest()==d[\"batch_sha256\"]\n    by={r[\"event_id\"]:r for r in rr(ROOT/\"data/processed/authorized_input_real/announcement_resolutions.csv\")}\n    for eid,stamp in d[\"previous_exact_timestamps\"].items():assert by[eid][\"public_announcement_ts\"]==stamp\n    ex=[r for r in by.values() if r[\"resolution_status\"]==\"excluded_fail_closed\"];assert len(ex)==29\ndef test_batch_0105_worker0_shard_ownership():\n    event_ids=set([\"HEJFE-7F8218B15679F14D\",\"HEJFE-45559DD90D876D39\",\"HEJFE-D6AE4ACB99958A73\",\"HEJFE-5408AADD0CBD54E8\",\"HEJFE-93A7D27EF425EDF0\",\"HEJFE-20EC97300E6205B9\",\"HEJFE-B04F1AF8B6E30A43\",\"HEJFE-5D222F0F8E0C77D0\"])\n    assert 105 >= 60 and (105-60) % 5 == 0\n    assert all(int(hashlib.sha256(eid.encode(\"utf-8\")).hexdigest(),16) % 5 == 0 for eid in event_ids)\n"
ast.parse(ts);tp.write_text(ts)
assert rebuild.rebuild(ROOT,publish=False)["before"]["up_to_date"]

for prep_only in (Path("data/public/metadata/g1_public_batch_0105_prep_evidence.json"),Path("tests/test_g1_public_batch_0105_prep.py")):
    if prep_only.exists():prep_only.unlink()

changed=set(subprocess.check_output(["git","diff","--name-only",BASE],text=True).splitlines());changed.update([str(batch),str(evidence_path),str(tp),SCRIPT])
permitted={WORKFLOW,SCRIPT,str(contract_path),str(exclusion_path),str(hints_path),str(acq),str(batch),str(evidence_path),str(tp),
"docs/g1_announcement_times.md","src/metadata_resolver.py","tests/test_metadata_resolver.py","tests/test_g1_source_research.py","tests/test_g1_acquisition_manifest.py","tests/test_real_data_release_sprint.py",
str(cp),str(cp.parent/"unresolved_gates.csv"),str(sd/"step_status.json"),"data/processed/research_receipt_bundle.json",
"data/processed/real_data_replay/real_data_replay_status.json","data/public/metadata/g1_public_batch_0105_integration_spec.json","data/public/metadata/g1_public_batch_0105_prep_evidence.json","tests/test_g1_public_batch_0105_prep.py"} | {str(x) for x in Path("tests").glob("test_g1_public_batch_*.py")} | {str(md/name) for name in rebuild.METADATA_RECEIPTS}
assert changed<=permitted,f"Unexpected {changed-permitted}"
allowp=Path("config/release_drift_allowlist.json");allow=load(allowp);reason="G1 batch 0105 Worker-0 filed federal-court public-distribution clocks for eight events; deterministic 145 exact / 29 reviewed exclusions with pinned press-release identity corroboration and prior evidence preserved."
for name in sorted(changed):
    sec="intentional_release_modifications" if name in allow["intentional_release_modifications"] else "repository_additions"
    allow[sec][name]={"expected_sha256":sha(name),"reason":reason}
save(allowp,allow);changed.add(str(allowp));subprocess.run(["git","add","--",*sorted(changed)],check=True)
audit=Path("private_runtime/audit/g1-batch-0105");audit.mkdir(parents=True,exist_ok=True)
save(audit/"verification.json",{"base_main_sha":BASE,"source_head_sha":os.environ["GITHUB_SHA"],"exact":145,"reviewed_excluded":29,
"previous_exact_preserved":137,"new_events":items,"step9":"SOURCE_BLOCKED","evaluation_release_permitted":False,"deterministic_rebuild_matches":True})
print(json.dumps({"exact":145,"reviewed_excluded":29,"new_events":[x["event_id"] for x in items]},indent=2))
