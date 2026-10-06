#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, math
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

REQUIRED_G5 = [
    "sector","index_bucket","market_cap","price","trailing_21d_vol",
    "normal_minute_volume","normal_minute_turnover","normal_relative_spread",
    "option_liquidity","institutional_ownership","analyst_coverage",
    "borrow_cost","pre_event_return"
]

def auc(y,s):
    y=np.asarray(y,int); s=np.asarray(s,float)
    return float(roc_auc_score(y,s)) if len(np.unique(y))==2 else None

def zframe(df, cols):
    out=df[cols].copy()
    for c in cols:
        med=out[c].median()
        out[c]=out[c].fillna(med)
        sd=out[c].std(ddof=0)
        out[c]=(out[c]-out[c].mean())/(sd if sd and np.isfinite(sd) else 1.0)
    return out

def run(repo:Path, out:Path):
    out.mkdir(parents=True,exist_ok=True)
    excl=json.loads((repo/"data/processed/authorized_input_real/g5_final_control_exclusions.json").read_text())
    g5=excl["g5_state"]
    strict={
        "status":"BLOCKED_ZERO_G5_MODEL_EVALUATION_ELIGIBLE_DATES",
        "required_event_dates":g5["required_event_dates"],
        "point_in_time_resolved_dates":g5["point_in_time_resolved_dates"],
        "model_evaluation_eligible_dates":g5["model_evaluation_eligible_dates"],
        "reviewed_excluded_dates":g5["reviewed_excluded_dates"],
        "required_covariates":excl["evidence_boundary"]["required_covariates"],
        "generator_default_covariates":REQUIRED_G5,
        "retrospective_samplefirms_as_live_controls_prohibited":g5["retrospective_samplefirms_as_live_controls_prohibited"],
        "strict_test_executed":True,
        "g5_quality_result_available":False
    }
    pred=pd.read_csv(repo/"data/processed/hacked_earnings_walkforward/walkforward_predictions.csv")
    feat=pd.read_csv(repo/"data/processed/hacked_earnings_deep/sample_text_features.csv")
    pred=pred[pred["pool"].eq("hacked_only_retrospective") & pred["test_year"].isin([2012,2013,2015])].copy()
    feat["PERMNO"]=feat["PERMNO"].astype(str); pred["PERMNO"]=pred["PERMNO"].astype(str)
    feat["date"]=feat["date"].astype(str); pred["date"]=pred["date"].astype(str)
    keep=["PERMNO","date","selected_text_characters","prior_text_jaccard_distance"]
    m=pred.merge(feat[keep],on=["PERMNO","date"],how="left",validate="one_to_one")
    m["dt"]=pd.to_datetime(m["date"]); m["quarter"]=m["dt"].dt.to_period("Q").astype(str)
    m["log_text_chars"]=np.log1p(pd.to_numeric(m["selected_text_characters"],errors="coerce"))
    m["novelty"]=pd.to_numeric(m["prior_text_jaccard_distance"],errors="coerce")

    # Strictly earlier issuer history within the scored Hacked-only universe.
    m=m.sort_values(["dt","PERMNO"]).reset_index(drop=True)
    prior_n=[]; prior_pos=[]
    counts={}; poss={}
    for _,r in m.iterrows():
        k=r["GVKEY"]
        prior_n.append(counts.get(k,0)); prior_pos.append(poss.get(k,0))
        counts[k]=counts.get(k,0)+1
        poss[k]=poss.get(k,0)+int(r["Actual"])
    m["prior_issuer_n"]=prior_n
    m["prior_issuer_rate"]=[(p+0.5)/(n+1.0) for p,n in zip(prior_pos,prior_n)]

    # Partial retrospective match: same quarter, Hacked-only, outcome-negative controls,
    # nearest on issuer propensity + reporting-style variables. Not G5.
    cols=["prior_issuer_rate","log_text_chars","novelty"]
    z=zframe(m,cols); 
    for c in cols: m["_z_"+c]=z[c]
    treated=m[m["Actual"].eq(1)].copy()
    controls=m[m["Actual"].eq(0)].copy()
    rows=[]
    for i,t in treated.iterrows():
        pool=controls[controls["quarter"].eq(t["quarter"]) & ~controls["GVKEY"].eq(t["GVKEY"])].copy()
        if len(pool)<3: continue
        dist=np.zeros(len(pool))
        for c in cols:
            dist+=(pool["_z_"+c].to_numpy()-t["_z_"+c])**2
        pool=pool.assign(distance=np.sqrt(dist/len(cols))).sort_values(["distance","PERMNO","date"]).head(3)
        for rank,(_,c) in enumerate(pool.iterrows(),1):
            rows.append({
                "treated_permno":t["PERMNO"],"treated_gvkey":t["GVKEY"],"treated_date":t["date"],
                "control_permno":c["PERMNO"],"control_gvkey":c["GVKEY"],"control_date":c["date"],
                "quarter":t["quarter"],"rank":rank,"distance":c["distance"],
                "treated_text_score":t["text_logit"],"control_text_score":c["text_logit"],
                "treated_text_novelty_score":t["text_novelty_logit"],"control_text_novelty_score":c["text_novelty_logit"]
            })
    pairs=pd.DataFrame(rows)
    if len(pairs):
        event=pairs.groupby(["treated_permno","treated_gvkey","treated_date"],as_index=False).agg(
            treated_text_score=("treated_text_score","first"),
            matched_control_text_score=("control_text_score","mean"),
            treated_text_novelty_score=("treated_text_novelty_score","first"),
            matched_control_text_novelty_score=("control_text_novelty_score","mean"),
            mean_distance=("distance","mean")
        )
        event["text_score_diff"]=event["treated_text_score"]-event["matched_control_text_score"]
        event["text_novelty_score_diff"]=event["treated_text_novelty_score"]-event["matched_control_text_novelty_score"]
        partial={
            "status":"COMPLETED_NON_G5_RETROSPECTIVE_PARTIAL_MATCH",
            "matched_treated_events":int(len(event)),
            "matched_pairs":int(len(pairs)),
            "matching_exact_fields":["calendar_quarter","Hacked=1","different_issuer","control_Actual=0"],
            "matching_numeric_fields":cols,
            "missing_required_g5_dimensions":[
                "sector/index_bucket","market_cap/price","21d volatility",
                "normal volume/turnover/spread","option liquidity",
                "institutional ownership","analyst coverage","borrow cost","pre-event return"
            ],
            "mean_text_score_diff":float(event["text_score_diff"].mean()),
            "median_text_score_diff":float(event["text_score_diff"].median()),
            "treated_beats_matched_control_rate":float((event["text_score_diff"]>0).mean()),
            "mean_text_novelty_score_diff":float(event["text_novelty_score_diff"].mean()),
            "treated_beats_matched_control_rate_text_novelty":float((event["text_novelty_score_diff"]>0).mean()),
            "g5_quality":False
        }
        pairs.to_csv(out/"partial_matched_pairs.csv",index=False)
        event.to_csv(out/"partial_matched_event_results.csv",index=False)
    else:
        partial={"status":"NO_PARTIAL_MATCHES","g5_quality":False}

    result={"strict_g5":strict,"partial_falsification":partial,
            "interpretation":"No G5-quality causal/control result can be produced until admitted point-in-time matching covariates exist. Partial matching is a falsification diagnostic only."}
    (out/"summary.json").write_text(json.dumps(result,indent=2)+"\n")
    gaps=pd.DataFrame([{"required_dimension":x,"available_for_g5_model_evaluation":False} for x in REQUIRED_G5])
    gaps.to_csv(out/"g5_required_data_gaps.csv",index=False)
    report=[
      "# Earlier-only text score vs G5-quality controls",
      "",
      "## Strict result",
      "",
      f"**BLOCKED:** {strict['model_evaluation_eligible_dates']} of {strict['required_event_dates']} event dates are eligible for genuine G5 model-evaluation matching.",
      f"All {strict['reviewed_excluded_dates']} dates are fail-closed reviewed exclusions.",
      "",
      "The repository explicitly prohibits treating retrospective SampleFirms rows as live/G5 control evidence. Therefore this run does not fabricate a G5 result.",
      "",
      "## Partial falsification",
      "",
      json.dumps(partial,indent=2),
      "",
      "This secondary diagnostic matches only on calendar quarter, earlier issuer propensity, and reporting-style measures. It omits the G5 dimensions that are currently unavailable and must not be described as G5-quality.",
      ""
    ]
    (out/"REPORT.md").write_text("\n".join(report))
    print(json.dumps(result,indent=2))
    return result

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--repo",type=Path,default=Path("."))
    p.add_argument("--output",type=Path,default=Path("data/processed/hacked_earnings_g5_match"))
    a=p.parse_args()
    run(a.repo,a.output)
