# Golden Goose Hunter B/C: cross-market divergence rejected (2026-10-31)

**Verdict: REJECT as a cost-robust edge.** A 5-session SPY/QQQ relative underperformance hypothesis generated positive gross retrospective means in some later periods, but every validation and retrospective holdout source cohort was negative at 20 bps modeled total roundtrip friction. These are *idealized open-print returns*, NOT fills or paper brokerage executions. No trades, private quotes, API calls, secrets, deployments or monetary exposure.

## Frozen protocol (defined before reading this run's outcome)

- Require the entire overlapping SPY/QQQ trading-session calendar to match exactly (abort if either leg has an interior missing bar); no forward-filling, no asynchronous legs, no selectively dropped losses, and skip entry days following >7-day calendar gaps.
- At session T open, compare the **previous** T-1 close versus T-6 close five-session returns: (QQQ adjusted return - SPY adjusted return) <= -2.00 percentage points. If true, the hypothetical position is **50% gross long QQQ and 50% gross short SPY** from T official open to T close. No leverage/residual cash assumption is implied by this per-gross-notional return.
- Reverse-sign control: when QQQ led SPY by >= +2.00 points, go long SPY and short QQQ. Descriptive all-session control: half-long QQQ/half-short SPY.
- 20 bps gross-notional roundtrip friction is the predeclared conservative base, 10 bps an optimistic sensitivity, 40 and 80 bps stress. This is not observed bid/ask or a demonstrated borrow fee. Actual short borrow, auction slippage, fill sizes, spreads, taxes, costs and funding could differ.
- Train: dates before 2013-01-01; validation: 2013-01-01 to 2018-12-31; retrospective holdout: 2019-01-01 until source termination. Earlier overlapping equity strategies have already been researched: this so-called holdout is NOT genuinely untouched or a prospective OOS trial.
- Gross return = 0.5 * (QQQ_close/QQQ_open - SPY_close/SPY_open); net = gross return minus modeled two-leg friction, expressed on gross pair notional. Per-trigger average bps, not cumulative return, Sharpe ratio, realistic portfolio path, arbitrage, or a proof of profit. Signals use information available at or before T-1 ONLY.
- The original source access rights, time-of-availability of retrospective adjustments, exchange official opening auction prices, and real executable 2-sided short orders are not independently verified. This study is suitable for hypothesis falsification, not deployment.

## Source provenance (exact public GitHub file blobs, NOT copied into this repository)

| Secondary archive | Pinned Git commit | SPY Git blob SHA-1 | QQQ Git blob SHA-1 | Date span / common sessions | Notes |
|---|---|---|---|---|---|
| [xjcarter/data](https://github.com/xjcarter/data/commit/7d705ada2d3ca483700eb695772e7de9cfc75cbc) | `7d705ada2d3ca483700eb695772e7de9cfc75cbc` | `5a17de0b52ed8941aacc2ba16bdc96d7c1073cff` | `0b60cfa05a0117194440efd686c2df28f656f022` | 2000-01-03 to 2022-11-18; 5,759 | SPY.csv and QQQ.csv contain adjusted close |
| [revred/TradeSmart.Tracker](https://github.com/revred/TradeSmart.Tracker/commit/7d9d769b0f2ddcedf4c1703cc979b865a37b580d) | `7d9d769b0f2ddcedf4c1703cc979b865a37b580d` | `38acc25a077e23fdf107102960c3df32f1543a7d` | `410dc48d874ab666b6e22f529f395c0d9ca70060` | 2011-01-05 to 2026-01-06; 3,773 | market/us/spy.csv and market/us/qqq.csv have NO adjusted close; raw close used |

Both secondary repositories lacked an accessible root LICENSE file in the preceding Hunter inspection, so do NOT republish their CSV prices, assume commercialization rights, or claim exchange/vendor provenance. The two archives overlap economically and are not independent market replications. Verified blob IDs at the listed commits, without copying raw market data.

## Measured retrospective results

Figures = **mean net bps per triggered pair** at 20 bps modeled two-leg roundtrip friction; n = triggered sessions. The corresponding gross means are net+20 bps.

| Pair archive / evaluation | Validation n | Validation net bps | Retrospective holdout n | Holdout net bps | Holdout at 40 bps |
|---|---:|---:|---:|---:|---:|
| SPY/QQQ xjcarter | 36 | -14.461 | 61 | -10.921 | -30.921 |
| SPY/QQQ revred | 36 | -14.461 | 75 | -13.618 | -33.618 |

Additional fixed pre-2013 calibration: xjcarter n=393, net -21.426 bps at 20bps; revred n=4, net -8.409 (insufficient sampling, NOT material confirmation). Negative-control (QQQ-led prior 5d, reversed leg) validation -14.435 bps (n=27) for both archives, holdout xjcarter -14.976 (n=67), revred -16.566 (n=92); nothing becomes cost-robust. Source overlap means no duplicate independent evidence.

Across both source histories, the primary condition triggers in only 15 months in validation, 22 months in xjcarter holdout and 28 months in revred holdout. Month-cluster bootstrap is available via the source-pinned CLI; do not over-interpret nominal sample counts or post-hoc intervals.

**Independent supplemental uncertainty check:** 2,000 deterministic month-cluster resamples, seed 102391 (LCG), draw months with replacement and preserve every return within a drawn month. Exploratory 95% percentile intervals at the 20 bps cost assumption, net bps per triggered pair: xjcarter validation [-22.665, -5.540], holdout [-20.339, +1.206]; revred validation [-22.665, -5.540], holdout [-21.423, -4.647]. Retrospective, overlapping source histories are NOT independent and the intervals omit auction/borrow, source-method, future-adjustment, selection and hyperparameter uncertainty. They do not certify statistical significance or executable returns. Under **10 bps** optimistic costs, validation is still -4.461 bps, xjcarter holdout -0.921 bps and revred holdout -3.618 bps. No backtest-selected direction is promoted to a new strategy.

## Reproduce and reconcile

Run with externally retrieved exact-commit historical files under permitted data-use rights, verifying the blob SHA-1 before parsing:

```sh
PYTHONPATH=src python -m equity_pair_divergence_audit \
  --spy-file /private/market/SPY.csv --spy-git-blob-sha 5a17de0b52ed8941aacc2ba16bdc96d7c1073cff \
  --qqq-file /private/market/QQQ.csv --qqq-git-blob-sha 0b60cfa05a0117194440efd686c2df28f656f022
PYTHONPATH=src python -m pytest -q tests/test_equity_pair_divergence_audit.py
```

Results from this run were calculated independently by date-aligned JS against four fetched, fixed GitHub blobs; the Python module reproduces the frozen rules and uses the existing authenticated CSV adapter and month-cluster bootstrap. Check exact-head hosted CI and source-chain trust approval separately; both source and this doc are candidate-authored and are not independent release attestation. See `docs/hunters_trend20_falsification_2026-10-31.md` in pending PR #517 and `docs/hunters_equity_reversal_2026-10-31.md` in main for earlier rejected, non-independent overlapping hypotheses.

## Hunter A collaboration and next ranked experiments

1. **Options data-integrity, not a duplicate Tradier experiment:** Tradier Research v3.5 has identified that two individually fresh spread legs can be quoted 49 seconds apart and misstate hypothetical spread margin. Cross-leg synchronization remains owned by that task. Gather genuine *time-stamped* forward option-leg pairs at acquisition time; do not synthesize prices or propose 7-21 DTE win rates from expired histories.
2. **Next independent equity validation:** Require new, pre-registered non-overlapping prospective data, executable bid/ask/auction evidence, verified historical adjustment protocol and buy/short borrow constraints before promoting ANY cross-ETF signal.
3. **Engineering:** preserve and test the full calendar-denominator join, multi-asset joint cost uncertainty, and prevent post-hoc control selection; separate method review is needed before any protected release SHA attestation.

Tradier docs: https://docs.tradier.com/docs/market-data (expired options historical data unavailable; top-of-book Level 1 feeds; hourly Greeks and limited intraday retention). Pairs trading costs prior art: Do and Faff (2012), https://doi.org/10.1111/j.1475-6803.2012.01317.x .

## Source-bound independent source-integrity and cost-hurdle checkpoint (2026-10-31)

At the original full pinned source Git commits/blobs above, an independent
read-only, four-file archive scan found **0 duplicate dates, 0 decreasing
dates, 0 nonfinite numeric bar fields**, and **0 calendar gaps >7 days** in
each of SPY/QQQ (5,759 rows per xjcarter symbol, 3,773 per revred symbol).
This confirms the new strictly ordered, one-session-one-observation check does
**not alter** the frozen positive historical samples. The prior direct
`compute_pairs()` API *did* accept identically duplicated or scrambled dates
in both legs, potentially double-counting trades. Three synthetic hostile
calendar tests now reject it; this is a correctness fix, **not a newly
discovered trading signal**.

Using the exact published pinned blobs and the unchanged frozen 2% rule, the
**maximum roundtrip cost tolerable at zero average net return** equals the
idealized gross mean: xjcarter validation 5.539 bps (36 observations),
holdout 9.079 bps (61); revred validation 5.539 bps (36), holdout
6.382 bps (75). Actual costs remain unmeasured, and even an average
gross return above zero is not necessarily realizable at auction prints.
All four means are negative at the conservative 20 bps assumption.
The independent archive check has not created a new prospective holdout,
an independent market or an observed fill. The source streams overlap.

## Hunter B/C next-run integrity experiment (2026-10-31, 12:12 ET)

**Failure hypothesis, tested on synthetic evidence:** The prior implementation
checked only the T-1-to-T calendar gap. When both legs have a synchronized
30+ day outage *inside* the T-6-to-T five-session lag window but show fresh
T-1 quotes, the evaluator still admitted two candidate entries. The bounded
repair now skips an entry unless **all six successive calendar intervals**
from T-6 through T are <=7 days. Three adversarial regression tests cover
the synchronized hidden outage, automatic resumption after the entire
lookback refreshes, and acceptance of the frozen seven-day boundary. No
threshold tuning, no new trading signal and no changed cost assumptions.

**Actual-source check:** Re-read the same four public, immutable-commit CSVs
listed above, dated 2000-01-03..2022-11-18 for xjcarter (5,759
bars/symbol) and 2011-01-05..2026-01-06 for revred (3,773
bars/symbol). Each symbol had **0 consecutive-calendar gaps >7 days**.
The new filter therefore alters **0 source observations** in these archival
cohorts, so earlier documented 20-bp negative result and sample sizes
are unchanged. This checks date continuity, not licensed real-time quotes,
borrow rates, executable open/close auction fills or profit.

**Hunter A coordination:** Tradier Options Research v3.7 independently owns
future-dated quote acceptance. No option collector, quote timing, execution
or brokerage path changed. **Hunter B:** previously exposed SPY/QQQ samples
remain retrospective and not a fresh out-of-sample holdout.
**Hunter C:** real source-date control + adversarial synthetic regression.
No additional third-party libraries and no new data redistribution.
Release trust-root attestation is external and remains unresolved.

**Next:** Obtain independently timestamped, executable two-leg quotes,
borrow capacity and truly prospective untouched observations before any
attempt to validate a net, risk-adjusted edge. Keep this PR draft.
