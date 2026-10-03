from pathlib import Path
import json,re,ast

p=Path("scripts/g1_batch_0095_generate.py")
s=p.read_text()
spec=json.loads(Path("data/public/metadata/g1_public_batch_0095_integration_spec.json").read_text())
base=spec["base_main_sha"]
s=s.replace("0077","0095").replace("Worker-2","Worker-0").replace("worker2","worker0")
s=re.sub(r'^BASE="[^"]+"$',f'BASE="{base}"',s,count=1,flags=re.M)
s=s.replace('len(old_exact)==101','len(old_exact)==107').replace('len(exclusions["exclusions"])==73','len(exclusions["exclusions"])==67')
items=[]
for x in spec["items"]:
 items.append(dict(
  event_id=x["event_id"],historical_symbol=x["historical_symbol"],expected_trade=x["expected_trade"],clock=x["clock"],
  publisher_timestamp_text=f'CourtListener RECAP federal filing records {x["historical_symbol"]} public distribution at 2013-10-22 16:05 EDT',
  release_title=x["release_title"],source_reference=spec["source_reference"],court_docket_reference=spec["court_docket_reference"],
  corroboration_reference=x["corroboration_reference"],
  corroboration_basis="Filed federal-court record explicitly identifies the exact public-distribution clock; matching SEC Exhibit 99.1 independently corroborates the issuer/release identity and date.",
  timestamp_evidence_kind="explicit_release_clock",source_family="federal_court_public_distribution_record",source_grade="A",
  public_distribution_explicit=True,expected_delta=x["expected_delta"]))
block="specs="+repr(items)+"\nitems=[]"
s=re.sub(r'specs=\[[\s\S]*?\]\nitems=\[\]',block,s,count=1)
s=s.replace('"previous_exact_count":101,"expected_exact_count_after_batch":106,"expected_excluded_after_batch":68','"previous_exact_count":107,"expected_exact_count_after_batch":109,"expected_excluded_after_batch":65')
s=s.replace('exact_resolved=106,reviewed_excluded=68,raw_exact_time_evidence_gaps=68,exact_timing_analysis_eligible=106','exact_resolved=109,reviewed_excluded=65,raw_exact_time_evidence_gaps=65,exact_timing_analysis_eligible=109')
s=s.replace('expected_count=68','expected_count=65')
s=s.replace('G1 has 106 exact release timestamps and 68 reviewed fail-closed exclusions','G1 has 109 exact release timestamps and 65 reviewed fail-closed exclusions')
s=s.replace('public_exact_batch_count=72,exact_resolved_event_records=106,reviewed_excluded_event_records=68','public_exact_batch_count=74,exact_resolved_event_records=109,reviewed_excluded_event_records=65')
s=s.replace('72 and cumulative exact event records are 106','74 and cumulative exact event records are 109')
s=re.sub(r'expected=\{[\s\S]*?\n\}', 'expected={"HEJFE-F20ECC0C09BBC89E":"2013-10-22T20:05:00Z","HEJFE-8167467EBF64AABE":"2013-10-22T20:05:00Z"}',s,count=1)
for a,b in [("==106","==109"),("==68","==65"),("(101,73)","(107,67)"),("(106,68)","(109,65)"),("(101, 73)","(107, 67)"),("(106, 68)","(109, 65)"),("101/174","107/174"),("106/174","109/174"),("73\" in step9","67\" in step9"),("68\" in step9","65\" in step9"),("len(excluded)==68","len(excluded)==65"),("len(excluded) == 68","len(excluded) == 65"),("len(ex)==68","len(ex)==65"),("len(ex) == 68","len(ex) == 65")]:
 s=s.replace(a,b)
s=s.replace('70 public exact-time batches / 100 exact-resolved','73 public exact-time batches / 107 exact-resolved')
s=s.replace('72 public exact-time batches / 106 exact-resolved','74 public exact-time batches / 109 exact-resolved')
s=s.replace('WTS/THC/DXCM/WLL/CR exact public-distribution clocks','JNPR/PNRA exact public-distribution clocks')
s=s.replace('five releases','two releases')
s=s.replace('"exact":106,"reviewed_excluded":68','"exact":109,"reviewed_excluded":65').replace('"previous_exact_preserved":101','"previous_exact_preserved":107')
s=s.replace('{"exact":106,"reviewed_excluded":68','{"exact":109,"reviewed_excluded":65')
s=s.replace('assert len(d["items"])==5','assert len(d["items"])==2')
ast.parse(s)
p.write_text(s)

Path("scripts/g1_batch_0095_patch.py").unlink(missing_ok=True)
