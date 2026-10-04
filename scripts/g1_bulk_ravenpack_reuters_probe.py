#!/usr/bin/env python3
"""Bulk G1 discovery across all unresolved events.

Public lane: Reuters-full-data-set daily pickles, fetched only for unresolved event windows.
Licensed lane: RavenPack RPNA yearly/monthly files when lawfully supplied to --ravenpack-dir.
Outputs research candidates only; never mutates canonical G1 resolution state.
"""
import argparse,csv,io,json,pickle,re,urllib.request
from datetime import date,timedelta
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
MANIFEST=ROOT/"data/public/metadata/g1_acquisition_manifest.json"
OUT=ROOT/"data/public/metadata/g1_bulk_ravenpack_reuters_candidates.json"
EARN_RE=re.compile(r"earn|quarter|fiscal|results|eps|revenue|profit|loss",re.I)

class SafeUnpickler(pickle.Unpickler):
    def find_class(self,module,name):
        raise pickle.UnpicklingError(f"global forbidden: {module}.{name}")

def unresolved():
    d=json.loads(MANIFEST.read_text())
    return [x for x in d["items"] if x["current_resolution_status"]!="resolved_exact_public_timestamp"]

def daterange(a,b):
    d=date.fromisoformat(a); z=date.fromisoformat(b)
    while d<=z:
        yield d
        d+=timedelta(days=1)

def fetch_reuters_day(d):
    ymd=d.strftime("%Y%m%d")
    urls=[
      f"https://raw.githubusercontent.com/mike0sv/Reuters-full-data-set/master/data/{ymd}.pkl",
      f"https://raw.githubusercontent.com/philipperemy/Reuters-full-data-set/master/data/{ymd}.pkl",
    ]
    for u in urls:
        try:
            with urllib.request.urlopen(u,timeout=25) as r:
                raw=r.read()
            rows=SafeUnpickler(io.BytesIO(raw),encoding="latin1").load()
            return u,rows
        except Exception:
            pass
    return None,[]

def reuters_candidates(events):
    bydate={}
    for e in events:
        for d in daterange(e["search_window"]["start_date"],e["search_window"]["end_date"]):
            bydate.setdefault(d,[]).append(e)
    out=[]
    for d,evs in sorted(bydate.items()):
        src,rows=fetch_reuters_day(d)
        if not rows: continue
        for e in evs:
            sym=e["historical_symbol"].upper()
            trade=e["first_documented_illicit_trade_ts"]
            for r in rows:
                title=str(r.get("title","")); href=str(r.get("href","")); ts=str(r.get("ts",""))
                blob=(title+" "+href).upper()
                ticker_hit=bool(re.search(r"(?<![A-Z])"+re.escape(sym)+r"(?![A-Z])",blob))
                if ticker_hit and EARN_RE.search(title):
                    out.append({"event_id":e["event_id"],"historical_symbol":sym,"first_trade":trade,
                      "candidate_timestamp_text":ts,"title":title,"href":href,"archive_source":src,
                      "status":"CLUE_ONLY_REQUIRES_EXACT_RELEASE_IDENTITY_AND_FIRST_PUBLIC_VALIDATION"})
    return out

def ravenpack_candidates(events,rpdir):
    if not rpdir: return []
    rpdir=Path(rpdir)
    if not rpdir.exists(): return []
    wanted={e["historical_symbol"].upper():e for e in events}
    out=[]
    for p in sorted(list(rpdir.rglob("*.csv"))+list(rpdir.rglob("*.csv.gz"))):
        try:
            with (io.TextIOWrapper(__import__("gzip").open(p,"rb"),encoding="ISO-8859-1") if p.suffix==".gz" else p.open(encoding="ISO-8859-1")) as fh:
                rd=csv.DictReader(fh)
                for r in rd:
                    if r.get("GROUP")!="earnings" or r.get("CATEGORY")!="earnings-per-share": continue
                    if str(r.get("RELEVANCE","")) not in {"100","100.0"}: continue
                    text=" ".join(str(r.get(k,"")) for k in ("ENTITY_NAME","COMPANY","SOURCE"))
                    for sym,e in wanted.items():
                        # Ticker/entity mapping is deliberately not guessed here.
                        if re.search(r"(?<![A-Z])"+re.escape(sym)+r"(?![A-Z])",text.upper()):
                            out.append({"event_id":e["event_id"],"historical_symbol":sym,
                              "timestamp_utc":r.get("TIMESTAMP_UTC"),"entity_name":r.get("ENTITY_NAME"),
                              "source":r.get("SOURCE"),"rp_story_id":r.get("RP_STORY_ID"),
                              "event_similarity_key":r.get("EVENT_SIMILARITY_KEY"),
                              "status":"CANDIDATE_REQUIRES_ENTITY_MAPPING_RELEASE_IDENTITY_AND_CHRONOLOGY"})
        except Exception:
            continue
    return out

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--ravenpack-dir")
    a=ap.parse_args(); ev=unresolved()
    rc=reuters_candidates(ev); rp=ravenpack_candidates(ev,a.ravenpack_dir)
    payload={"schema_version":"1","research_use_only":True,"canonical_main_sha":"51d847052f163a0c61b3d9e2d74003d321a511a1",
      "unresolved_event_count":len(ev),"reuters_candidate_count":len(rc),"ravenpack_candidate_count":len(rp),
      "reuters_candidates":rc,"ravenpack_candidates":rp,
      "guardrails":["No candidate is canonical automatically.","Require exact issuer/release identity.","Require first-public chronology.","RavenPack requires lawful entitlement; no credential bypass.","Reuters corpus is discovery/corroboration unless provenance is independently sufficient."]}
    OUT.write_text(json.dumps(payload,indent=2)+"\n")
    print(json.dumps({k:payload[k] for k in ("unresolved_event_count","reuters_candidate_count","ravenpack_candidate_count")}))
if __name__=="__main__": main()
