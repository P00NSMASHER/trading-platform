# Validation addendum: hacked earnings walk-forward experiment

## Bottom line

The experiment found a **real cross-sectional association with the retrospective `Actual=1` label**, but it did **not** establish a trading signal.

- Strictly earlier-only text AUC: **0.679** full-universe; **0.637** Hacked-only.
- Published `Soft` AUC: **0.522** full-universe; **0.499** Hacked-only.
- Same-date text AUC: **0.687** (95% date-bootstrap CI 0.647–0.731) full-universe; **0.692** (0.652–0.736) Hacked-only.
- Same-issuer text AUC: **0.412** full-universe; **0.497** Hacked-only.
- Same-issuer-year text AUC: **0.530** full-universe; **0.490** Hacked-only.

## What that means

The text model is good at separating **types of firms / reporting styles / event populations** associated with the retrospective complaint-derived label. It is not convincing evidence that wording distinguishes which announcement from the **same company** was actually traded by the hackers. The Hacked-only same-issuer tests are essentially chance.

A smoothed earlier-history issuer baseline reaches AUC **0.552** full-universe and **0.617** Hacked-only. The text model is better cross-sectionally, including on the same date, so it is not merely memorizing each firm's historical label rate. But firm/industry/reporting-style confounding is clearly substantial.

## Time stability

The text-only AUC by year was **0.697 (2012), 0.765 (2013), and 0.640 (2015)** full-universe, and **0.641, 0.728, and 0.711** Hacked-only. The signal persists across all three positive-label years, but its strength moves materially.

## Novelty

Text novelty alone was weak in the pooled test. Adding novelty to text nudged pooled metrics only slightly, while the cluster-bootstrap checks placed the incremental AUC around zero. Keep **text-only** as the simpler challenger until a stronger incremental case exists.

## Unseen-issuer stress test

Within the Hacked-only subset, issuers absent from that fold's Hacked training history produced AUC **0.703** on **1,457** rows with **152** positives. This is encouraging but 2015-heavy; the earlier unseen-issuer slices are sparse and unstable.

## Return experiment status

The realized-return experiment remains **blocked**. The authorized non-synthetic market-data manifest reports **zero active sources**, and the public corpus has no row-level `LRet_12pm_OpenNext`. Synthetic market fixtures were excluded. No return, Sharpe, P&L, execution, or profitability claim is made.

## Reproducibility

- Final GitHub workflow run: `37431359121` — **SUCCESS**.
- Research branch: `research/hacked-earnings-walkforward-actual-20261006`.
- 36,750 text-linked rows rebuilt from pinned public assets.
- Every temporal fold trains strictly on earlier years.
- Duplicate content hash overlap across temporal train/test splits: zero.
- Same-date and same-issuer diagnostics were independently recomputed from saved row-level predictions.
- Main and the production champion were not modified.
