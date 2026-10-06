# Hacked earnings walk-forward experiment

## tl;dr

This experiment fits text models only on earlier calendar years and evaluates later years. The executable outcome is the independent retrospective Actual=1 source label. The requested realized-return experiment remains fail-closed because the authorized real market-data manifest contains zero active sources.

Primary pooled years are 2012, 2013, and 2015. The source has zero Actual/Hacked observations in 2014, so 2014 is reported separately as a negative-only regime check rather than mixed into headline discrimination metrics.

## Full Universe

- Evaluated rows: **18,004**; positives: **446**; base rate: **2.477%**.
- Past-only text model: ROC AUC **0.679**, average precision **0.065**.
- Past-only text + novelty: ROC AUC **0.683**, average precision **0.068**.
- Published full-sample Soft benchmark: ROC AUC **0.522**, average precision **0.026**.
- Constant-prior baseline: ROC AUC **0.485**, average precision **0.024**.

## Hacked Only Retrospective

- Evaluated rows: **3,587**; positives: **446**; base rate: **12.434%**.
- Past-only text model: ROC AUC **0.637**, average precision **0.232**.
- Past-only text + novelty: ROC AUC **0.637**, average precision **0.238**.
- Published full-sample Soft benchmark: ROC AUC **0.499**, average precision **0.125**.
- Constant-prior baseline: ROC AUC **0.468**, average precision **0.117**.

## Return experiment status

- Authorized non-synthetic market source count: **0**.
- Real feature backfill eligible: **False**.
- Synthetic market fixtures were explicitly excluded.
- Therefore no realized-return, excess-return, Sharpe, or profitability statistic is reported.

## Leakage and robustness checks

- Duplicate text hashes crossing train/test: **0**.
- All temporal folds strictly earlier-only: **True**.
- TF-IDF vocabulary is fit separately inside each training fold.
- 2014 is retained as a negative-only source-regime diagnostic, not used to inflate AUC.
- Unseen-issuer results are exported separately and are low-power because very few Actual=1 rows occur for issuers absent from prior-year training.

## Files

- fold_metrics.csv: year-by-year results.
- pooled_metrics.csv: pooled primary-year and unseen-issuer stress tests.
- walkforward_predictions.csv: row-level predictions for audit.
- top_2015_text_terms.csv: largest 2015-fold coefficients; associative, not causal.
- leakage_checks.csv: temporal and duplicate-content assertions.
- summary.json: machine-readable experiment receipt.
