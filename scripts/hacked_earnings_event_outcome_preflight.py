#!/usr/bin/env python3
from pathlib import Path
import json, math
import numpy as np
import pandas as pd
from scipy import stats
from hacked_earnings_oos_experiment import fetch_yahoo_histories, next_session_outcome

def main():
    root=Path("data/processed/hacked_earnings_oos_preflight"); root.mkdir(parents=True,exist_ok=True)
    events=pd.read_csv("data/processed/hacked_earnings_deep/event_174_text_features.csv",dtype={"PERMNO":str,"GVKEY":str,"SYMBOL":str})
    ann=pd.read_csv("data/processed/authorized_input_real/announcement_resolutions.csv",dtype=str)
    assert len(events)==174 and len(ann)==174
    amap={(r.historical_symbol,r.event_date):r for r in ann.itertuples(index=False)}
    symbols=sorted(set(events["SYMBOL"].dropna().astype(str)))
    histories, meta=fetch_yahoo_histories(symbols,root,batch_size=80)
    spy=histories.get("SPY")
    rows=[]
    for e in events.itertuples(index=False):
        trade_date=str(e.TimeOfFirstTrade)[:10]
        a=amap.get((str(e.SYMBOL),trade_date))
        if a is None: continue
        pub=pd.Timestamp(a.public_announcement_ts)
        if pub.tzinfo is None: pub=pub.tz_localize("UTC")
        local_date=pub.tz_convert("America/New_York").date().isoformat()
        outcome=next_session_outcome(histories.get(str(e.SYMBOL)),spy,str(e.date))
        rows.append({
            "source_trade_row":int(e.source_trade_row),"event_id":a.event_id,"PERMNO":str(e.PERMNO),
            "SYMBOL":str(e.SYMBOL),"trade_date":trade_date,"text_date":str(e.date),
            "announcement_local_date":local_date,"exact_text_date_match":str(e.date)==local_date,
            "Soft":pd.to_numeric(pd.Series([e.Soft]),errors="coerce").iloc[0],
            "prior_text_jaccard_distance":pd.to_numeric(pd.Series([e.prior_text_jaccard_distance]),errors="coerce").iloc[0],
            **outcome
        })
    d=pd.DataFrame(rows)
    d.to_csv(root/"event_outcomes.csv",index=False)
    eligible=d[d["exact_text_date_match"] & d["market_adjusted_open_close_return"].notna()].copy()
    metrics={}
    for col in ["Soft","prior_text_jaccard_distance"]:
        x=eligible[[col,"market_adjusted_open_close_return"]].dropna()
        metrics[col]={
            "n":len(x),
            "pearson":float(stats.pearsonr(x[col],x["market_adjusted_open_close_return"]).statistic) if len(x)>3 else None,
            "spearman":float(stats.spearmanr(x[col],x["market_adjusted_open_close_return"]).statistic) if len(x)>3 else None,
        }
    summary={
        "events":174,"symbols":len(symbols),"histories_returned":meta.get("returned_symbols"),
        "events_with_market_adjusted_outcome":int(d["market_adjusted_open_close_return"].notna().sum()),
        "exact_text_date_matches":int(d["exact_text_date_match"].sum()),
        "primary_eligible":int(len(eligible)),"outcome_status_counts":d["outcome_status"].value_counts().to_dict(),
        "reference_metrics":metrics,"market_fetch":meta,
        "warning":"Published Soft is in-sample; novelty is descriptive. This preflight is not the OOS text-model result."
    }
    (root/"summary.json").write_text(json.dumps(summary,indent=2,default=str)+"\n")
    print(json.dumps(summary,indent=2,default=str))
if __name__=="__main__": main()
