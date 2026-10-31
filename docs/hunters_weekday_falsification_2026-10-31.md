# Golden Goose: SPY Monday intraday falsification (October 31, 2026)

**Verdict: REJECT as a validated net trading edge.** At the frozen 20-bps modeled one-leg roundtrip cost, Monday open-to-close SPY long is negative in 2013-2018 validation and both economically overlapping retrospective archives. No live prices, executable market-open fills, borrow inventory, transactions or profit claims.

## Predeclared rule and controls

- Hunter B candidate: Monday calendar weekday is known before T open. At Monday T open, hypothetically long one SPY gross notional until T close, without using T close in its own trigger. No Tuesday substitution when exchanges close for Monday holidays. Historical opening and closing prints are NOT executable order fills.
- Friday short is a separate *diagnostic negative control* only; actual borrow and associated fees have not been demonstrated. No direction flip or tuning using the results.
- Primary total roundtrip cost = 20 basis points per gross SPY notional, sensitivity = 10 and 40 bps. Net-bps formula = 10,000 × side × (raw_close / raw_open - 1) − cost. Spread, auction slippage, funding, exchange fees, taxes and borrow remain unknown.
- Frozen phases: pre-2013 train; 2013-2018 validation; 2019+ retrospective exposed sample. None is a genuinely untouched prospective holdout given earlier Hunter SPY studies. This exploratory rule has no external preregistration.
- Source parser enforces strict Git-blob SHA-1 identity, unique ordered dates, non-weekend price rows, finite positive open/close/adjusted close, and at-most-35% intraday change. Entire cohort denominator is retained, including losing entries. No third-party code, raw archived price data, or licensing rights were copied.

## Public provenance, October 31, 2026

- xjcarter/data commit: https://github.com/xjcarter/data/commit/7d705ada2d3ca483700eb695772e7de9cfc75cbc . SPY.csv blob SHA-1 5a17de0b52ed8941aacc2ba16bdc96d7c1073cff . 5,759 daily bars; 2000-01-03 through 2022-11-18.
- revred/TradeSmart.Tracker commit: https://github.com/revred/TradeSmart.Tracker/commit/7d9d769b0f2ddcedf4c1703cc979b865a37b580d . market/us/spy.csv blob SHA-1 38acc25a077e23fdf107102960c3df32f1543a7d . 3,773 daily bars; 2011-01-05 through 2026-01-06.
- Re-read those immutable source revisions via approved GitHub public-resource access: 0 invalid nonfinite/negative/move-outlier rows, 0 duplicate/unsorted dates, 0 calendar intervals >7 days per source. This run did NOT independently recompute the historical documented Git blob IDs. Neither archive's original market-data redistribution license, original vendor adjustments nor bid/ask validity is verified. The series overlap economically and are NOT independent replications; no raw-price files are committed.

## Measured retrospective means at hypothetical 20-bps costs

Figures below are triggered-session counts and mean *net basis points*, not CAGR or real P&L.

| Frozen arm | xjcarter train | Validation 2013-2018 (both archives) | xjcarter retrospective 2019+ | revred retrospective 2019+ |
|---|---:|---:|---:|---:|
| Monday long | 614 / -20.307 | 284 / **-23.213** | 183 / **-9.514** | 330 / **-7.850** |
| Friday short diagnostic | 656 / -14.677 | 303 / -20.682 | 195 / -20.437 | 354 / -23.811 |

At 10 bps, Monday validation remains -13.213 bps; post-2019 xjcarter +0.486 and revred +2.151 bps. At 40 bps all three are negative: validation -43.213, retrospective -29.514/-27.850. Break-even Monday gross means: validation -3.213 bps, retrospective +10.486/+12.151 bps. Positive gross estimates in exposed later samples are not evidence of profitable fills.

Independent in-run exploratory month-cluster bootstrap (2,500 JS LCG resamples, seed 102391; whole months resampled) gives Monday net20 95% percentile intervals: validation [-30.896, -15.855] bps in both archives; retrospective xjcarter [-21.786, +3.241], revred [-15.436, -0.369]. The repository's Python bootstrap uses a different seeded PRNG; exact finite-sample endpoints can differ. All intervals ignore data snooping, model selection, transaction uncertainty and source dependence. No statistical-significance claim.

## Reproduction, governance, next test

- Offline implementation: src/equity_weekday_audit.py; synthetic adversarial regression suite: tests/test_equity_weekday_audit.py.
- Re-run with the archived file privately obtained under permitted use rights: PYTHONPATH=src python -m equity_weekday_audit --file /private/market/SPY.csv --git-blob-sha 5a17de0b52ed8941aacc2ba16bdc96d7c1073cff . Run tests with PYTHONPATH=src python -m pytest -q tests/test_equity_weekday_audit.py .
- Additions are on existing draft Golden Goose PR #518. New code, tests and docs can be reverted alongside their scoped candidate-authored SHA-256 release-drift entries. Those hashes are NOT an independent release trust-root; required exact-head hosted CI and authorization govern any merge. No production change.
- Hunter A: Tradier Options Research retains option Greeks, eligibility and time-synchronous two-leg data; no competing experiments or brokerage calls. Hunter B: rejects this Monday rule under frozen costs. Hunter C: fail-closed input integrity, no-lookahead and cost stress tests. Priority next: independently preregistered prospective untouched dates, timestamped executable market quotes/auction fills, fees, legal market-data provenance, and (for shorts) verified borrow availability. Do not optimize already exposed SPY samples.
