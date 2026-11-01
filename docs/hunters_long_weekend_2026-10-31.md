# Golden Goose Hunter A/B/C: SPY post-long-weekend audit (2026-10-31)

**Verdict: REJECT the predeclared LONG-only, intraday post-long-weekend trade as a reproducible after-cost edge.** No orders or executable fills; 20-bps complete round-trip friction is modeled, not observed. Existing Tradier option experiments and PR #523 were not modified.

## Frozen hypothesis and data
Before calculating signal outcomes: when a SPY regular session follows >=4 calendar days since the previous observed NYSE session, hypothetically enter LONG at that day's reported OPEN and exit at CLOSE. Stress 10, 20 and 30 bps complete round-trip cost. Controls: regular 3-day weekend and 1-day gap. Never derive entry from same-day CLOSE. Train 2011-2012, validation 2013-2018, retrospective holdout 2019-2022. Optional 2023-2025 extension is single-archive, already historically observable and therefore NOT prospective independent validation.

Immutable archives: [xjcarter/data SPY.csv](https://github.com/xjcarter/data/blob/7d705ada2d3ca483700eb695772e7de9cfc75cbc/SPY.csv) (Git blob 5a17de0b52ed8941aacc2ba16bdc96d7c1073cff), [revred/TradeSmart.Tracker spy.csv](https://github.com/revred/TradeSmart.Tracker/blob/7d9d769b0f2ddcedf4c1703cc979b865a37b580d/market/us/spy.csv) (Git blob 38acc25a077e23fdf107102960c3df32f1543a7d). Retrieved 2026-10-31. There are exactly 2,990 matching dates in 2011-01-05 to 2022-11-18, zero unmatched dates and max difference in open-to-close returns 0.0007585 bps. The two archives reflect the SAME underlying market, not independent vendors/replications; vendor provenance, adjustment methodology and redistribution rights are NOT established. No raw prices are committed.

| Cohort | >=4-day gap events | Gross bps/event | Net at 10bps | Net at 20bps | Net at 30bps |
|---|---:|---:|---:|---:|---:|
| Training 2011-12 | 14 | +8.077 | -1.923 | **-11.923** | -21.923 |
| Validation 2013-18 | 39 | -3.555 | -13.555 | **-23.555** | -33.555 |
| Retrospective holdout 2019-22 | 27 | -13.030 | -23.030 | **-33.030** | -43.030 |
| Single-source 2023-25 | 20 | -19.684 | -29.684 | **-39.684** | -49.684 |

Controls, same 20-bps assumed friction: ordinary 3-day weekend = -18.671 (n=90) train, -23.485 (n=274) validation, -9.335 (n=175) retrospective holdout, -2.698 (n=137) extension. Single-gap weekday control = -18.813 (n=391), -17.849 (n=1181), -18.927 (n=771), -18.218 (n=584). These controls are NOT promoted to investable strategies.

These figures were independently calculated directly from the immutable GitHub archive contents via an exact-date JavaScript reconciliation, without source-data copying. The accompanying source-blob-pinned offline Python audit and synthetic tests enable independent repetition, but are not themselves executable-fill evidence. The 2023-2025 single-source extension does NOT verify a vendor-independent holdout. Shorting on long weekends was NOT the predeclared hypothesis; flipping direction after seeing losses would be data snooping.

## Research context and limitations
Prior art already documents different holiday effects, including Tsiakas (2010), 'The Economic Gains of Trading Stocks Around Holidays' (https://doi.org/10.1111/j.1475-6803.2009.01260.x), Pettengill (1989) (https://doi.org/10.1111/j.1475-6803.1989.tb00101.x) and a 2025 paper on US federal-holiday abnormal returns (https://doi.org/10.1002/rfe.70018). This result is NOT a novelty claim. Small and correlated event counts, open/close print execution, trading costs and possible secondary-data transformations preclude profitable-edge or formal-significance claims. A >=4-day observed market gap may include unscheduled closures or data omissions. The implementation rejects >7-day unexplained gaps and refuses disagreement between source calendars.

## Reproduce and rollback
After checking data-use rights, place source files outside the repository. Run:

    PYTHONPATH=src python -m equity_long_weekend_audit --first-file /private/SPY_xjcarter.csv --first-blob 5a17de0b52ed8941aacc2ba16bdc96d7c1073cff --second-file /private/spy_revred.csv --second-blob 38acc25a077e23fdf107102960c3df32f1543a7d --include-second-source-2023-2025
    PYTHONPATH=src python -m pytest -q tests/test_equity_long_weekend_audit.py

Rollback: close/revert this isolated research PR; no existing signals, APIs, Tradier tasks, markets, fees, production workflows, or protected release procedures changed. Next best experiment: controlled, timestamped real opening bid/ask observation and conservative out-of-sample paper tracking with source rights established.


## Hunter checkpoint 2: calendar contamination and matched-year negative control (2026-10-31)

**No tradeable edge validated.** This is an exploratory robustness audit of the *existing*
rejected LONG-only rule, **not** a registered new short strategy or independent holdout.
The original hypothesis and its event counts remain unchanged. Data and source blobs
are unchanged, and no raw market bars are committed.

Before running these controls, the follow-up diagnostic was frozen as: compare >=4-day
gap intraday gross returns with **3-day regular-weekend** gross returns in the same
years; report pooled difference, equal-weight mean of yearly differences, and
leave-one-year-out range (when >=3 matched years). The same assumed 20-bps
round-trip friction cancels between these *hypothetical* trades. This does
not correct different weekdays, selection bias, ordinary price prints versus
executable quotes, dependence, or nonindependent price archives.

| Cohort | >=4-day / 3-day sessions | Pooled long-minus-3-day gross bps | Equal-year difference bps | Leave-one-year-out equal-year range bps |
|---|---:|---:|---:|---:|
| 2011-12 train | 14 / 90 | +6.747 | +7.056 | insufficient years |
| 2013-18 validation | 39 / 274 | -0.070 | -1.217 | -6.319 to +4.949 |
| 2019-22 retrospective holdout | 27 / 175 | -23.696 | -23.732 | -33.317 to -11.090 |
| 2023-25 single-archive extension | 20 / 137 | -36.986 | -36.806 | -44.099 to -31.119 |

The event signature varies by historical period. Negative differences observed
after seeing the data **do not justify reversing direction**, because that
would select a strategy post hoc. A 3-day-weekend control also changes
weekday composition, so differences must not be called a causal holiday
effect or statistically significant.

**New data-quality finding:** the >=4-calendar-day classification includes
**2012-10-31**, following a **5-day observed gap** after 2012-10-26.
NYSE and Nasdaq were closed 2012-10-29 and 2012-10-30 for Hurricane
Sandy, a non-holiday market closure. Contemporary AP reporting:
https://www.cbsnews.com/news/new-york-stock-exchange-to-reopen-wednesday/
The first pinned archive records that 2012-10-31 SPY intraday return as
**-35.248 bps**. Exploratory exclusion of *all >=5-day observed gaps*
changes 2011-12 long-event count from 14 to 13 and its gross mean from
+8.077 to +11.409 bps/event; at an assumed 20-bps round trip, it remains
negative at **-8.591 bps/event**. This is a labeled sensitivity test, not
a retuned discovery. The new code flags such dates for calendar verification
instead of silently dropping them. No >=5-day events appear in the
analyzed 2013-2025 extension.

**Prior-art/multiple-testing warning:** Bailey et al. (2017),
https://doi.org/10.21314/JCF.2016.322,
explain how strategy selection using historic backtests can overfit.
No formal hypothesis-test p-values or vendor-independent forward results
are asserted here. No NYSE official schedule reconciliation or data license
clearance has yet been completed.

**Reproduce:** the existing pinned-blob CLI command now includes
`exploratory_gap_control` per cohort. The new synthetic tests cover
matched-year arithmetic, year deletion, unmatched cohorts, Sandy flagging,
and invariant primary event totals.

**Owner coordination:** Tradier-options joint quote/depth draft
https://github.com/P00NSMASHER/trading-platform/pull/512
was read, not modified. Missing trusted executable quotes and paper
outcomes remain the options bottleneck; no API calls or live orders.

**Ranked next test:** obtain permitted timestamped OPEN/CLOSE bid/ask or
NBBO data for the candidate equity entry/exit points and an independent
verified NYSE exchange schedule; run a preregistered 2026+ prospective
paper ledger with honest friction and zero selective omissions.


## Hunter checkpoint 3: weekday/year confounding (2026-10-31)

**Disposition: REJECT the original LONG rule; no profitable executable edge or independent forward confirmation.**
This additional *post-hoc diagnostic* controls for one obvious holiday anomaly:
most long gaps resume on different weekdays than ordinary weekends. For each
original >=4-calendar-day-gap event, subtract the average OPEN-to-CLOSE gross
return of **every session with a <4-day gap in that same calendar year and
weekday**. Each event must have a matched control or the entire cohort fails
closed; controls are never selected by their outcomes. Compare event-weighted
and equal-year effects, then delete one entire year at a time. This is a
retrospective benchmark using the *whole year's returns*, including dates
after a hypothetical entry, and explicitly cannot serve as a point-in-time
prediction, tradable benchmark or formal causal identification.

| Source-constrained cohort | Long events matched | Non-long-gap control sessions | Event-weighted event-minus-weekday/year gross bps | Equal-year mean bps | Leave-one-year-out equal-year range bps |
|---|---:|---:|---:|---:|---:|
| 2011-12 train, dual-archive overlap | 14/14 | 485 | **-7.729** | -7.729 | too few years |
| 2013-18 validation, dual-archive overlap | 39/39 | 1,471 | **-5.860** | -6.736 | -14.143 to +1.914 |
| 2019-22 retrospective holdout (through 2022-11-18), dual-archive overlap | 27/27 | 953 | **-12.177** | -12.419 | -23.864 to -4.848 |
| 2023-25 single-archive retrospective extension | 20/20 | 732 | **-29.030** | -28.302 | -40.355 to -19.889 |

The matched-source period has 2,990 aligned trading sessions and at most
0.000759 bps OPEN-to-CLOSE return disagreement. These archives are *not two
economically independent vendors*. Exact pinned Git blobs and source addresses
are listed above. Values independently computed in JavaScript directly from
both linked immutable GitHub source contents, using UTC session dates; the
testable Python implementation accepts the same pre-existing source hash
checks and does not commit the underlying unlicensed vendor bars. Any source
reuse remains subject to checking original data permissions.

**Interpretation and adverse evidence:** the negative measured relative
differences persist in the later periods after a simple weekday/year control,
but a 2015 yearly effect is positive, 2022's is +21.917 bps, and the 2013-18
leave-one-year-out range includes zero. Constant matched round-trip assumed
costs cancel from a *difference*, but open/close print marks are not
executable bid/ask fills and actual costs can differ by holiday. The study is
post-hoc, events are few and correlated, there are multiple prior tested
hypotheses, and a genuine exchange-session calendar has not been reconciled.
No p-values, trading significance or reverse-direction alpha are claimed.

**Prior art / confound:** weekday effects have been documented (Berument and
Kiymaz, 2001, https://doi.org/10.1007/bf02744521); SPY intraday weekday
effects are discussed in
https://www.cxoadvisory.com/calendar-effects/spy-by-day-of-week-and-overnight/.
Hurricane Sandy's 2012-10-29/30 unscheduled NYSE closures were documented
on 2012-10-30:
https://www.cbsnews.com/news/new-york-stock-exchange-to-reopen-wednesday/.
No universal novelty claim.

**Verification:** new `same_year_weekday_diagnostics` is wired into the
existing offline `evaluate` cohort report, with six synthetic/adversarial
regressions (year/weekday matching, unequal-year weighting, unmatched-event
fail-closed, event exclusion, no-event behavior, frozen primary strategy).
Run: `PYTHONPATH=src python -m pytest -q tests/test_equity_long_weekend_audit.py`.
No new dependencies, broker paths, order access or data redistribution.
Exact-head GitHub CI is the required arbiter; do **not** infer that the tests
pass merely because this source is committed.

**Ranked next experiments (all paper-only):**
1. Source-authorized 2026+ timestamped executable SPY NBBO/auction observations
   at both entry and exit; compare actual spreads, fees, adverse selection and
   slippage with 10/20/30-bps assumptions, and independently verify NYSE
   closures/session completeness before making any new signal claims.
2. Prospective, frozen out-of-sample long-gap cohort with fixed sample and
   cost/power gates, recorded before observing outcomes; report all dates and
   uncertainty, including null results.
3. Coordinate with the separate Tradier Options Research task on its v4.8
   $100 slippage-stress risk-cap patch and quote-consistency issue; do not
   duplicate its work or fabricate expired-option price histories.

**Rollback:** close/revert this draft research PR; it does not touch any
production strategy, brokerage integration, release trust root, automation or
protected baseline.
