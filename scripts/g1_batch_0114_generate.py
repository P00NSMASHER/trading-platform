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
BASE="8014585b043217da5d5774382eb79e6a8b0972cc"
WORKFLOW=".github/workflows/g1-public-batch-0114-worker-4.yml"
SCRIPT="scripts/g1_batch_0114_generate.py"
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
assert len(events)==174 and len(old_exact)==123
exclusion_path=md/"g1_final_timing_exclusions.json"
exclusions=load(exclusion_path)
assert len(exclusions["exclusions"])==51

batch=Path("data/public/metadata/g1_announcement_times_batch_0114.csv")
evidence_path=Path("data/public/metadata/g1_public_batch_0114_evidence.json")
assert not batch.exists() and not evidence_path.exists()

specs=[
  {
    "event_id": "HEJFE-4080E04F012A7290",
    "historical_symbol": "QLIK",
    "expected_trade": "2015-02-12 15:39:00",
    "clock": "2015-02-12T16:05:00-05:00",
    "explicit_release_clock_text": "GX 8002 row 1869 explicitly records Press Release / Distribution Time 2015-02-12 16:05 Eastern",
    "release_title": "Qlik Technologies Announces Fourth Quarter and Full Year 2014 Financial Results",
    "source_reference": "https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf",
    "corroboration_reference": "https://www.sec.gov/Archives/edgar/data/1305294/000119312515046702/d873496dex991.htm",
    "corroboration_basis": "Official SEC Exhibit 99.x corroborates issuer, title, content and date.",
    "timestamp_evidence_kind": "explicit_release_clock",
    "source_family": "federal_court_public_distribution_record",
    "source_grade": "A",
    "public_distribution_explicit": True,
    "expected_delta": 1560,
    "court_docket_reference": "https://www.courtlistener.com/docket/4324653/united-states-v-korchevsky/",
    "gx8002_row_id": "1869",
    "wire_source_code": "BW",
    "corroborating_release_member_path": "2015/QTR1/12026_20150212_0.txt"
  },
  {
    "event_id": "HEJFE-7CEFB3FE3D986464",
    "historical_symbol": "ROG",
    "expected_trade": "2015-02-17 15:44:00",
    "clock": "2015-02-17T16:01:00-05:00",
    "explicit_release_clock_text": "GX 8002 row 1877 explicitly records Press Release / Distribution Time 2015-02-17 16:01 Eastern",
    "release_title": "Rogers Corporation Reports Fourth Quarter and Full Year 2014 Results",
    "source_reference": "https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf",
    "corroboration_reference": "https://www.sec.gov/Archives/edgar/data/84748/000115752315000594/a51041844ex99_1.htm",
    "corroboration_basis": "Official SEC Exhibit 99.x corroborates issuer, title, content and date.",
    "timestamp_evidence_kind": "explicit_release_clock",
    "source_family": "federal_court_public_distribution_record",
    "source_grade": "A",
    "public_distribution_explicit": True,
    "expected_delta": 1020,
    "court_docket_reference": "https://www.courtlistener.com/docket/4324653/united-states-v-korchevsky/",
    "gx8002_row_id": "1877",
    "wire_source_code": "BW",
    "corroborating_release_member_path": "2015/QTR1/35991_20150217_0.txt"
  },
  {
    "event_id": "HEJFE-9861757889227DD4",
    "historical_symbol": "IDTI",
    "expected_trade": "2015-02-02 14:24:00",
    "clock": "2015-02-02T16:05:00-05:00",
    "explicit_release_clock_text": "GX 8002 row 1838 explicitly records Press Release / Distribution Time 2015-02-02 16:05 Eastern",
    "release_title": "IDT Reports Fiscal Third Quarter 2015 Financial Results",
    "source_reference": "https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf",
    "corroboration_reference": "https://www.sec.gov/Archives/edgar/data/703361/000070336115000003/a8-kq3fy15earningsexhibit9.htm",
    "corroboration_basis": "Official SEC Exhibit 99.x corroborates issuer, title, content and date.",
    "timestamp_evidence_kind": "explicit_release_clock",
    "source_family": "federal_court_public_distribution_record",
    "source_grade": "A",
    "public_distribution_explicit": True,
    "expected_delta": 6060,
    "court_docket_reference": "https://www.courtlistener.com/docket/4324653/united-states-v-korchevsky/",
    "gx8002_row_id": "1838",
    "wire_source_code": "BW",
    "corroborating_release_member_path": "2015/QTR1/44506_20150202_0.txt"
  },
  {
    "event_id": "HEJFE-8EAA8616B1750B40",
    "historical_symbol": "CGNX",
    "expected_trade": "2015-05-04 15:09:00",
    "clock": "2015-05-04T16:06:00-04:00",
    "explicit_release_clock_text": "GX 8002 row 1966 explicitly records Press Release / Distribution Time 2015-05-04 16:06 Eastern",
    "release_title": "Cognex Reports Record First Quarter Results",
    "source_reference": "https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf",
    "corroboration_reference": "https://www.sec.gov/Archives/edgar/data/851205/000115752315001539/a51094452ex99_1.htm",
    "corroboration_basis": "Official SEC Exhibit 99.x corroborates issuer, title, content and date.",
    "timestamp_evidence_kind": "explicit_release_clock",
    "source_family": "federal_court_public_distribution_record",
    "source_grade": "A",
    "public_distribution_explicit": True,
    "expected_delta": 3420,
    "court_docket_reference": "https://www.courtlistener.com/docket/4324653/united-states-v-korchevsky/",
    "gx8002_row_id": "1966",
    "wire_source_code": "BW",
    "corroborating_release_member_path": "2015/QTR2/75654_20150504_0.txt"
  },
  {
    "event_id": "HEJFE-8415E931D4314106",
    "historical_symbol": "KOPN",
    "expected_trade": "2015-03-10 14:58:00",
    "clock": "2015-03-10T16:05:00-04:00",
    "explicit_release_clock_text": "GX 8002 row 1909 explicitly records Press Release / Distribution Time 2015-03-10 16:05 Eastern",
    "release_title": "Kopin Corporation Provides Business Update and Fourth-Quarter and Fiscal Year 2014 Operating Results",
    "source_reference": "https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf",
    "corroboration_reference": "https://www.sec.gov/Archives/edgar/data/771266/000115752315000889/a51056072ex99_1.htm",
    "corroboration_basis": "Official SEC Exhibit 99.x corroborates issuer, title, content and date.",
    "timestamp_evidence_kind": "explicit_release_clock",
    "source_family": "federal_court_public_distribution_record",
    "source_grade": "A",
    "public_distribution_explicit": True,
    "expected_delta": 4020,
    "court_docket_reference": "https://www.courtlistener.com/docket/4324653/united-states-v-korchevsky/",
    "gx8002_row_id": "1909",
    "wire_source_code": "BW",
    "corroborating_release_member_path": ""
  },
  {
    "event_id": "HEJFE-0AA84E6E44ED02D8",
    "historical_symbol": "AMSG",
    "expected_trade": "2015-02-25 15:57:00",
    "clock": "2015-02-25T16:00:00-05:00",
    "explicit_release_clock_text": "GX 8002 row 1894 explicitly records Press Release / Distribution Time 2015-02-25 16:00 Eastern",
    "release_title": "AmSurg Reports Fourth-Quarter and 2014 Results",
    "source_reference": "https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf",
    "corroboration_reference": "https://www.sec.gov/Archives/edgar/data/895930/000089593015000008/amsg8k20150225ex99.htm",
    "corroboration_basis": "Official SEC Exhibit 99.x corroborates issuer, title, content and date.",
    "timestamp_evidence_kind": "explicit_release_clock",
    "source_family": "federal_court_public_distribution_record",
    "source_grade": "A",
    "public_distribution_explicit": True,
    "expected_delta": 180,
    "court_docket_reference": "https://www.courtlistener.com/docket/4324653/united-states-v-korchevsky/",
    "gx8002_row_id": "1894",
    "wire_source_code": "BW",
    "corroborating_release_member_path": ""
  },
  {
    "event_id": "HEJFE-947F50EBAFBA54DC",
    "historical_symbol": "CRL",
    "expected_trade": "2015-02-10 15:55:00",
    "clock": "2015-02-10T16:30:00-05:00",
    "explicit_release_clock_text": "GX 8002 row 1851 explicitly records Press Release / Distribution Time 2015-02-10 16:30 Eastern",
    "release_title": "Charles River Laboratories Announces Fourth-Quarter and Full-Year 2014 Results",
    "source_reference": "https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf",
    "corroboration_reference": "https://www.sec.gov/Archives/edgar/data/1100682/000115752315000503/a51037415ex99_1.htm",
    "corroboration_basis": "Official SEC Exhibit 99.x corroborates issuer, title, content and date.",
    "timestamp_evidence_kind": "explicit_release_clock",
    "source_family": "federal_court_public_distribution_record",
    "source_grade": "A",
    "public_distribution_explicit": True,
    "expected_delta": 2100,
    "court_docket_reference": "https://www.courtlistener.com/docket/4324653/united-states-v-korchevsky/",
    "gx8002_row_id": "1851",
    "wire_source_code": "BW",
    "corroborating_release_member_path": "2015/QTR1/88281_20150210_0.txt"
  },
  {
    "event_id": "HEJFE-791693865584F9CB",
    "historical_symbol": "COL",
    "expected_trade": "2015-04-22 14:29:00",
    "clock": "2015-04-23T07:30:00-04:00",
    "explicit_release_clock_text": "GX 8002 row 1936 explicitly records Press Release / Distribution Time 2015-04-23 07:30 Eastern",
    "release_title": "Rockwell Collins Reports Second Quarter Fiscal Year 2015 Results",
    "source_reference": "https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf",
    "corroboration_reference": "https://www.sec.gov/Archives/edgar/data/1137411/000113741115000068/col_3312015xexhibit991.htm",
    "corroboration_basis": "Official SEC Exhibit 99.x corroborates issuer, title, content and date.",
    "timestamp_evidence_kind": "explicit_release_clock",
    "source_family": "federal_court_public_distribution_record",
    "source_grade": "A",
    "public_distribution_explicit": True,
    "expected_delta": 61260,
    "court_docket_reference": "https://www.courtlistener.com/docket/4324653/united-states-v-korchevsky/",
    "gx8002_row_id": "1936",
    "wire_source_code": "BW",
    "corroborating_release_member_path": "2015/QTR2/89014_20150423_0.txt"
  },
  {
    "event_id": "HEJFE-22BF36BABB9D19D7",
    "historical_symbol": "ALNY",
    "expected_trade": "2015-02-12 15:55:00",
    "clock": "2015-02-12T16:00:00-05:00",
    "explicit_release_clock_text": "GX 8002 row 1860 explicitly records Press Release / Distribution Time 2015-02-12 16:00 Eastern",
    "release_title": "Alnylam Pharmaceuticals Reports Fourth Quarter and Full Year 2014 Financial Results",
    "source_reference": "https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf",
    "corroboration_reference": "https://www.sec.gov/Archives/edgar/data/1178670/000115752315000553/a51039029-ex991.htm",
    "corroboration_basis": "Official SEC Exhibit 99.x corroborates issuer, title, content and date.",
    "timestamp_evidence_kind": "explicit_release_clock",
    "source_family": "federal_court_public_distribution_record",
    "source_grade": "A",
    "public_distribution_explicit": True,
    "expected_delta": 300,
    "court_docket_reference": "https://www.courtlistener.com/docket/4324653/united-states-v-korchevsky/",
    "gx8002_row_id": "1860",
    "wire_source_code": "BW",
    "corroborating_release_member_path": "2015/QTR1/90178_20150212_0.txt"
  },
  {
    "event_id": "HEJFE-E28050410A1480C6",
    "historical_symbol": "DYN",
    "expected_trade": "2015-05-06 14:24:00",
    "clock": "2015-05-06T16:07:00-04:00",
    "explicit_release_clock_text": "GX 8002 row 1978 explicitly records Press Release / Distribution Time 2015-05-06 16:07 Eastern",
    "release_title": "Dynegy Reports First Quarter 2015 Results",
    "source_reference": "https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf",
    "corroboration_reference": "https://www.sec.gov/Archives/edgar/data/1379895/000110465915034877/a15-10867_2ex99d1.htm",
    "corroboration_basis": "PR #355 exact event/date press-release mapping at 2015/QTR2/90352_20150506_0.txt; official SEC Exhibit 99.x also corroborates issuer, title, content and date.",
    "timestamp_evidence_kind": "explicit_release_clock",
    "source_family": "federal_court_public_distribution_record",
    "source_grade": "A",
    "public_distribution_explicit": True,
    "expected_delta": 6180,
    "court_docket_reference": "https://www.courtlistener.com/docket/4324653/united-states-v-korchevsky/",
    "gx8002_row_id": "1978",
    "wire_source_code": "BW",
    "corroborating_release_member_path": "2015/QTR2/90352_20150506_0.txt"
  },
  {
    "event_id": "HEJFE-0704950C71CFAFB4",
    "historical_symbol": "TXRH",
    "expected_trade": "2015-02-23 15:24:00",
    "clock": "2015-02-23T16:02:00-05:00",
    "explicit_release_clock_text": "GX 8002 row 1893 explicitly records Press Release / Distribution Time 2015-02-23 16:02 Eastern",
    "release_title": "Texas Roadhouse, Inc. Announces Fourth Quarter 2014 Results",
    "source_reference": "https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf",
    "corroboration_reference": "https://www.sec.gov/Archives/edgar/data/1289460/000110465915013055/a15-5200_1ex99d1.htm",
    "corroboration_basis": "PR #355 exact event/date press-release mapping at 2015/QTR1/90427_20150223_0.txt; official SEC Exhibit 99.x also corroborates issuer, title, content and date.",
    "timestamp_evidence_kind": "explicit_release_clock",
    "source_family": "federal_court_public_distribution_record",
    "source_grade": "A",
    "public_distribution_explicit": True,
    "expected_delta": 2280,
    "court_docket_reference": "https://www.courtlistener.com/docket/4324653/united-states-v-korchevsky/",
    "gx8002_row_id": "1893",
    "wire_source_code": "BW",
    "corroborating_release_member_path": "2015/QTR1/90427_20150223_0.txt"
  },
  {
    "event_id": "HEJFE-C926C41F03E66E82",
    "historical_symbol": "PAY",
    "expected_trade": "2014-12-15 15:36:00",
    "clock": "2014-12-15T16:01:00-05:00",
    "explicit_release_clock_text": "GX 8002 row 1808 explicitly records Press Release / Distribution Time 2014-12-15 16:01 Eastern",
    "release_title": "VeriFone Reports Results for the Fourth Quarter and Fiscal Year 2014",
    "source_reference": "https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf",
    "corroboration_reference": "https://www.sec.gov/Archives/edgar/data/1312073/000131207314000041/ex991q42014pressrelease.htm",
    "corroboration_basis": "PR #355 exact event/date press-release mapping at 2014/QTR4/90657_20141215_0.txt; official SEC Exhibit 99.x also corroborates issuer, title, content and date.",
    "timestamp_evidence_kind": "explicit_release_clock",
    "source_family": "federal_court_public_distribution_record",
    "source_grade": "A",
    "public_distribution_explicit": True,
    "expected_delta": 1500,
    "court_docket_reference": "https://www.courtlistener.com/docket/4324653/united-states-v-korchevsky/",
    "gx8002_row_id": "1808",
    "wire_source_code": "BW",
    "corroborating_release_member_path": "2014/QTR4/90657_20141215_0.txt"
  },
  {
    "event_id": "HEJFE-826F68D9DA88B37C",
    "historical_symbol": "ATRC",
    "expected_trade": "2015-02-23 15:58:00",
    "clock": "2015-02-23T16:02:00-05:00",
    "explicit_release_clock_text": "GX 8002 row 1889 explicitly records Press Release / Distribution Time 2015-02-23 16:02 Eastern",
    "release_title": "AtriCure Reports Fourth Quarter and Full Year 2014 Financial Results",
    "source_reference": "https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf",
    "corroboration_reference": "https://www.sec.gov/Archives/edgar/data/1323885/000119312515058137/d879026dex991.htm",
    "corroboration_basis": "PR #355 exact event/date press-release mapping at 2015/QTR1/90856_20150223_0.txt; official SEC Exhibit 99.x also corroborates issuer, title, content and date.",
    "timestamp_evidence_kind": "explicit_release_clock",
    "source_family": "federal_court_public_distribution_record",
    "source_grade": "A",
    "public_distribution_explicit": True,
    "expected_delta": 240,
    "court_docket_reference": "https://www.courtlistener.com/docket/4324653/united-states-v-korchevsky/",
    "gx8002_row_id": "1889",
    "wire_source_code": "BW",
    "corroborating_release_member_path": "2015/QTR1/90856_20150223_0.txt"
  },
  {
    "event_id": "HEJFE-A5AE76F13A48C40F",
    "historical_symbol": "DGI",
    "expected_trade": "2013-05-07 14:29:00",
    "clock": "2013-05-07T16:02:00-04:00",
    "explicit_release_clock_text": "GX 8002 row 1703 explicitly records Press Release / Distribution Time 2013-05-07 16:02 Eastern",
    "release_title": "DigitalGlobe Reports First Quarter 2013 Results",
    "source_reference": "https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf",
    "corroboration_reference": "https://www.sec.gov/Archives/edgar/data/1208208/000119312513204419/d532876dex991.htm",
    "corroboration_basis": "PR #355 exact event/date press-release mapping at 2013/QTR2/92924_20130507_0.txt; official SEC Exhibit 99.x also corroborates issuer, title, content and date.",
    "timestamp_evidence_kind": "explicit_release_clock",
    "source_family": "federal_court_public_distribution_record",
    "source_grade": "A",
    "public_distribution_explicit": True,
    "expected_delta": 5580,
    "court_docket_reference": "https://www.courtlistener.com/docket/4324653/united-states-v-korchevsky/",
    "gx8002_row_id": "1703",
    "wire_source_code": "MW",
    "corroborating_release_member_path": "2013/QTR2/92924_20130507_0.txt"
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
    trial["validation_probes"].append(dict(item,probe_id=f'{spec["historical_symbol"]}-batch0114',historical_event_match=True,
      exact_clock_observed=True,exact_public_release_ts=release.isoformat(),evidence_eligible=True))
research.validate_research_map(trial,exclusions)

fields=["event_id","historical_symbol","event_date","public_announcement_ts","timestamp_kind","source_grade","source_reference"]
s=io.StringIO(newline="");w=csv.DictWriter(s,fieldnames=fields,lineterminator="\n");w.writeheader()
for x in items:w.writerow({k:x[k] for k in fields})
batch.write_text(s.getvalue(),encoding="utf-8")
save(evidence_path,{"schema_version":"1","research_use_only":True,"base_main_sha":BASE,"batch_path":str(batch),"batch_sha256":sha(batch),
"items":items,"previous_exact_count":123,"expected_exact_count_after_batch":137,"expected_excluded_after_batch":37,
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
exclusions["g1_state"].update(exact_resolved=137,reviewed_excluded=37,raw_exact_time_evidence_gaps=37,exact_timing_analysis_eligible=137)
save(exclusion_path,exclusions)

contract_path=Path("config/metadata_sources.public_progress.json");contract=load(contract_path)
contract["sources"].insert(0,{"source_id":"public-worker4-federal-court-gx8002-batch-0114","record_kind":"announcement_timestamp",
"source_family":"federal_court_public_distribution_record","path":str(batch),"enabled":True,"authorized":True,"data_classification":"public_official_data",
"delimiter":",","encoding":"utf-8","timezone":"America/New_York","column_map":{k:k for k in fields},
"license_reference":"Filed E.D.N.Y. GX 8002 Document 367-2 explicit press-release/public-distribution clocks, with exact release identity/date corroborated by pinned public press-release members and SEC Exhibits 99.x. No licensed vendor data used.",
"notes":"Fourteen exact first-public distribution clocks; prohibited substitute times are not used."})
contract["reviewed_announcement_exclusions"].update(expected_count=37,expected_sha256=sha(exclusion_path))
contract["purpose"]="Cumulative public point-in-time metadata: G1 has 137 exact release timestamps and 37 reviewed fail-closed exclusions; exact-timing and all independent non-synthetic release locks remain fail-closed."
save(contract_path,contract)

hints["priority_events"]=[r for r in hints.get("priority_events",[]) if r.get("event_id") not in ids]
hints["validation_probes"]=[r for r in hints.get("validation_probes",[]) if r.get("event_id") not in ids]
hints["base_main_sha"]=BASE
hints["current_g1_state"].update(public_exact_batch_count=81,exact_resolved_event_records=137,reviewed_excluded_event_records=37,
 note="The latest integrated recovery is batch_0114; cumulative public exact-time batches are 81 and cumulative exact event records are 137 because some public batches resolve more than one historical event.")
for item in items:
    hints["validation_probes"].append(dict(item,probe_id=f'{item["historical_symbol"]}-batch0114',historical_event_match=True,
      exact_clock_observed=True,exact_public_release_ts=item["public_announcement_ts"],evidence_eligible=False,
      disposition="RESOLVED_IN_BATCH_0114",reason="Promoted from filed federal-court GX 8002 explicit public-distribution clock with pinned press-release/SEC identity corroboration."))
save(hints_path,hints)

assert rebuild.rebuild(ROOT,publish=True)["after"]["up_to_date"]
fresh=rows(md/"announcement_resolutions.csv");by={r["event_id"]:r for r in fresh};assert len(by)==174
for eid,old in old_exact.items():assert by[eid]==old
expected={item["event_id"]:datetime.fromisoformat(item["public_announcement_ts"]).astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00","Z") for item in items}
for item in items:
    r=by[item["event_id"]];assert r["resolution_status"]=="resolved_exact_public_timestamp" and r["public_announcement_ts"]==expected[item["event_id"]]
excluded=[r for r in fresh if r["resolution_status"]=="excluded_fail_closed"]
assert len(excluded)==37 and all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in excluded)
ready=load(md/"metadata_readiness_summary.json");assert ready["announcement_exact_resolved"]==137 and ready["announcement_events_excluded"]==37
assert ready["ready_g1_exact_timing_analysis"] is False

acq=Path("data/public/metadata/g1_acquisition_manifest.json");acq.write_text(acquisition.render_manifest(acquisition.build_manifest()),encoding="utf-8")
sd=Path("data/processed/real_data_release_sprint");cp=Path("data/processed/coverage_plan_real/coverage_summary.json")
sprint.refresh_coverage(coverage_summary_path=cp,metadata_readiness_path=md/"metadata_readiness_summary.json",
 metadata_quality_path=md/"metadata_quality_summary.json",requirements_manifest_path=sd/"requirements_manifest.json",
 unresolved_gates_path=cp.parent/"unresolved_gates.csv")
status=sprint.build_status(requirements_manifest_path=sd/"requirements_manifest.json",coverage_summary_path=cp,
 metadata_readiness_path=md/"metadata_readiness_summary.json",metadata_quality_path=md/"metadata_quality_summary.json",outpath=sd/"step_status.json")
step9=next(x for x in status["steps"] if x["step"]==9);assert step9["status"]=="SOURCE_BLOCKED" and "137/174" in step9["evidence"] and "37" in step9["evidence"]

test_files=["tests/test_g1_source_research.py","tests/test_g1_acquisition_manifest.py","tests/test_real_data_release_sprint.py",
*sorted(str(x) for x in Path("tests").glob("test_g1_public_batch_*.py"))]
for fn in test_files:
    p=Path(fn);txt=p.read_text()
    if fn.endswith("test_g1_source_research.py"):
        pairs=[('report["exact_resolved_event_records"] == 123','report["exact_resolved_event_records"] == 137'),
          ('report["reviewed_excluded_event_records"] == 51','report["reviewed_excluded_event_records"] == 37'),
          ('state["public_exact_batch_count"] == 80','state["public_exact_batch_count"] == 81'),
          ('state["exact_resolved_event_records"] == 123','state["exact_resolved_event_records"] == 137')]
    elif fn.endswith("test_g1_acquisition_manifest.py"):
        pairs=[('manifest["state"]["exact_resolved"] == 123','manifest["state"]["exact_resolved"] == 137'),
          ('manifest["state"]["acquisition_needed"] == 51','manifest["state"]["acquisition_needed"] == 37'),
          ('len(manifest["work_queue"]) == 51','len(manifest["work_queue"]) == 37'),
          ('len({row["dedupe_key"] for row in manifest["work_queue"]}) == 51','len({row["dedupe_key"] for row in manifest["work_queue"]}) == 37'),
          ('len(resolved) == 123','len(resolved) == 137'),('len(unresolved) == 51','len(unresolved) == 37')]
    elif fn.endswith("test_real_data_release_sprint.py"):
        pairs=[('updated["missing_exact_announcement_timestamps"] == 51','updated["missing_exact_announcement_timestamps"] == 37')]
    else:
        pairs=[('(readiness["announcement_exact_resolved"],readiness["announcement_events_excluded"]) == (123,51)','(readiness["announcement_exact_resolved"],readiness["announcement_events_excluded"]) == (137,37)'),
          ('(readiness["announcement_exact_resolved"], readiness["announcement_events_excluded"]) == (123, 51)','(readiness["announcement_exact_resolved"], readiness["announcement_events_excluded"]) == (137, 37)'),
          ('"123/174" in step9["evidence"] and "51" in step9["evidence"]','"137/174" in step9["evidence"] and "37" in step9["evidence"]'),
          ('len(excluded)==51','len(excluded)==37'),('len(excluded) == 51','len(excluded) == 37'),
          ('len(ex)==51','len(ex)==37'),('len(ex) == 51','len(ex) == 37')]
    for old,new in pairs:txt=txt.replace(old,new)
    ast.parse(txt);p.write_text(txt)

p=Path("docs/g1_announcement_times.md");txt=p.read_text()
assert "80 public exact-time batches / 123 exact-resolved" in txt
txt=txt.replace("80 public exact-time batches / 123 exact-resolved","81 public exact-time batches / 137 exact-resolved",1)
txt += """
### Batch 0114: QLIK, ROG, IDTI, CGNX, KOPN, AMSG, CRL, COL, ALNY, DYN, TXRH, PAY, ATRC, DGI

Filed E.D.N.Y. GX 8002 Document 367-2 supplies explicit first-public press-release distribution clocks for fourteen Worker-4 events. Exact release identity/date is corroborated by pinned public press-release archive members and official SEC Exhibits 99.x. This advances G1 from 123 exact / 51 reviewed exclusions to 137 exact / 37 reviewed exclusions. Conference-call, EDGAR acceptance, archive-capture, date-only, scheduled-release and inferred clocks are not used. Step 9 remains SOURCE_BLOCKED.
""";p.write_text(txt)

tp=Path("tests/test_g1_public_batch_0114.py")
ts='''import csv,json,hashlib
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
def rr(p):
    with p.open(newline="",encoding="utf-8") as h:return list(csv.DictReader(h))
def test_batch_0114():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0114_evidence.json").read_text())
    events={r["event_id"]:r for r in rr(ROOT/"data/processed/historical_events.csv")}
    resolved={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    exp={"HEJFE-4080E04F012A7290":["QLIK","2015-02-12T21:05:00Z",1560],"HEJFE-7CEFB3FE3D986464":["ROG","2015-02-17T21:01:00Z",1020],"HEJFE-9861757889227DD4":["IDTI","2015-02-02T21:05:00Z",6060],"HEJFE-8EAA8616B1750B40":["CGNX","2015-05-04T20:06:00Z",3420],"HEJFE-8415E931D4314106":["KOPN","2015-03-10T20:05:00Z",4020],"HEJFE-0AA84E6E44ED02D8":["AMSG","2015-02-25T21:00:00Z",180],"HEJFE-947F50EBAFBA54DC":["CRL","2015-02-10T21:30:00Z",2100],"HEJFE-791693865584F9CB":["COL","2015-04-23T11:30:00Z",61260],"HEJFE-22BF36BABB9D19D7":["ALNY","2015-02-12T21:00:00Z",300],"HEJFE-E28050410A1480C6":["DYN","2015-05-06T20:07:00Z",6180],"HEJFE-0704950C71CFAFB4":["TXRH","2015-02-23T21:02:00Z",2280],"HEJFE-C926C41F03E66E82":["PAY","2014-12-15T21:01:00Z",1500],"HEJFE-826F68D9DA88B37C":["ATRC","2015-02-23T21:02:00Z",240],"HEJFE-A5AE76F13A48C40F":["DGI","2013-05-07T20:02:00Z",5580]}
    assert len(d["items"])==14
    for x in d["items"]:
        sym,utc,delta=exp[x["event_id"]];e=events[x["event_id"]]
        tr=datetime.fromisoformat(e["first_documented_illicit_trade_ts"]).replace(tzinfo=ZoneInfo("America/New_York"));rel=datetime.fromisoformat(x["public_announcement_ts"])
        assert e["historical_symbol"]==sym and tr<rel<=tr+timedelta(days=7) and int((rel-tr).total_seconds())==delta
        assert resolved[x["event_id"]]["public_announcement_ts"]==utc
        assert resolved[x["event_id"]]["resolution_status"]=="resolved_exact_public_timestamp"
        assert x["source_family"]=="federal_court_public_distribution_record" and x["source_grade"]=="A"
        assert x["timestamp_evidence_kind"]=="explicit_release_clock"
        assert x["public_distribution_explicit"] is True
        assert x["source_reference"].startswith("https://storage.courtlistener.com/recap/")
        assert x["corroboration_reference"].startswith(("https://github.com/","https://www.sec.gov/"))
def test_batch_0114_preserves_prior():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0114_evidence.json").read_text())
    assert hashlib.sha256((ROOT/d["batch_path"]).read_bytes()).hexdigest()==d["batch_sha256"]
    by={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    for eid,stamp in d["previous_exact_timestamps"].items():assert by[eid]["public_announcement_ts"]==stamp
    ex=[r for r in by.values() if r["resolution_status"]=="excluded_fail_closed"];assert len(ex)==37
    assert all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in ex)
def test_batch_0114_worker4_shard_ownership():
    event_ids=set(["HEJFE-4080E04F012A7290","HEJFE-7CEFB3FE3D986464","HEJFE-9861757889227DD4","HEJFE-8EAA8616B1750B40","HEJFE-8415E931D4314106","HEJFE-0AA84E6E44ED02D8","HEJFE-947F50EBAFBA54DC","HEJFE-791693865584F9CB","HEJFE-22BF36BABB9D19D7","HEJFE-E28050410A1480C6","HEJFE-0704950C71CFAFB4","HEJFE-C926C41F03E66E82","HEJFE-826F68D9DA88B37C","HEJFE-A5AE76F13A48C40F"])
    assert 114 >= 64 and (114-64) % 5 == 0
    assert all(int(hashlib.sha256(eid.encode("utf-8")).hexdigest(),16) % 5 == 4 for eid in event_ids)
'''
ast.parse(ts);tp.write_text(ts)
assert rebuild.rebuild(ROOT,publish=False)["before"]["up_to_date"]

for prep_only in (Path("data/public/metadata/g1_public_batch_0114_prep_evidence.json"),Path("tests/test_g1_public_batch_0114_prep.py")):
    if prep_only.exists():prep_only.unlink()

changed=set(subprocess.check_output(["git","diff","--name-only",BASE],text=True).splitlines());changed.update([str(batch),str(evidence_path),str(tp),SCRIPT])
permitted={WORKFLOW,SCRIPT,str(contract_path),str(exclusion_path),str(hints_path),str(acq),str(batch),str(evidence_path),str(tp),
"docs/g1_announcement_times.md","src/metadata_resolver.py","tests/test_metadata_resolver.py","tests/test_g1_source_research.py","tests/test_g1_acquisition_manifest.py","tests/test_real_data_release_sprint.py",
str(cp),str(cp.parent/"unresolved_gates.csv"),str(sd/"step_status.json"),"data/processed/research_receipt_bundle.json",
"data/processed/real_data_replay/real_data_replay_status.json","data/public/metadata/g1_public_batch_0114_integration_spec.json","data/public/metadata/g1_public_batch_0114_prep_evidence.json","tests/test_g1_public_batch_0114_prep.py"} | {str(x) for x in Path("tests").glob("test_g1_public_batch_*.py")} | {str(md/name) for name in rebuild.METADATA_RECEIPTS}
assert changed<=permitted,f"Unexpected {changed-permitted}"
allowp=Path("config/release_drift_allowlist.json");allow=load(allowp);reason="G1 batch 0114 Worker-4 filed federal-court public-distribution clocks for fourteen events; deterministic 137 exact / 37 reviewed exclusions with press-release/SEC identity corroboration and prior evidence preserved."
for name in sorted(changed):
    sec="intentional_release_modifications" if name in allow["intentional_release_modifications"] else "repository_additions"
    allow[sec][name]={"expected_sha256":sha(name),"reason":reason}
save(allowp,allow);changed.add(str(allowp));subprocess.run(["git","add","--",*sorted(changed)],check=True)
audit=Path("private_runtime/audit/g1-batch-0114");audit.mkdir(parents=True,exist_ok=True)
save(audit/"verification.json",{"base_main_sha":BASE,"source_head_sha":os.environ["GITHUB_SHA"],"exact":137,"reviewed_excluded":37,
"previous_exact_preserved":123,"new_events":items,"step9":"SOURCE_BLOCKED","evaluation_release_permitted":False,"deterministic_rebuild_matches":True})
print(json.dumps({"exact":137,"reviewed_excluded":37,"new_events":[x["event_id"] for x in items]},indent=2))
