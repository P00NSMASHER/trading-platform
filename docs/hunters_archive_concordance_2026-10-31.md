# Golden Goose Hunter B/C: immutable SPY archive concordance (2026-10-31)

**New validated source-quality finding, NOT a profitable trading edge.** The two SPY CSV archives previously used as negative controls cover the same historical market and yield virtually identical *daily open-to-close returns*, but **materially different overnight gaps** because historical OHLC levels differ by a smoothly evolving, adjustment-like multiplicative factor. One archive's `Close` cannot safely be treated as the same unadjusted economic series as the other's `Close` when detecting prior overnight gaps. Neither historical data license nor exact corporate-action vendor methodology has been independently confirmed.

## Verified source identities and method

- [xjcarter/data SPY.csv](https://github.com/xjcarter/data/blob/7d705ada2d3ca483700eb695772e7de9cfc75cbc/SPY.csv), source commit `7d705ada2d3ca483700eb695772e7de9cfc75cbc`, Git blob `5a17de0b52ed8941aacc2ba16bdc96d7c1073cff`, **5,759** rows (2000-01-03 through 2022-11-18), `Adj Close` separate from `Close`.
- [revred/TradeSmart.Tracker market/us/spy.csv](https://github.com/revred/TradeSmart.Tracker/blob/7d9d769b0f2ddcedf4c1703cc979b865a37b580d/market/us/spy.csv), source commit `7d9d769b0f2ddcedf4c1703cc979b865a37b580d`, Git blob `38acc25a077e23fdf107102960c3df32f1543a7d`, **3,773** rows (2011-01-05 through 2026-01-06), no `Adj Close` column.
- The connected GitHub source reader independently returned **exact pinned blob IDs**, and JavaScript independently parsed each downloaded CSV, aligned exact ISO session dates, and compared raw intraday and gap returns. **2,990 overlapping sessions** from 2011-01-05 through 2022-11-18; **zero missing shared-calendar sessions**, no forward fills.
- Daily `close_revred / close_xjcarter` factor: first **0.764997310**, last **0.956871214**; in between it evolves gradually. Intraday return differences are negligible: maximum absolute **0.0007585 bps** (floating rounding). This supports the adjustment-like interpretation, but does **not** establish which archive is correct, the vendor's exact methodology or historic dividend entitlements.
- Overnight `open[T] / close[T-1] - 1` diverges by as much as **69.48753 bps**; **47 of 2,989** shared overnight comparisons differ by **more than 5 bps**. Differences cluster around quarterly dates. **External cross-check:** all **47 of 47** >5-bps discrepancy dates match the full SPY ex-dividend calendar from 2011-03-18 to 2022-09-16 listed by both [ETFIQ](https://etfiq.com/funds/spy/dividends/) and [Twelve Data](https://twelvedata.com/markets/568728/etf/nyse/spy/historical-data/dividends), with **0 extra/missing dates** (12 each in March, June and September; 11 in December). This is strong third-party corroboration for dividend adjustment semantics, not issuer-level certification of the adjustment formula or vendor licensing. As a negative control, **0 of 2,985** overlapping five-prior-session source comparisons disagree on the previously frozen high-range >=2% or quiet-range <=0.5% signals; source choice matters chiefly for **cross-day gaps**, not same-session returns.

## Effect on pre-registered previous-day 1% overnight-gap signal

Replicated the **already rejected** protocol owned by [Golden Goose PR #518](https://github.com/P00NSMASHER/trading-platform/pull/518): at hypothetical entry T, use prior day T-1's gap from T-2 close to T-1 open. Long if prior gap >= +100 bps; mirrored <= -100 bps short only as a diagnostic. The target T open-to-close is not used in the signal. Results below compare only the **shared 2,990-session 2011-2022** window; 20-bps total modeled single-leg roundtrip cost, hypothetical official opening/closing prices, no real executions.

| Phase on shared calendar | Long xjcarter / revred | Short control xjcarter / revred | Differing trigger dates |
|---|---:|---:|---:|
| 2011-2012 train (498 eligible) | 34 / 35 | 37 / 37 | 1 |
| 2013-2018 validation (1,510 eligible) | 33 / 33 | 34 / 33 | 1 |
| 2019-2022 retrospective (980 eligible) | 69 / 71 | 74 / 72 | 4 |

**Six source-dependent signal selections**: 2011-03-21 long; 2015-12-21 short control; 2020-03-23 long; 2020-06-22 long; 2021-06-21 short control; 2021-12-20 short control. These are entry dates and refer to **the previous session's gap**, not same-day outcomes. The precise 2020-03-23 source disagreement is xjcarter prior gap **+83.99 bps**, revred **+143.28 bps**; revred includes a hypothetical next-day loss of about **-249.63 bps net** that xjcarter does not flag.

Shared 2019-2022 retrospective **long** mean net after fixed 20bps costs: xjcarter **-27.496 bps (69 sessions)**, revred **-29.317 bps (71 sessions)**. This is **not** the entire revred 2019-2026 cohort reported in PR #518 (96 sessions, -12.830 bps); comparing those two full-window means directly would confound distinct dates.

### Reproduction and controls

`src/research_archive_concordance.py` is offline Python standard library, local-files only, checks full Git blob IDs, 10MB/source, 100,000 rows/source, nonfinite/invalid OHLC, duplicates, weekend dates, exact overlap, prior-session-only signals and seven-day continuity. `tests/test_research_archive_concordance.py` contains **14 passing synthetic/adversarial local tests**: tampering, source scaling, dividend-factor discontinuity, missing sessions, no overlap, invalid rows/calendars and temporal separation. No raw historical bar redistribution or external library added.

```sh
PYTHONPATH=src python -m research_archive_concordance \
 --primary /approved/local/xjcarter-SPY.csv \
 --primary-blob 5a17de0b52ed8941aacc2ba16bdc96d7c1073cff \
 --secondary /approved/local/revred-spy.csv \
 --secondary-blob 38acc25a077e23fdf107102960c3df32f1543a7d
PYTHONPATH=src python -m pytest -q tests/test_research_archive_concordance.py
```

**Independent computation:** The numeric historical findings were produced from exact GitHub source bytes in the connected data reader, not a synthetic price generator. The native Python module is covered by synthetic adversarial tests, but there is not yet a hosted Python execution against the full licensed archival price files. The two data sources are not independent replications, and earlier historical cohorts are exposed to many tested hypotheses. The SHA-256 hashes in release allowlists attest to **candidate-authored content only**, not an independent release authorization.

**Hunter A:** Tradier Options Research retains ownership of quote timestamps, option fill/exercise risk and options PRs; this finding concerns SPY archive adjustment semantics only. **Hunter B:** finds source-dependent threshold classification, not alpha. **Hunter C:** adds a repeatable fail-closed cross-archive QA check.

**Next critical test:** obtain approved source-licensed, point-in-time SPY corporate actions and independently timestamped broker/exchange bid/ask or auction evidence; reconcile historical raw vs adjusted bars, then register one prospective embargoed hypothesis with realistic fees, spread, borrow where applicable and multiple-trial correction. No orders, deployments, paid data, API credentials or live account changes.
