# Golden Goose Hunter B/C: previous-session overnight gap (2026-10-31)

**Verdict: REJECT as a validated net edge.** A source-pinned SPY prior
overnight-up-gap continuation hypothesis loses on the frozen historical
2013-2018 validation and both overlapping retrospective archives under
20 bps modeled single-leg roundtrip costs. These are *not* actual
market-open fills or real broker P&L.

## Frozen hypothesis and controls

- Before inspecting the outcome: at T open, if the **previous completed
  session's overnight gap** (T-1 raw OPEN / T-2 raw CLOSE - 1) is at least
  **+1.00%**, hypothetically buy SPY at T official opening print and sell
  at T closing print. The T close does not influence its own signal.
- A separate negative diagnostic: T-1 overnight gap <= -1.00%, hypothetically
  short SPY for T open-to-close. This is **not** a second candidate or
  recommendation; borrowing feasibility is entirely unverified.
- Freeze 20 bps modeled gross-notional roundtrip friction, 10 bps
  optimistic and 40 bps stress. Source price precision and official
  opening auction are not measured executable bid/ask or acquired fills.
  Spread, slippage, borrow, dividends, financing, taxes and exposure
  selection could make realized costs materially worse.
- Split: pre-2013 train; 2013-2018 validation; 2019+ retrospective
  holdout through each archive's end. All periods were previously exposed
  by related ETF experiments. **No genuinely untouched OOS data**.
- Reject malformed, duplicate, unsorted, nonfinite and outlier prices;
  require both T-2 to T-1 and T-1 to T calendar gaps <=7 days; do not
  forward fill. Return is gross T close/T open -1, less fixed friction.
- This rule was frozen before examining the referenced immutable price
  bytes in this run, but has **no independent timestamped pre-registration**
  and is one of multiple attempted strategies. No threshold optimization
  or significance/promotion claim is permitted.

## Source-provenance and historical observation

Two *secondary*, economically overlapping archives were read at immutable
Git commits and Git blob identities. No raw price observations were copied
into the owner's repository. Their root LICENSE and exchange/vendor usage
rights have not been independently verified.

- [xjcarter/data commit](https://github.com/xjcarter/data/commit/7d705ada2d3ca483700eb695772e7de9cfc75cbc)
  `SPY.csv`, Git blob SHA-1
  `5a17de0b52ed8941aacc2ba16bdc96d7c1073cff`;
  5,759 ordered bars, 2000-01-03 through 2022-11-18.
- [revred/TradeSmart.Tracker commit](https://github.com/revred/TradeSmart.Tracker/commit/7d9d769b0f2ddcedf4c1703cc979b865a37b580d)
  `market/us/spy.csv`, Git blob SHA-1
  `38acc25a077e23fdf107102960c3df32f1543a7d`;
  3,773 ordered bars, 2011-01-05 through 2026-01-06.

Both archives had zero unparseable daily records or calendar intervals
greater than 7 days under this audit. The archives overlap in price
economics; they are **NOT independent market replications**.
Raw historical gap classification may differ under ex-dividend and
split adjustment conventions; sources do not attest original point-in-time
data adjustments or borrow. Exact Git blob identity only establishes
retrieved file bytes, not trading suitability or publication rights.

## Paper-only outcome at 20 bps modeled costs

Figures are triggered-session *mean net basis points* (not cumulative
returns, compounded capital, Sharpe or executable P&L).

| Cohort | xjcarter primary (n, bps) | revred primary (n, bps) |
| --- | ---: | ---: |
| Train <2013 | 168, -17.771 | 35, -26.690 |
| Validation 2013-2018 | 33, **-18.282** | 33, **-18.282** |
| Retrospective holdout 2019+ | 69, **-27.496** | 96, **-12.830** |

- At optimistic 10 bps, validation still -8.282 bps, holdout
  xjcarter -17.496 and revred -2.830. At 40 bps, validation
  -38.282, holdout -47.496 and -32.830 bps.
- The reversed-sign short negative control produced validation
  **+25.150 bps** (34 trades) on xjcarter and **+26.909**
  (33 trades) on revred, but retrospective holdouts were
  **-28.696** (74 trades) and **-26.423** (105 trades).
  The short control omits actual borrow, therefore is not a
  profit candidate even where validation mean is positive.
- Exploratory 1,500-draw **calendar-month cluster bootstrap** using
  deterministic JS LCG (seed 102391, multiplier 1664525, increment
  1013904223, full month clusters with replacement): at 20 bps
  validation primary [-58.464, +17.035] in both archives;
  retrospective xjcarter [-53.724, -2.316], revred
  [-42.512, +24.840] bps. These intervals omit multiple-testing,
  future source adjustment, genuine execution and selection uncertainty.
  The Python CLI uses its already-tested Python PRNG; exact percentile
  values may differ from this independent JS cross-check.
- Worst single retrospective net mark at 20 bps: xjcarter
  -351.133 bps and revred -351.133 bps. The baseline
  20 bps is hypothetical, not validated slippage or fees.

**Interpretation:** There is no reproducible, cost-robust, risk-adjusted
positive expectancy. A favorable sign in an exposed short diagnostic
is not a promotable result. This is another falsification, not a
new trade signal. No retrospective archive overlap is counted as
independent confirmation.

## Reproduction and governance

Acquire exact source files only under verified use rights, confirm
their supplied Git blob SHA-1, keep the CSVs private, then run:

```sh
PYTHONPATH=src python -m equity_overnight_gap_audit \
  --file /private/market/SPY.csv \
  --git-blob-sha 5a17de0b52ed8941aacc2ba16bdc96d7c1073cff
PYTHONPATH=src python -m pytest -q tests/test_equity_overnight_gap_audit.py
```

The new standard-library-only offline module and synthetic adversarial
tests live on existing Golden Goose draft PR #518. Revert these three files
and their scoped candidate-authored allowlist entries to roll back.
A self-written SHA-256 release drift allowlist is **not** independent
release trust-root verification. Do not merge while it is missing.

**Hunter A:** Tradier v3.7 owns synchronized options quotes, expiry
and future-timestamp safeguards; no competing edits made.
**Hunter B:** this SPY gap continuation idea is rejected.
**Hunter C:** source-byte pins, negative-control, clustered uncertainty
and no-lookahead synthetic tests provide reproducibility, not true OOS
proof. Ranked next test: prospectively timestamp actual executable
bid/ask and auction fills, costs and corporate actions with appropriate
licensed data and untouched forward sample. No orders, API tokens,
payments, deployments or automation changes.
