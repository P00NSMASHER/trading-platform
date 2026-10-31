# Golden Goose Hunter B/C: trailing daily-range regime (2026-10-31)

**Decision: REJECT as a credible net-of-cost trading edge.** This is an
exploratory, previously exposed historical cohort, not a new prospective
out-of-sample or actual executable-fill experiment. No orders, broker
credentials, paid data, redistribution of third-party bars, or live trading.

## Frozen bounded hypothesis (before inspecting outcome means in this iteration)

At the **open of T**, calculate the arithmetic average of the *five completed
prior trading sessions'* raw `(high-low)/open`. If the mean is at least 2%,
**hypothetically** hold long SPY from T's official open to T's official
close. The entirely separate diagnostic negative control is long SPY if
that five-session mean is at most 0.5%. This control is not a second
strategy or a source of threshold optimization. Require six distinct,
strictly increasing, weekday sessions and every consecutive calendar
spacing <=7 days; reject nonfinite, nonpositive, impossible or implausible
OHLC. Split fixed at pre-2013 training, 2013-2018 validation and
2019+ retrospective. Costs are hypothetical roundtrip 10/20/40 bps of
one-leg gross notional, primary 20 bps. Formula:
`net_bps = 10000 * (raw_close[T] / raw_open[T] - 1) - cost_bps`.
Neither official auction open nor close is an authenticated executable quote.

### Source identity and reproducibility

Read-only historical public GitHub CSVs pinned to immutable source commits;
verify each reported **Git blob SHA-1** on local download. GitHub-hosted
file identity and source dates were checked via connected GitHub access.
Original market-data vendor license and redistribution rights were NOT
established; no price bars are committed or licensed as original works.

- [xjcarter/data commit 7d705ada](https://github.com/xjcarter/data/commit/7d705ada2d3ca483700eb695772e7de9cfc75cbc), root `SPY.csv`, blob `5a17de0b52ed8941aacc2ba16bdc96d7c1073cff`; 5,759 sessions, 2000-01-03 to 2022-11-18.
- [revred/TradeSmart.Tracker commit 7d9d769b](https://github.com/revred/TradeSmart.Tracker/commit/7d9d769b0f2ddcedf4c1703cc979b865a37b580d), `market/us/spy.csv`, blob `38acc25a077e23fdf107102960c3df32f1543a7d`; 3,773 sessions, 2011-01-05 to 2026-01-06.

The two archives have **overlapping SPY trading history**, not independent
market replications. Source data came from public secondary archives, not
Tradier executable quotes, exchange auction allocation or broker records.

## Historical measured mean net bps per triggered session

All listed means include fixed hypothetical 20-bps roundtrip cost.
The 10-bps stress adds 10 bps to each displayed net estimate; the
40-bps stress subtracts 20 bps. Units are basis points of SPY notional,
not actual portfolio performance, returns on margin, or guaranteed fills.

| Arm and phase | xjcarter trades / mean | revred trades / mean |
|---|---:|---:|
| High prior range, training <2013 | 664 / -15.953 | 53 / -10.537 |
| High prior range, validation 2013-2018 | **58 / -20.840** | **58 / -20.840** |
| High prior range, retrospective 2019+ | **161 / -4.657** | **195 / -3.258** |
| Quiet prior range control, validation | 200 / -20.116 | 200 / -20.116 |
| Quiet prior range control, retrospective | 38 / -15.371 | 54 / -28.920 |

At optimistic 10-bps costs the high-range validation is still -10.840
bps/trade, but the retrospective means turn +5.343/+6.742 bps. Those
small positives are on **exposed overlapping historical data**, depend on
assumed ideal opening/closing fills, and are not replicated or actionable
profit. At 40 bps, validation -40.840, retrospective -24.657/-23.258.
Worst single retrospective net20 mark in both archives was ~-586 bps.
The historical cohorts are economically dependent; do not combine them
into a larger independent sample or claim significance. The repository
CLI also calculates seeded month-cluster 95% exploratory intervals when
at least five distinct entry months exist, which remain unadjusted for
multiple hypothesis tests and source selection.

Both sources had 0 out-of-order or weekend rows and 0 >7-day gaps in
this recorded inspection; 5,754 and 3,768 eligible post-lookback days,
respectively. Any future source re-retrieval should reverify byte identity
before reproducing the results. Figures above were independently computed
with a read-only JS implementation directly over the GitHub source
content; the native Python module was separately tested on adversarial
synthetic data, not production broker data.

## Reproduction / engineering checkpoint

```
PYTHONPATH=src python -m equity_range_regime_audit \
  --file /approved/local/SPY.csv \
  --git-blob-sha 5a17de0b52ed8941aacc2ba16bdc96d7c1073cff
PYTHONPATH=src python -m pytest -q tests/test_equity_range_regime_audit.py
```

`src/equity_range_regime_audit.py` is standard-library-only and imports
existing offline research helpers. No API endpoint, broker call, production
configuration, dependency, or existing evaluator is modified. The
19 synthetic/adversarial test cases passed locally with a faithful shim
for imported helper interfaces; **full native repository GitHub CI must
still execute on the exact PR head**. Rollback: remove just the new module,
its test, this report, and three exact candidate-authored SHA-256 allowlist
entries. These hashes are **not** external release-trust-root approval.

**Hunter A coordination:** Tradier Options Research v4.1 owns options
exchange-session timing checks; this work does not touch its PRs or
simulate option fills. **Hunter B:** rejects another retrospective idea.
**Hunter C:** proves timing exclusion, source identity, costs and
adversarial validity, but not real execution or genuine untouched OOS.

**Ranked next:** (1) prospective, embargoed SPY executable open/close
quote/auction evidence, actual fees and broker execution; (2) broker
borrowing/capacity evidence if testing any short strategy; (3) new
source-authorized independent historical series for sanity checks;
(4) multiple-hypothesis correction across all frozen Hunter protocols.
No parameter rescue on the already exposed SPY archive.
