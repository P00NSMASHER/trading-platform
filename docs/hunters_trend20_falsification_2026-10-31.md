# Golden Goose Hunter B/C: 20-session ETF trend-filter falsification (2026-10-31)

**Verdict: REJECT positive-trend hypothesis, no validated net trading edge.** This is an offline exploratory retrospective test against immutable public secondary GitHub CSVs, not a live execution or independent market-data attestation. No broker call, orders, API token, external spending, private data, or production change.

## Frozen test plan (set before evaluating the six source files)

- At session T open, calculate signal using only the **T-1 adjusted close divided by T-21 adjusted close minus 1**. The 20-session prior trend must be **>= +5.00%**; no optimization of threshold, ticker, train/validation/holdout splits or payoff after looking at the results.
- Hypothetical **buy at exact T official open print, sell at exact T close print**. This is an optimistic research proxy, **not an executable fill**. Do not trade it without bid/ask/auction and timestamp-specific execution evidence.
- Predeclared controls: negative 20-session trend <= -5.00% and all sessions. The negative-trend control is **not promoted into a trading strategy** if it appears profitable.
- Data partitions by target entry date: train before 2013-01-01, validation 2013-01-01 through 2018-12-31, retrospective holdout 2019-01-01 through each source's last date. The entire analysis is retrospective; earlier Hunter research has already inspected overlapping dates.
- Per completed roundtrip costs: 10 bps baseline, 30 and 50 bps stress. Estimate mean **net basis points per triggered trade**, not compound wealth, Sharpe, capacity, statistical significance, actual fills or total profit.
- Month-cluster bootstrap is available in the audited reusable module. Source/market overlap means neither 6 rows nor the two vendor-like sources count as independent markets or independent replication.

## Source census (files NOT copied to this repository)

| Source | Git commit | Symbols / path | Git blob SHA-1 | Date span |
|---|---|---|---|---|
| xjcarter/data | `7d705ada2d3ca483700eb695772e7de9cfc75cbc` | `SPY.csv` | `5a17de0b52ed8941aacc2ba16bdc96d7c1073cff` | 2000-01-03 to 2022-11-18 |
| same | same | `QQQ.csv` | `0b60cfa05a0117194440efd686c2df28f656f022` | 2000-01-03 to 2022-11-18 |
| same | same | `IWM.csv` | `26c8cb4f083715b4811ab5e388729069476fd27d` | 2000-05-26 to 2022-11-18 |
| same | same | `DIA.csv` | `a654644945c5a594ded5ffcb40826d612c729cd6` | 2000-01-03 to 2022-11-18 |
| revred/TradeSmart.Tracker | `7d9d769b0f2ddcedf4c1703cc979b865a37b580d` | `market/us/spy.csv` | `38acc25a077e23fdf107102960c3df32f1543a7d` | 2011-01-05 to 2026-01-06 |
| same | same | `market/us/qqq.csv` | `410dc48d874ab666b6e22f529f395c0d9ca70060` | 2011-01-05 to 2026-01-06 |

Original source anchors:
- https://github.com/xjcarter/data/commit/7d705ada2d3ca483700eb695772e7de9cfc75cbc
- https://github.com/revred/TradeSmart.Tracker/commit/7d9d769b0f2ddcedf4c1703cc979b865a37b580d

Neither source repository supplied an accessible root `LICENSE` file when checked. Do not redistribute raw CSV data or claim the files have a license. Market vendor identity, contemporaneous dividend-adjustment methodology, exact official open/close execution and commercial reuse rights remain **unverified**. Our code reuses only owner-repository code, with no new dependencies.

## Primary hypothesis: 20-session prior trend >= +5%

Observed net bps per selected session **at the fixed optimistic 10 bps roundtrip cost**. First validation precedes the retrospective holdout.

| ETF / source | 2013-18 validation n | Validation net bps | 2019-last-date n | Holdout net bps | Holdout at 30 bps |
|---|---:|---:|---:|---:|---:|
| SPY / xjcarter | 83 | -7.50 | 188 | -13.65 | -33.65 |
| QQQ / xjcarter | 193 | -7.05 | 320 | -6.40 | -26.40 |
| IWM / xjcarter | 212 | -5.30 | 263 | -19.96 | -39.96 |
| DIA / xjcarter | 123 | -8.87 | 159 | -11.09 | -31.09 |
| SPY / revred | 83 | -7.50 | 297 | -11.16 | -31.16 |
| QQQ / revred | 193 | -7.05 | 524 | -5.01 | -25.01 |

**6/6 validation and 6/6 retrospective holdout source-series are negative at 10 bps.** All six 30bps stress outcomes are also negative. They are not six independent studies because source histories overlap. No positive-trend edge is supported.

The negative-trend **control** shows SPY/revred +22.69 bps at 10 bps over 153 holdout observations, but **-10.13 bps in 2013-18 validation (69 observations)**, only +2.69 bps at 30bps in holdout, and shares economic history with the older SPY source. It is **exploratory** and cannot be promoted post hoc to an edge or used to claim independent replication. QQQ/revred negative-control 2019-2026 is +8.78 bps at 10 bps and -11.22 bps at 30 bps. Both require a separate future preregistered paper observation before any further claim.

## Reproduce, protect, and extend

Download files yourself under authorized rights using **exact fixed commit paths**, verify Git blob SHA before parsing, then for example:

```sh
PYTHONPATH=src python -m equity_trend_filter_audit \
  --file /private/research/SPY.csv \
  --git-blob-sha 5a17de0b52ed8941aacc2ba16bdc96d7c1073cff \
  --symbol SPY
PYTHONPATH=src python -m pytest -q tests/test_equity_trend_filter_audit.py
```

Both new source and test code use existing `equity_reversal_audit` source-byte validator and bootstrap rather than importing additional libraries. The signal is computed only with previous closes; source mismatch and malformed OHLC are rejected. Synthetic unit tests cover no-lookahead, cost monotonicity, control separation, phase cutoff, incomplete history and immutable-source authentication.

**Next recommended experiment (Hunter A/C collaboration):** Pre-register a prospective 7-21 DTE options cohort with actual dated bid/ask size/time snapshots, full-denominator losses, modeled capital-risk and assignment costs. Tradier officially notes **expired options have no historical API data**, and its consolidated quotes are Level 1, not Level 2: https://docs.tradier.com/docs/market-data . Do not synthesize 2026 historical options books or rely on hourly Greek updates as tick-level records. Existing Tradier PRs #509-#512 already own forward quote-depth gates; coordinate rather than duplicate. Research-only, not an investable trading recommendation.

**Reproducibility status:** source blob identities inspected and fixed retrospective summaries independently computed in the Hunter run; hosted CI and immutable source/test SHA approvals must still be checked on this PR's exact head. No revenue, returns or trades are certified.
