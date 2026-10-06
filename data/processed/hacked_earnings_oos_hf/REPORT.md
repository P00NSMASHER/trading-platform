# Out-of-time hacked-earnings text experiment

## Executive Summary

The experiment produced **92 leakage-screened event predictions across 81 issuers** using exact G1 public-release dates for test eligibility and earlier-calendar-year training only.

The primary issuer/duplicate-purged text model has Spearman IC **0.042**, Pearson IC **0.056**, and top-minus-bottom descriptive next-session market-adjusted outcome **0.17%**. Year-block permutation p-value for the rank relationship is **0.712**.

The language-change-only model has Spearman IC **-0.040**. The original published Soft score is shown only as an in-sample reference (Spearman **-0.002**) and is not credited as out-of-time evidence.

## Design

- Test years: 2011–2015. Each year is scored by a model trained only on earlier calendar years.
- Primary model removes all earlier observations from issuers appearing in that test year and any training text identical to held-out text.
- Hyperparameter selection uses grouped folds over connected issuer/content components.
- Outcome is the next trading session's open-to-close stock return minus SPY's same-session return, with the session strictly after the text date.
- Test text is admitted only when its archive date equals the independently resolved G1 public-announcement date in New York time.

## Coverage

- Source text observations: 36,750
- Source text rows with usable market-adjusted outcome: 18,025 (49.0%)
- Core events with text: 160 / 174
- Core events whose text date matches exact G1 public-release date: 174 / 174
- Final leakage-screened evaluation rows: 92

## Predictor comparison

| Predictor | N | Spearman | Pearson | Direction | Top-bottom outcome | Permutation p |
|---|---:|---:|---:|---:|---:|---:|
| oos_text_issuer_duplicate_purged | 92 | 0.042 | 0.056 | 50.00% | 0.17% | 0.712 |
| oos_text_all_prior | 92 | 0.040 | 0.075 | 45.65% | 0.58% | 0.686 |
| oos_novelty_only | 92 | -0.040 | -0.102 | 44.57% | -0.13% | 0.636 |
| published_soft_reference | 92 | -0.002 | 0.018 | 51.09% | 0.55% | 0.985 |

## Interpretation guardrails

- Yahoo Finance daily bars are exploratory public outcome data, not canonical G2 market-data evidence.
- Training press-release dates are source archive dates, not independently verified exact release clocks; using only prior calendar years prevents same-day look-ahead into held-out years.
- Primary test features require the archive text date to equal the independently resolved G1 public-announcement date in America/New_York.
- Next-session open-to-close return deliberately omits immediate after-hours/overnight reaction and intraday microstructure.
- Ticker-only public price retrieval can miss delisted or renamed securities; missing outcomes are excluded and coverage is reported.
- The 174 core events are selected historical illicit-trading cases, not a random population of earnings announcements.
- Published Soft is an optimistic in-sample reference and is not treated as a fair out-of-time benchmark.
- Top-minus-bottom values are descriptive outcome spreads, not executable portfolio returns; no costs, capacity, or slippage are modeled.

## Artifacts

event_predictions.csv contains held-out event predictions and realized outcomes. overall_metrics.csv and year_metrics.csv contain aggregate and year-specific diagnostics. year_model_receipts.json records training-set sizes, vocabulary sizes, CV grouping and selected alpha for every yearly fit.
