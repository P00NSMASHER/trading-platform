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
