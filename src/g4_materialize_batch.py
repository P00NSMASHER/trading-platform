from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
MAX_STALENESS_DAYS = 130
OUT_FIELDS = [
    "observation_index","historical_symbol","target_trade_date","target_cutoff_local",
    "cik","fact_date","available_at","shares_outstanding","source_tag","form",
    "accession","filed_date","staleness_days","source_grade","source_reference",
    "staleness_exception_max_days","staleness_exception_reason",
    "status","unresolved_reason","research_use_only",
]


def read_csv(path: Path):
    with path.open(newline="", encoding="utf-8") as f:
        return [{k:(v or "").strip() for k,v in r.items()} for r in csv.DictReader(f)]


def cutoff(req):
    starts=[]
    for interval in (req.get("window_intervals_local") or "").split(";"):
        interval=interval.strip()
        if "-" not in interval:
            continue
        s=interval.split("-",1)[0].strip()
        try:
            hh,mm=map(int,s.split(":"))
            starts.append((hh,mm))
        except Exception:
            pass
    hh,mm=min(starts) if starts else (23,59)
    return datetime.fromisoformat(f'{req["trade_date"]}T{hh:02d}:{mm:02d}:00').replace(tzinfo=NY)


def available_at(filed_date: str):
    return datetime.fromisoformat(f"{filed_date}T23:59:59").replace(tzinfo=NY)


def build(requirements: Path, anchors: Path, start: int, count: int, output: Path, report: Path):
    reqs=read_csv(requirements)[start:start+count]
    anchors_by=defaultdict(list)
    for a in read_csv(anchors):
        anchors_by[a["historical_symbol"].upper()].append(a)
    for arr in anchors_by.values():
        arr.sort(key=lambda a:(a["fact_date"],a["filed_date"]))

    rows=[]
    unresolved={}
    usage=defaultdict(int)
    for offset, req in enumerate(reqs):
        idx=start+offset+1
        sym=req["historical_symbol"].upper()
        td=date.fromisoformat(req["trade_date"])
        co=cutoff(req)
        valid=[]
        for a in anchors_by.get(sym,[]):
            fd=date.fromisoformat(a["fact_date"])
            filed=date.fromisoformat(a["filed_date"])
            avail=available_at(a["filed_date"])
            stale=(td-fd).days
            if fd>td or filed>td or avail>co or stale<0 or stale>MAX_STALENESS_DAYS:
                continue
            valid.append((stale,-fd.toordinal(),a,avail))
        if valid:
            stale,_,a,avail=sorted(valid,key=lambda x:(x[0],x[1]))[0]
            usage[f'{sym}|{a["fact_date"]}|{a["accession"]}']+=1
            row={
                "observation_index":idx,"historical_symbol":sym,"target_trade_date":req["trade_date"],
                "target_cutoff_local":co.isoformat(),"cik":a["cik"],"fact_date":a["fact_date"],
                "available_at":avail.isoformat(),"shares_outstanding":a["shares_outstanding"],
                "source_tag":a["source_tag"],"form":a["form"],"accession":a["accession"],
                "filed_date":a["filed_date"],"staleness_days":stale,"source_grade":a["source_grade"],
                "source_reference":a["source_reference"],
                "staleness_exception_max_days":"",
                "staleness_exception_reason":"",
                "status":"RESOLVED","unresolved_reason":"","research_use_only":1,
            }
        else:
            unresolved[sym]=unresolved.get(sym,0)+1
            row={
                "observation_index":idx,"historical_symbol":sym,"target_trade_date":req["trade_date"],
                "target_cutoff_local":co.isoformat(),"cik":"","fact_date":"","available_at":"",
                "shares_outstanding":"","source_tag":"","form":"","accession":"","filed_date":"",
                "staleness_days":"","source_grade":"","source_reference":"",
                "staleness_exception_max_days":"","staleness_exception_reason":"",
                "status":"UNRESOLVED","unresolved_reason":"no_pre_window_anchor_within_130_days","research_use_only":1,
            }
        rows.append(row)

    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=OUT_FIELDS);w.writeheader();w.writerows(rows)
    resolved=sum(r["status"]=="RESOLVED" for r in rows)
    obj={
        "schema_version":"1","research_use_only":True,"batch_start_zero_based":start,
        "batch_count":count,"observation_index_first":start+1,"observation_index_last":start+count,
        "resolved_count":resolved,"unresolved_count":count-resolved,"remaining_after_batch":3828-(start+resolved),
        "unique_symbol_count":len({r["historical_symbol"] for r in rows}),
        "unresolved_by_symbol":unresolved,"anchor_usage":dict(sorted(usage.items())),
        "max_staleness_days":MAX_STALENESS_DAYS,
        "availability_policy":"Conservative end-of-filing-day timestamp in America/New_York; must precede earliest requested market interval.",
        "future_filed_facts_prohibited":True,
    }
    report.parent.mkdir(parents=True,exist_ok=True)
    report.write_text(json.dumps(obj,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    return obj


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--requirements",type=Path,required=True)
    ap.add_argument("--anchors",type=Path,required=True)
    ap.add_argument("--start",type=int,required=True)
    ap.add_argument("--count",type=int,required=True)
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--report",type=Path,required=True)
    a=ap.parse_args()
    print(json.dumps(build(a.requirements,a.anchors,a.start,a.count,a.output,a.report),indent=2))


if __name__=="__main__":
    main()
