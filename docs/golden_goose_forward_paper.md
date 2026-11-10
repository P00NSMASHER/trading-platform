# Golden Goose prospective paper evidence engine (research only)

This is an **offline, private, non-executing** lifecycle for an experiment. It
does not establish a profitable trading edge, submit brokerage orders, connect
to Tradier, change a Cloudflare Worker, or run on a schedule. Inputs must come
from a separately authorized feed with documented market-data rights.

## What is implemented

- Pre-register exactly one strategy implementation fingerprint, an independently
  chosen benchmark rule, and a future chronological holdout cutoff. Later
  changes or backdated admissions fail closed.
- Admit an existing `golden_goose_signals.SignalResult` and
  `golden_goose_candidates.DebitSpread` **only within 120 seconds of decision**,
  with contemporaneous, two-sided, source-qualified quote receipts; enforce the
  original $100 total concurrent indicative risk budget and conservative
  debit-spread screening.
- Freeze **four exact option-contract IDs** per observation: two for the
  selected experimental spread and two for a predeclared same-side,
  same-expiration independent benchmark spread. The benchmark must be selected
  before either exit is observed. Indicative entries are long ASK/short BID.
- Report every still-open paper position and all its required option IDs, even
  after an expected exit becomes missing. No missing contract is imputed as a
  win, no-fill, or loss. Monitoring an open position uses
  `due_contracts(now)`; **this module does not schedule or fetch those marks**.
- Reconcile **both** target and control at their frozen timestamp, using
  the long BID/short ASK, with each bid, ask, and capture timestamp no older
  than 120 seconds. Inputs arriving later than two minutes after the planned
  exit are rejected rather than chosen after the result is known.
- Subtract the established minimum $6.60 total modeled fees/slippage from
  both indicative paper P/Ls. Compare the benchmark at the *same modeled
  upfront risk* as the experimental spread.
- Use the existing conservative `evaluate_edge` gate separately for
  absolute net paper P/L and excess over the matched control. A positive
  result is labeled `PAPER_PROMISING_NOT_LIVE_VALIDATED`, **never**
  `PROFITABLE` or an executable order. Incomplete outcomes block promotion.
- Persist events in a local, owner-readable SQLite database. Serialized
  `BEGIN IMMEDIATE` writes, unique event IDs, immutability triggers, full
  hash-chain verification, and idempotent admissions prevent casual overwrites.
  Hash-chain integrity alone is not external proof against a privileged
  adversary; checkpoint `head_hash()` outside the database.

## Developer-only synthetic example

```python
from datetime import datetime, timedelta, timezone
from golden_goose_forward_paper import ForwardPaperBook

with ForwardPaperBook("/private/local/path/goose-paper.sqlite") as book:
    book.preregister(
        strategy_hash="<sha256 of frozen strategy specification>",
        benchmark_rule="predeclared_same_expiry_control_v1",
        holdout_start=datetime(2027, 1, 1, tzinfo=timezone.utc),
        registered_at=datetime.now(timezone.utc),
    )
    print(book.due_contracts(datetime.now(timezone.utc)))
    print(book.report())
    print(book.head_hash())
```

For a complete synthetic admission/exit integration example and negative
test cases, see `tests/test_golden_goose_forward_paper.py`. Use
`PYTHONPATH=src python -m pytest -q tests/test_golden_goose_forward_paper.py`.

No real quote samples, API credentials, or private paper ledgers are committed.
The local database must remain outside the repository and off public CI logs.

## Remaining independent operational prerequisites

This code is **not** a deployed prospective study. Its safety checks cannot
establish that a caller-supplied calendar or catalyst receipt is genuine.
Before running real admissions, provide and validate:

1. A rights-cleared, trustworthy exchange calendar and independently
   timestamped catalyst/public-event source.
2. At least 20 preceding, complete same-minute volume sessions per symbol,
   and reference market/sector confirmation using as-of-only data.
3. An independently reviewed, locked benchmark-selection algorithm; the code
   freezes the selected control but does not choose controls autonomously.
4. A private authorized source for all four contracts' quotes **through
   their predetermined exit**, with queue/idempotent retry and health
   monitoring. Current rotating D1 options snapshots do **not** guarantee
   complete exit follow-through or synchronized control quotes.
5. Separately verified quote-data lineage, independent replay, externally
   checkpointed journal hashes, and enough genuine holdout observations
   (100 complete, 90 calendar days, 12 entry weeks) for the existing
   weekly clustered bootstrap; include missing outcomes in denominators.
6. Independent assessments of fill probability, market impact, benchmark
   choice, and sensitivity to slippage and market regimes before any
   hypothetical paper result could be considered a candidate for further study.

**No production Cloudflare database, Worker, cron, trading account, or active
scheduler was touched as part of this code-only increment.**
