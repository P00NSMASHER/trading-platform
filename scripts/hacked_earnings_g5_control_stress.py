#!/usr/bin/env python3
"""Fail-closed G5 test plus maximum-feasible pre-G5 matched-control sensitivity.

Canonical conclusion is governed by g5_final_control_exclusions.json.
The proxy sensitivity is NOT canonical G5 evidence. It balances only source-derived,
pre-date reporting-style and retrospective issuer-propensity covariates because the
canonical point-in-time market/industry inputs are not complete.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import binomtest, wilcoxon

SEED = 20261006
TEST_YEARS = {2012, 2013, 2015}
COVARIATES = (
    "prior_actual_rate",
    "prior_hacked_rate",
    "prior_n",
    "prior_text_chars_mean",
    "prior_jaccard_mean",
    "last_text_chars",
    "last_jaccard",
)
LOG_COVARIATES = {"prior_n", "prior_text_chars_mean", "last_text_chars"}
MAX_COMPONENT_Z = 2.5
HARD_ABS_SMD = 0.20
CONTROLS_PER_EVENT = 3


def clean_id(series: pd.Series) -> pd.Series:
    return series.astype(str).str.replace(r"\.0$", "", regex=True)


def transform(name: str, value: float) -> float:
    if pd.isna(value):
        return np.nan
    if name in LOG_COVARIATES:
        if value < 0:
            raise ValueError(f"{name} is negative")
        return math.log1p(value)
    return float(value)


def robust_scale(values: list[float]) -> float | None:
    vals = np.asarray([v for v in values if np.isfinite(v)], dtype=float)
    if len(vals) < 2:
        return None
    med = np.median(vals)
    mad = np.median(np.abs(vals - med))
    if mad > 0:
        return float(1.4826 * mad)
    sd = float(np.std(vals, ddof=1))
    return sd if sd > 0 else None


def smd(treated: np.ndarray, controls: np.ndarray) -> float:
    tm, cm = float(np.mean(treated)), float(np.mean(controls))
    ts = float(np.std(treated, ddof=1))
    cs = float(np.std(controls, ddof=1))
    pooled = math.sqrt((ts * ts + cs * cs) / 2)
    return 0.0 if pooled == 0 else (tm - cm) / pooled


def add_prior_features(sample: pd.DataFrame) -> pd.DataFrame:
    out = sample.sort_values(["PERMNO", "date"]).reset_index(drop=True).copy()
    out["text_chars"] = pd.to_numeric(out["selected_text_characters"], errors="coerce")
    out["jaccard"] = pd.to_numeric(out["prior_text_jaccard_distance"], errors="coerce")
    grouped = out.groupby("PERMNO", sort=False, group_keys=False)
    out["prior_n"] = grouped.cumcount()
    out["prior_actual_sum"] = grouped["Actual"].transform(lambda s: s.cumsum().shift(1))
    out["prior_hacked_sum"] = grouped["Hacked"].transform(lambda s: s.cumsum().shift(1))
    out["prior_text_chars_mean"] = grouped["text_chars"].transform(
        lambda s: s.expanding().mean().shift(1)
    )
    out["prior_jaccard_mean"] = grouped["jaccard"].transform(
        lambda s: s.expanding().mean().shift(1)
    )
    out["last_text_chars"] = grouped["text_chars"].shift(1)
    out["last_jaccard"] = grouped["jaccard"].shift(1)
    base_actual = float(out["Actual"].mean())
    base_hacked = float(out["Hacked"].mean())
    out["prior_actual_rate"] = (
        out["prior_actual_sum"].fillna(0) + 20 * base_actual
    ) / (out["prior_n"] + 20)
    out["prior_hacked_rate"] = (
        out["prior_hacked_sum"].fillna(0) + 20 * base_hacked
    ) / (out["prior_n"] + 20)
    return out


def build_pairs(sample: pd.DataFrame, events: pd.DataFrame, candidates: pd.DataFrame, predictions: pd.DataFrame):
    row_map = {
        (row.PERMNO, row.date.strftime("%Y-%m-%d")): row
        for _, row in sample.iterrows()
    }
    score_map = {
        (row.PERMNO, row.date.strftime("%Y-%m-%d")): float(row.text_logit)
        for _, row in predictions.iterrows()
    }

    test = events[events["date"].dt.year.isin(TEST_YEARS)].copy()
    test["text_score"] = [
        score_map.get((p, d.strftime("%Y-%m-%d")), np.nan)
        for p, d in zip(test["PERMNO"], test["date"])
    ]
    scored = test[test["text_score"].notna()].copy()
    rows = []
    scored_candidate_event_ids = set()

    for _, event in scored.iterrows():
        date_str = event.date.strftime("%Y-%m-%d")
        treated = row_map.get((event.PERMNO, date_str))
        if treated is None:
            continue
        event_candidates = candidates[candidates["source_trade_row"] == event.source_trade_row]
        for _, candidate in event_candidates.iterrows():
            candidate_date = str(candidate.date)[:10]
            control = row_map.get((candidate.candidate_PERMNO, candidate_date))
            control_score = score_map.get((candidate.candidate_PERMNO, candidate_date))
            if control is None or control_score is None:
                continue
            if str(control.GVKEY) == str(treated.GVKEY):
                continue
            rec = {
                "source_trade_row": int(event.source_trade_row),
                "treated_permno": event.PERMNO,
                "treated_symbol": event.SYMBOL,
                "treated_gvkey": str(treated.GVKEY),
                "candidate_permno": candidate.candidate_PERMNO,
                "candidate_symbol": candidate.candidate_SYMBOL,
                "candidate_gvkey": str(control.GVKEY),
                "date": candidate_date,
                "year": int(event.date.year),
                "treated_score": float(event.text_score),
                "candidate_score": float(control_score),
            }
            for cov in COVARIATES:
                rec[f"treated_{cov}"] = getattr(treated, cov)
                rec[f"control_{cov}"] = getattr(control, cov)
            rows.append(rec)
            scored_candidate_event_ids.add(int(event.source_trade_row))

    return scored, pd.DataFrame(rows), scored_candidate_event_ids


def feasible_candidates(pairs: pd.DataFrame):
    feasible = {}
    treated_vectors = {}
    coverage = []
    for event_id, group in pairs.groupby("source_trade_row"):
        treated = {c: transform(c, group.iloc[0][f"treated_{c}"]) for c in COVARIATES}
        if any(pd.isna(v) for v in treated.values()):
            coverage.append({
                "source_trade_row": event_id,
                "status": "MISSING_TREATED_PRE_DATE_PROXY_COVARIATE",
                "complete_candidate_count": 0,
                "caliper_candidate_count": 0,
            })
            continue
        complete = group.copy()
        keep = np.ones(len(complete), dtype=bool)
        for cov in COVARIATES:
            keep &= complete[f"control_{cov}"].notna().to_numpy()
        complete = complete.loc[keep]
        if len(complete) < CONTROLS_PER_EVENT:
            coverage.append({
                "source_trade_row": event_id,
                "status": "INSUFFICIENT_COMPLETE_PROXY_CANDIDATES",
                "complete_candidate_count": len(complete),
                "caliper_candidate_count": 0,
            })
            continue

        scales = {}
        for cov in COVARIATES:
            values = [treated[cov]] + [
                transform(cov, x) for x in complete[f"control_{cov}"].values
            ]
            scales[cov] = robust_scale(values)

        candidates = []
        for idx, row in complete.iterrows():
            z_values = []
            rejected = False
            for cov in COVARIATES:
                control_value = transform(cov, row[f"control_{cov}"])
                scale = scales[cov]
                if scale is None:
                    z = 0.0 if abs(control_value - treated[cov]) <= 1e-12 else math.inf
                else:
                    z = abs(control_value - treated[cov]) / scale
                if z > MAX_COMPONENT_Z:
                    rejected = True
                    break
                z_values.append(z)
            if rejected:
                continue
            candidates.append(
                (idx, float(np.sqrt(np.mean(np.square(z_values)))), float(max(z_values)))
            )
        candidates.sort(key=lambda x: (x[1], x[2], str(pairs.loc[x[0], "candidate_symbol"])))
        if len(candidates) < CONTROLS_PER_EVENT:
            coverage.append({
                "source_trade_row": event_id,
                "status": "INSUFFICIENT_PROXY_CANDIDATES_AFTER_CALIPER",
                "complete_candidate_count": len(complete),
                "caliper_candidate_count": len(candidates),
            })
            continue
        feasible[int(event_id)] = candidates
        treated_vectors[int(event_id)] = treated
        coverage.append({
            "source_trade_row": event_id,
            "status": "PROXY_MATCHABLE",
            "complete_candidate_count": len(complete),
            "caliper_candidate_count": len(candidates),
        })
    return feasible, treated_vectors, coverage


def balance_for_selection(pairs: pd.DataFrame, selection: dict[int, list[int]], treated_vectors: dict):
    event_ids = sorted(selection)
    out = {}
    for cov in COVARIATES:
        treated = np.asarray([treated_vectors[e][cov] for e in event_ids], dtype=float)
        controls = np.asarray([
            transform(cov, pairs.loc[idx, f"control_{cov}"])
            for event_id in event_ids for idx in selection[event_id]
        ], dtype=float)
        out[cov] = smd(treated, controls)
    return out


def optimize_selection(pairs: pd.DataFrame, feasible: dict, treated_vectors: dict):
    selection = {
        event_id: [row[0] for row in candidates[:CONTROLS_PER_EVENT]]
        for event_id, candidates in feasible.items()
    }

    def objective(sel):
        balance = balance_for_selection(pairs, sel, treated_vectors)
        abs_values = [abs(v) for v in balance.values()]
        return (max(abs_values), float(np.mean(abs_values)))

    current_obj = objective(selection)
    for _ in range(5):
        best = None
        for event_id in sorted(selection):
            current = selection[event_id]
            pool = [x[0] for x in feasible[event_id]]
            for pos, old in enumerate(current):
                for new in pool:
                    if new in current:
                        continue
                    trial = {k: list(v) for k, v in selection.items()}
                    trial[event_id][pos] = new
                    obj = objective(trial)
                    candidate_key = (obj, event_id, pos, str(pairs.loc[new, "candidate_symbol"]))
                    if best is None or candidate_key < best[0]:
                        best = (candidate_key, trial)
        if best is None or best[0][0] >= current_obj:
            break
        selection = best[1]
        current_obj = best[0][0]

    return selection, balance_for_selection(pairs, selection, treated_vectors)


def randomization_test(matched: pd.DataFrame, reps: int = 20000):
    event_effects = []
    groups = []
    for event_id, group in matched.groupby("source_trade_row"):
        treated_score = float(group.iloc[0]["treated_score"])
        control_scores = group["candidate_score"].astype(float).to_numpy()
        groups.append(np.r_[treated_score, control_scores])
        event_effects.append({
            "source_trade_row": int(event_id),
            "year": int(group.iloc[0]["year"]),
            "date": group.iloc[0]["date"],
            "treated_symbol": group.iloc[0]["treated_symbol"],
            "treated_score": treated_score,
            "control_mean_score": float(control_scores.mean()),
            "control_max_score": float(control_scores.max()),
            "treated_minus_control_mean": float(treated_score - control_scores.mean()),
            "treated_highest_in_set": int(treated_score > control_scores.max()),
        })
    effects = pd.DataFrame(event_effects)
    observed = float(effects["treated_minus_control_mean"].mean())
    rng = np.random.default_rng(SEED)
    randomized = np.empty(reps, dtype=float)
    for i in range(reps):
        diffs = []
        for scores in groups:
            j = int(rng.integers(0, 4))
            diffs.append(float(scores[j] - (scores.sum() - scores[j]) / 3))
        randomized[i] = float(np.mean(diffs))
    p = float((1 + np.sum(randomized >= observed - 1e-15)) / (reps + 1))
    return effects, observed, p


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.repo_root
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)

    g5 = json.loads(
        (root / "data/processed/authorized_input_real/g5_final_control_exclusions.json").read_text()
    )
    g5_state = g5["g5_state"]
    if int(g5_state["point_in_time_resolved_dates"]) != 0:
        raise ValueError("Canonical G5 state changed; rerun against newly resolved controls.")
    if int(g5_state["model_evaluation_eligible_dates"]) != 0:
        raise ValueError("Canonical G5 state unexpectedly contains eligible dates.")

    sample = pd.read_csv(root / "data/processed/hacked_earnings_deep/sample_text_features.csv")
    events = pd.read_csv(root / "data/processed/hacked_earnings_deep/event_174_text_features.csv")
    candidates = pd.read_csv(root / "data/processed/hacked_earnings_deep/same_day_control_candidates.csv")
    predictions = pd.read_csv(root / "data/processed/hacked_earnings_walkforward/walkforward_predictions.csv")
    predictions = predictions[predictions["pool"] == "full_universe"].copy()

    for df in (sample, events, predictions):
        df["PERMNO"] = clean_id(df["PERMNO"])
    candidates["treated_PERMNO"] = clean_id(candidates["treated_PERMNO"])
    candidates["candidate_PERMNO"] = clean_id(candidates["candidate_PERMNO"])

    sample["date"] = pd.to_datetime(sample["date"])
    events["date"] = pd.to_datetime(events["date"])
    predictions["date"] = pd.to_datetime(predictions["date"])
    sample = add_prior_features(sample)

    scored, pairs, candidate_event_ids = build_pairs(sample, events, candidates, predictions)
    missing_score_controls = sorted(
        set(scored["source_trade_row"].astype(int)) - set(candidate_event_ids)
    )
    feasible, treated_vectors, coverage = feasible_candidates(pairs)
    selection, balance = optimize_selection(pairs, feasible, treated_vectors)

    matched_rows = []
    distance_map = {
        event_id: {idx: (distance, max_z) for idx, distance, max_z in rows}
        for event_id, rows in feasible.items()
    }
    for event_id in sorted(selection):
        for rank, idx in enumerate(selection[event_id], 1):
            row = pairs.loc[idx].to_dict()
            distance, max_z = distance_map[event_id][idx]
            row.update({
                "control_rank": rank,
                "proxy_match_distance": distance,
                "max_component_z": max_z,
                "canonical_g5_credit": 0,
                "research_use_only": 1,
            })
            matched_rows.append(row)
    matched = pd.DataFrame(matched_rows)

    if any(abs(v) > HARD_ABS_SMD + 1e-12 for v in balance.values()):
        raise ValueError(f"Proxy matching failed hard balance rule: {balance}")
    if any(float(v) > MAX_COMPONENT_Z + 1e-12 for v in matched["max_component_z"]):
        raise ValueError("Proxy matched set violates component caliper")

    effects, observed, randomization_p = randomization_test(matched)
    top_count = int(effects["treated_highest_in_set"].sum())
    top_p = float(
        binomtest(top_count, len(effects), 0.25, alternative="greater").pvalue
    )
    wilcoxon_result = wilcoxon(
        effects["treated_minus_control_mean"], alternative="greater"
    )
    pairwise_win_rate = float(
        (matched["treated_score"] > matched["candidate_score"]).mean()
    )

    balance_rows = [
        {
            "covariate": cov,
            "smd_after": value,
            "abs_smd_after": abs(value),
            "hard_abs_smd_limit": HARD_ABS_SMD,
            "hard_balance_pass": int(abs(value) <= HARD_ABS_SMD),
        }
        for cov, value in balance.items()
    ]
    coverage_df = pd.DataFrame(coverage)
    if missing_score_controls:
        coverage_df = pd.concat([
            coverage_df,
            pd.DataFrame([{
                "source_trade_row": event_id,
                "status": "NO_SCORED_SAME_DATE_CONTROL",
                "complete_candidate_count": 0,
                "caliper_candidate_count": 0,
            } for event_id in missing_score_controls])
        ], ignore_index=True)

    matched.to_csv(out / "proxy_matched_controls.csv", index=False)
    effects.to_csv(out / "proxy_event_effects.csv", index=False)
    pd.DataFrame(balance_rows).to_csv(out / "proxy_balance.csv", index=False)
    coverage_df.sort_values("source_trade_row").to_csv(out / "proxy_coverage.csv", index=False)

    year_stats = (
        effects.groupby("year")
        .agg(
            matched_events=("source_trade_row", "size"),
            mean_score_difference=("treated_minus_control_mean", "mean"),
            median_score_difference=("treated_minus_control_mean", "median"),
            treated_highest_rate=("treated_highest_in_set", "mean"),
        )
        .reset_index()
    )
    year_stats.to_csv(out / "proxy_year_results.csv", index=False)

    summary = {
        "status": "CANONICAL_G5_BLOCKED_PROXY_SENSITIVITY_COMPLETED",
        "canonical_g5": {
            "required_event_dates": int(g5_state["required_event_dates"]),
            "point_in_time_resolved_dates": int(g5_state["point_in_time_resolved_dates"]),
            "model_evaluation_eligible_dates": int(g5_state["model_evaluation_eligible_dates"]),
            "reviewed_excluded_dates": int(g5_state["reviewed_excluded_dates"]),
            "strict_g5_text_score_test_executed": False,
            "reason": "No canonical G5-quality matched-control date is model-evaluation eligible.",
            "required_covariates": g5["evidence_boundary"]["required_covariates"],
        },
        "proxy_sensitivity": {
            "label": "PRE_G5_SOURCE_DERIVED_SENSITIVITY_NOT_CANONICAL_G5",
            "earlier_only_scored_core_events": int(len(scored)),
            "events_with_any_scored_same_date_control": int(len(candidate_event_ids)),
            "proxy_matchable_events": int(len(selection)),
            "controls_per_event": CONTROLS_PER_EVENT,
            "matched_control_rows": int(len(matched)),
            "exact_same_release_date_required": True,
            "same_issuer_controls_excluded": True,
            "max_component_z": MAX_COMPONENT_Z,
            "hard_abs_smd_limit": HARD_ABS_SMD,
            "max_abs_smd_observed": float(max(abs(v) for v in balance.values())),
            "covariates": list(COVARIATES),
            "covered_dimensions": [
                "reporting_style_history",
                "retrospective_issuer_propensity",
                "issuer_release_history_depth",
                "exact_calendar_date",
            ],
            "uncovered_requested_dimensions": [
                "canonical_point_in_time_industry",
                "market_cap_size",
                "market_liquidity",
                "pre_event_market_behavior",
            ],
            "mean_treated_minus_control_score": observed,
            "median_treated_minus_control_score": float(
                effects["treated_minus_control_mean"].median()
            ),
            "pairwise_treated_score_win_rate": pairwise_win_rate,
            "treated_highest_in_four_count": top_count,
            "treated_highest_in_four_rate": float(top_count / len(effects)),
            "treated_highest_null_rate": 0.25,
            "treated_highest_binomial_p_one_sided": top_p,
            "randomization_reps": 20000,
            "matched_set_randomization_p_one_sided": randomization_p,
            "wilcoxon_statistic": float(wilcoxon_result.statistic),
            "wilcoxon_p_one_sided": float(wilcoxon_result.pvalue),
        },
        "interpretation": (
            "The earlier-only text score remains higher for the treated first-trade events "
            "in a small, aggressively balanced source-derived subset, but canonical G5 "
            "industry/size/liquidity/market-history balance cannot yet be tested because "
            "the project has zero model-evaluation-eligible G5 dates."
        ),
        "prohibited_claims": [
            "canonical_G5_validation",
            "causal_effect",
            "trading_profitability",
            "return_prediction",
            "live_signal",
        ],
    }
    (out / "summary.json").write_text(
        json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )

    report = f"""# Earlier-only text score vs matched controls

## Bottom line

The strict canonical G5 experiment cannot yet execute: **0 of 72 event dates are model-evaluation eligible** under the repository's fail-closed G5 dossier.

A separate pre-G5 sensitivity test was completed without changing that verdict. It matched exactly three same-date controls for **{len(effects)}** core events using only source-derived pre-date reporting-style and issuer-propensity covariates, with every matched component inside **{MAX_COMPONENT_Z} robust standardized units** and all post-match absolute SMDs at or below **{HARD_ABS_SMD:.2f}**.

Within that deliberately narrow subset:

- mean treated-minus-control text score: **{observed:.6f}**
- median treated-minus-control text score: **{effects['treated_minus_control_mean'].median():.6f}**
- treated score beat an individual matched control **{pairwise_win_rate:.1%}** of pairwise comparisons
- treated event had the highest score in its four-name set **{top_count}/{len(effects)} = {top_count/len(effects):.1%}**, versus a 25% random-ranking null
- matched-set randomization p-value: **{randomization_p:.4f}**
- one-sided Wilcoxon p-value: **{wilcoxon_result.pvalue:.4f}**

## What this does and does not establish

This sensitivity says the cross-sectional text result does not immediately disappear after aggressive balancing on **prior reporting behavior and retrospective issuer propensity**.

It is **not a G5-quality result**. Canonical G5 still lacks admissible point-in-time balance for industry, market-cap size, market liquidity, and pre-event market behavior. Those dimensions are precisely the ones most capable of explaining the remaining cross-sectional text signal.

## Coverage

The earlier-only score exists for **{len(scored)}** core 2012/2013/2015 events. Only **{len(selection)}** survive the strict three-control proxy matching rule, so the sensitivity is selective and mostly reflects 2015. Rejected events remain rejected rather than being rescued with weaker matches.

## Balance

Maximum observed absolute post-match SMD across the seven proxy covariates is **{max(abs(v) for v in balance.values()):.3f}**, below the project hard limit of **0.20**.

## Decision

Keep the earlier-only text score as a research challenger, but do not promote it. The decisive next test remains the true G5 match using point-in-time industry, market-cap, liquidity, and 21-day market-history covariates. If the effect survives that test, the company-type confounding objection becomes materially weaker.
"""
    (out / "REPORT.md").write_text(report, encoding="utf-8")
    print(json.dumps(summary, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
