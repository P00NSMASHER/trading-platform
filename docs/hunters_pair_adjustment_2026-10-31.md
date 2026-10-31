# Golden Goose Hunter A/B/C: adjusted-close classification audit (2026-10-31)

**Engineering outcome:** Historical adjusted-vs-raw closes can change whether
a frozen 5-session SPY/QQQ divergence signal fires. This is an input
provenance/sensitivity finding, **not** a second trading strategy, profitable
edge, or proof of actual lookahead. Existing Tradier Options Research v3.7
owns the separate future-dated option-quote bug: do not duplicate its
experiments or modify options collectors without coordination.

## Frozen diagnostic, source and timing

Compare existing prior-session T-1 versus T-6 QQQ-minus-SPY returns below
-2.00 percentage points. Hold the actual open-to-close pair payoff, 50%
QQQ long and 50% SPY short per gross notional, unchanged. The diagnostic
compares historical "Adj Close" and raw "Close" inputs; it NEVER searches
thresholds or elects a winning variant after observing outcomes. Retain the
original hypothetical 20-bp two-leg roundtrip friction and 10/40-bp
sensitivities. Corporate-action adjusted source series may carry
retrospective adjustment conventions, but the current scan does not
establish that a specific date was leaked or that one series is preferable.
The raw-close alternative is a negative sensitivity control, not
a recommendation to trade.

Price archives fetched for read-only analysis at **immutable Git commits**:
- xjcarter/data commit 7d705ada2d3ca483700eb695772e7de9cfc75cbc,
  SPY.csv blob 5a17de0b52ed8941aacc2ba16bdc96d7c1073cff and QQQ.csv
  blob 0b60cfa05a0117194440efd686c2df28f656f022.
- revred/TradeSmart.Tracker commit
  7d9d769b0f2ddcedf4c1703cc979b865a37b580d, SPY blob
  38acc25a077e23fdf107102960c3df32f1543a7d and QQQ blob
  410dc48d874ab666b6e22f529f395c0d9ca70060.

These are secondary, overlapping archives, not independent licensed
executable market data. Neither original upstream source's root LICENSE was
confirmed; do not redistribute their raw data. Raw URLs:
https://github.com/xjcarter/data/commit/7d705ada2d3ca483700eb695772e7de9cfc75cbc
https://github.com/revred/TradeSmart.Tracker/commit/7d9d769b0f2ddcedf4c1703cc979b865a37b580d

## Independently recalculated read-only observation

As-of this checkpoint the four pinned historical files supplied 5,759
aligned bars per symbol (xjcarter; 2000-01-03 to 2022-11-18) and 3,773
per symbol (revred; 2011-01-05 to 2026-01-06).
These are **not** independent markets or fills. At 20 bps modeled costs:

| Cohort | Adjusted selected / mean net bps | Raw selected / mean net bps | Selection disagreements |
|---|---:|---:|---:|
| xjcarter train through 2012 | 393 / -21.426 | 389 / -21.643 | 4 |
| xjcarter validation 2013-2018 | 36 / -14.461 | 36 / -14.461 | 0 |
| xjcarter retrospective 2019-2022 | 61 / -10.921 | 62 / -10.797 | 1 |
| revred train through 2012 | 4 / -8.409 | 4 / -8.409 | 0 |
| revred validation 2013-2018 | 36 / -14.461 | 36 / -14.461 | 0 |
| revred retrospective 2019-2026-01-06 | 75 / -13.618 | 75 / -13.618 | 0 |

Exact xjcarter disagreement dates: 2001-03-19, 2001-09-25,
2002-03-20, 2008-06-27 (adjusted-only) and 2020-03-30 (raw-only).
Largest observed absolute adjusted-vs-raw five-day relative-return
difference: ~66 bps in train, ~54 bps in validation, ~50 bps in holdout.
The revred archive has no "Adj Close" column, so its zero differences
are structural and NOT independent corroboration of adjustment validity.

**Verdict:** The original 20-bp negative result remains negative across
both representations; one holdout signal changes membership, so do not
pretend adjusted close is a point-in-time vendor attestation.
The retrospective "holdout" was inspected in earlier work: no genuine
untouched or prospective out-of-sample evidence exists. Auction execution,
borrow, share availability, corporate actions, adjustments and
time-stamped quotes remain unverified. No statistically validated edge.

## Reproduce offline (no source data checked into owner's repository)

```sh
PYTHONPATH=src python -m equity_pair_adjustment_audit \
  --spy-file /private/market/SPY.csv \
  --spy-git-blob-sha 5a17de0b52ed8941aacc2ba16bdc96d7c1073cff \
  --qqq-file /private/market/QQQ.csv \
  --qqq-git-blob-sha 0b60cfa05a0117194440efd686c2df28f656f022
PYTHONPATH=src python -m pytest -q tests/test_equity_pair_adjustment_audit.py
```

The CLI reuses the existing strict calendar / source-byte validator and
refuses mismatched input hashes. Unit tests use synthetic data only.
No new dependencies or outside code. Existing PR #518 is kept draft.
The release-drift allowlist records self-declared SHA-256 checksums only,
**not** an independent release trust-root.

## Hunter rotation and next tests (ranked)

1. **Hunter C:** Request independently sourced *point-in-time* adjustment
   and split/dividend calendars, then test membership changes ex ante
   before any strategy claim. Verify exact original Git blob SHA on input.
2. **Hunter B:** Pre-register prospective, separate-timeframe executable
   two-leg SPY/QQQ quotes and borrow capacity; otherwise keep the
   divergence strategy REJECTED. Bootstrap by month; no overlapping-source
   or tiny-sample significance claims.
3. **Hunter A:** Tradier v3.7 identified future-timestamp quote acceptance
   in synthetic tests. That task owns the repair and real-quote verification.
   Independently evaluate whether defined-risk spreads have complete
   timestamp-aligned quote and early-exercise/assignment evidence before
   doing any option payoff research. No expired-options fill fabrication.

Rollback: revert only this diagnostic's three files and their
`repository_additions` entries; original pair experiment unchanged.
