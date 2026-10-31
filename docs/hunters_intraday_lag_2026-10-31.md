# Golden Goose Hunter B/C: SPY previous-session intraday reversal (2026-10-31)

**Verdict: REJECT as a validated net edge.** An exploratory source-pinned
SPY next-session paper-long rule is negative on the frozen 2013-2018
validation cohort at 20bps modeled one-leg roundtrip costs, while
retrospective 2019+ samples are slightly positive but reverse under 40bps.
No executable bid/ask or auction fill is observed. No proof of profit.

## Frozen in-run method, exploratory not prospective preregistration

- At T entry decision, T-1 SPY **raw close / open - 1 <= -1%**;
  hypothetical long SPY T official open to T close. Thus T payoff never
  determines its own signal. Today's opening print is used as an idealized
  entry price, not an assumed fill.
- Predeclared separate diagnostic control: when T-1 intraday rise is
  >= +1%, paper **short** T open to close. It is NOT a second promoted
  strategy and omits borrow availability.
- Fixed friction on gross single-leg notional: 20bps primary, 10bps
  optimistic, 40bps stress. Real auction spread, slippage, funding,
  corporate action source timing, costs and taxes not established.
- Abort malformed, unsorted, repeated, negative, nonfinite and unusual
  intraday price records; skip T after >7-day stale calendar gaps.
- Training before 2013, validation 2013-2018, retrospective holdout
  2019 through each source end. Existing Hunter studies have exposed
  these markets: this holdout is **not genuinely untouched**.
- Chosen prior-day 1% rule was stated before fetching these source bytes
  in this run, but has **no independent external timestamped pre-registration**
  and is exploratory alongside already investigated SPY ideas. No
  optimized threshold or ex-post strategy selection is authorized.

## Actual historical source evidence, no redistributable prices

- [xjcarter/data](https://github.com/xjcarter/data/commit/7d705ada2d3ca483700eb695772e7de9cfc75cbc)
  exact commit `7d705ada2d3ca483700eb695772e7de9cfc75cbc`,
  SPY.csv Git blob `5a17de0b52ed8941aacc2ba16bdc96d7c1073cff`;
  5,759 bars, 2000-01-03..2022-11-18.
- [revred/TradeSmart.Tracker](https://github.com/revred/TradeSmart.Tracker/commit/7d9d769b0f2ddcedf4c1703cc979b865a37b580d)
  exact commit `7d9d769b0f2ddcedf4c1703cc979b865a37b580d`,
  market/us/spy.csv blob `38acc25a077e23fdf107102960c3df32f1543a7d`;
  3,773 bars, 2011-01-05..2026-01-06.
- Prior run authenticated these Git blob IDs. This run directly re-read
  raw files from fixed commits and independently checked finite
  positive raw open/close, ordered dates, and 0 gaps >7 days.
  Secondary archives overlap and have no confirmed compatible
  root LICENSE. Do not redistribute the underlying rows or claim vendor
  provenance or independent market replication.

## Measured paper-only means at 20bps cost

Values are per-trigger **net basis points on SPY gross notional**, not
portfolio CAGR, Sharpe or executable return.

| Cohort | xjcarter n / net bps | revred n / net bps |
|---|---:|---:|
| Pre-2013 train | 472 / -6.463 | 48 / +11.190 |
| 2013-2018 validation | 91 / **-15.133** | 91 / **-15.133** |
| 2019+ retrospective | 116 / +2.043 | 172 / +4.076 |

- At 10bps modeled cost: validation -5.133bps; retrospective
  xjcarter +12.043bps and revred +14.076bps.
- At 40bps modeled cost: validation -35.133bps; retrospective
  xjcarter -17.957bps and revred -15.924bps.
- Post-2019 worst single paper-trade net outcome at 20bps:
  xjcarter -328.203bps, revred -371.175bps.
- 20bps month-cluster bootstrap, 1,500 in-run independent JS
  LCG resamples, seed 102391, multiplier 1664525 and increment
  1013904223, each draw resamples the same number of calendar-month
  clusters with replacement (including all trades in the month).
  Exploratory 95% percentile intervals: validation both
  [-26.463, -2.565]; retrospective xjcarter [-12.937, +17.766],
  revred [-12.953, +24.566] bps. They omit auction, borrow,
  adjustment, exposure overlap, selection and cost uncertainty.
  The native Python CLI uses a different seeded PRNG via the
  existing month-bootstrap helper, so its exact finite-sample
  interval numbers need not match this independent JS cross-check.

**Interpretation:** later positive point estimates are small, unstable
to realistic-cost stress and inconsistent with the negative earlier
validation. Same-market archive overlap cannot be sold as replication.
No statistically defensible golden goose, executable edge or
risk-adjusted portfolio return is established.

## Reproduce with independently obtained exact-commit source files

```sh
PYTHONPATH=src python -m equity_intraday_lag_audit \
  --file /private/market/SPY.csv \
  --git-blob-sha 5a17de0b52ed8941aacc2ba16bdc96d7c1073cff
PYTHONPATH=src python -m pytest -q tests/test_equity_intraday_lag_audit.py
```

Python adapter refuses any file with a different Git blob identifier,
does not fetch prices or place orders, emits the fixed train/validation/
holdout split and 10/20/40bp means and bootstrap diagnostics. Unit tests
use only synthetic prices. No new third-party dependency or source
licensed code. This addition is part of the existing Golden Goose
draft PR #518, not a deployed feature.

## Coordination, uncertainty and next critical test

**Hunter A:** Options task retains ownership of the independent Tradier
v3.7 future-quote bug and synchronized two-leg executable marks.
**Hunter B:** no threshold tuning on exposed SPY holdouts; reject this
candidate from the action queue. **Hunter C:** strengthen realistic
acquisition-time fills and independent prospective embargoed evaluation.
Priority remains collecting true timestamped executable prices, real
slippage/commission and appropriate borrow evidence under approved
research-only data rights. Keep release trust-root independent and this
research draft unmerged.
