# Golden Goose Hunters A/B/C: first-of-month SPY intraday falsification (2026-10-31)

**Outcome: REJECT as a cost-robust trading edge.** An isolated, source-pinned, paper-only test found **-18.419 bps net per selected session** in the retrospective 2019-2022 shared-source cohort after assumed **20-bps complete round-trip friction** (47 sessions). Both public CSV archives agree to rounding because they cover **the same underlying market**, not two independent replications. No executable fills, deployed capital P/L, orders or actual profit are claimed.

## Research question fixed before this run's source read

Narrow testable *component* of the documented turn-of-the-month anomaly: does buying SPY at the first regular-session open of each new calendar month, then selling at that session close, yield positive net price change after fixed 20-bps round-trip friction? A calendar date determines the hypothetical entry, not the future closing price. **No optimizing a threshold, symbol or regime against results.** Stress friction at 10/20/30 bps. Negative control: other ordinary sessions' gross open-close returns, **not** a competing after-cost strategy.

This is **not** a test of the better-known *four-day, close-to-close* anomaly. Prior art: [McConnell and Xu, Equity Returns at the Turn of the Month](https://docs.lib.purdue.edu/ciberwp/43/), initially citing Lakonishok and Smidt 1988. Their reported phenomenon is not refuted by this restricted SPY single-session experiment.

## Exact source identities and periods

1. [xjcarter/data, pinned SPY.csv](https://github.com/xjcarter/data/blob/7d705ada2d3ca483700eb695772e7de9cfc75cbc/SPY.csv), commit 7d705ada2d3ca483700eb695772e7de9cfc75cbc; Git blob SHA-1 5a17de0b52ed8941aacc2ba16bdc96d7c1073cff; 5,759 bars (2000-01-03 to 2022-11-18).
2. [revred/TradeSmart.Tracker pinned market/us/spy.csv](https://github.com/revred/TradeSmart.Tracker/blob/7d9d769b0f2ddcedf4c1703cc979b865a37b580d/market/us/spy.csv), commit 7d9d769b0f2ddcedf4c1703cc979b865a37b580d; Git blob SHA-1 38acc25a077e23fdf107102960c3df32f1543a7d; 3,773 bars (2011-01-05 to 2026-01-06).
3. **2,990 exactly shared sessions**, 2011-01-05 to 2022-11-18. The first partial January 2011 is excluded as a signal since no prior month boundary is observed. The sources select identical entry dates. Max difference on selected intraday returns: approximately **0.000692 bps**. Secondary archives represent the same underlying market, not independent trials. Original market vendor and rehosting rights are not independently verified.

Numbers below were calculated directly on the pinned GitHub CSV response text by an independent JavaScript parser/aggregation procedure. Original market data were not committed. The Python CLI is included for later source-byte-verified reproduction, but exact source archives were **not** available in the local Python execution environment.

| Chronological partition | First-of-month trades | Gross bps/trade | Net at 10 bps | Net at 20 bps | Net at 30 bps | Other-session gross bps (n) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2011-2012 exploratory train | 23 | -32.490 | -42.490 | **-52.490** | -62.490 | +3.062 (476) |
| 2013-2018 validation | 72 | +3.713 | -6.287 | **-16.287** | -26.287 | +1.271 (1,438) |
| 2019-2022 retrospective holdout | 47 | +1.581 | -8.419 | **-18.419** | -28.419 | +2.635 (933) |

Holdout per-event standard deviation ~101.560 bps. A **naive, independent-normal approximation** for the holdout 20-bps mean's 95% interval is **[-47.454, +10.617] bps**. This crosses zero; it is not multiple-testing-adjusted, month-clustered or executable-performance certainty. The CLI computes a seed-pinned month-resampled interval if source-licensed input files are supplied; no exact native-bootstrap numeric outcome is claimed here.

Positive gross validation and holdout means are swallowed by even 10-bps assumed friction. The non-first-session control is intentionally **gross**; do not treat it as alternative net P/L. Official daily open/close prices are idealized, not authenticated achievable fills. Prior explorations of related ETF signals mean this is a **retrospective holdout**, not an untouched prospective alpha sample.

## Reproduce without external calls or trading credentials

The new file src/equity_calendar_turn_audit.py reuses the repository's own audited equity_reversal_audit.read_bars, with immutable Git-blob check, sorted unique date and OHLC guard. It adds 10 MB/source limit, fail-closed overlap/calendar mismatch, >35% intraday outlier guard, >7-day session-gap rejection, known-on-entry monthly date selection and deterministic month bootstrap. Test file tests/test_equity_calendar_turn_audit.py provides 14 deterministic synthetic/adversarial cases including signal timing, bad calendars, source mutation, cost, no-lookahead and source mismatch. It cannot transform modeled price changes into actual fills.

After independently confirming the right to use exact pinned public sources locally, store them outside the repository and run:

~~~sh
PYTHONPATH=src python -m equity_calendar_turn_audit \
  --first-file /private/research/SPY_xjcarter.csv \
  --first-blob 5a17de0b52ed8941aacc2ba16bdc96d7c1073cff \
  --second-file /private/research/spy_revred.csv \
  --second-blob 38acc25a077e23fdf107102960c3df32f1543a7d
PYTHONPATH=src python -m pytest -q tests/test_equity_calendar_turn_audit.py
~~~

Rollback: revert this isolated PR. No existing trading API, broker account, production workflow or protected release baseline is changed. No imported third-party code, new runtime dependencies, external telemetry or copied market-bar files. Passing tests must not bypass the independent release-drift trust-root requirement.

## Ranked next studies / division of ownership

1. **Reject** this single-session month-turn strategy as validated after-cost alpha; do not tweak retrospectively to manufacture positives.
2. **Hunter A:** The separate Tradier Options Research v4.3 task owns stale-underlying/option-timestamp freshness; avoid duplicate implementation. Need read-only, time-synchronized executable bid/ask evidence before spread outcomes.
3. **Hunter B:** Seek licensed, point-in-time SPY/QQQ auction/quote data with adjustment lineage and realistic trade costs. Overlapping public archives are not independent replications.
4. **Hunter C:** Pre-register a new hypothesis with prospective holdout and multiple-testing budget; require walk-forward uncertainty, corrections for serial correlation, capacity and crisis risk. Historical opening-price economics, market-data reuse rights and independent release attestation remain unresolved.

**Measured net edge for this rule:** negative under tested costs. **Verified positive edge: none.** No orders, charges, purchases, token exposure, deployments or automation modifications.
