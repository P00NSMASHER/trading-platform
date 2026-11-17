# Private forward price research v1

This release integrates the prospective ledger work from PR #544 and bounded
collector recovery from PR #547 into the existing collector. It adds no service,
public data endpoint, broker route, paid dependency, or cron. Raw market data and
private reports must stay out of git and public Actions artifacts.

## Frozen experiment

`workers/paper_research_v1.mjs` is the single executable specification. Its JSON
configuration is SHA-256 bound to an immutable private D1 registration before
`forward_start`. A different rule requires a different study ID and future
registration; historical observations cannot be relabeled prospective.

SPY and QQQ are screened at 10:05, 10:35, 11:05, 13:05, and 14:05 Eastern on
exchange sessions. The opening range is the first 30 complete one-minute
**midquote** observations, not true trade OHLC. Missing opening minutes or any of
the ten immediately preceding minutes block selection. Require a range of at
least 5 basis points. Continuation requires the last three observations outside
the range plus a 2 bp buffer. Failed breakout reversal requires a prior crossing
in the last ten observations followed by a return inside the buffered range;
ambiguous two-sided failures are rejected. Only information captured by decision
time is used.

A signal selects four standard OCC contracts from the nearest actually listed
5–14 calendar-day expiry with four consecutive $1 strikes. The target is a $1
call or put debit spread around rounded spot; the reference spread has the same
root, expiry, direction and width two strikes farther out of the money. This is
a **contract-selection comparison**, not a randomized causal control or proof
that the timing signal adds value. Its P&L is risk-scaled before comparison.
SPY precedes QQQ deterministically; both signals and rejected candidates are
recorded. Only one global active target/reference pair is admitted. Comparison
legs never count as independent outcomes.

The decision time, version hash, four exact IDs, roles and fixed 30-minute exit
are committed atomically with the tracking queue **before** requesting entry
quotes. Positions continue to receive their exact symbols each minute; moving
strikes and original premium ceilings cannot replace or drop them. Entry needs
all four fresh quotes, OI >=100, <=10% relative spread and <=$100 modeled target
and control risk separately. Quotes have independent bid/ask provider clocks and
capture clocks, <=60-second age and <=45-second cross-leg clock skew. Invalid
identity, future/naive clocks, nonstandard deliverables or expired IDs fail
closed. Session calendar is the existing 2026–2028 calendar and fails closed
beyond its verified horizon.

Entry uses long ask minus short bid; exit uses long bid minus short ask. Four
contract sides cost $0.65 each plus $4 adverse execution per round trip; stress
adds $10. These are explicit modeling assumptions, **not actual broker fees,
orders or fills**. An entry is a `QUOTE_MODEL`, never a fill. Missing entry,
interrupted entry capture, stale quotes, invalid vertical close marks and late
exits are explicit no-fill or missing outcomes. Quotes do not establish available
size, execution probability, assignment costs or simultaneous leg execution.

Greek timestamps remain raw in the existing collector. Price-only v1 does not
use IV or Greeks. Naive Greek clocks remain unknown; even timezone-explicit
values are hourly provider updates, not tick updates. The existing direct-Greek
cross-check remains diagnostic only. Do not infer a timezone from a plausible
wall-clock reading.

## Persistence and recovery

`workers/migrations/0001_paper_research.sql` only adds tables/indexes/triggers.
Designs, decisions, entry receipts, observations and outcomes reject updates and
deletes. D1 transactional batches prevent a selected decision losing its queue.
Duplicate cron deliveries do not repeat the same-minute work. A restart resumes
the persisted queue on the next minute. An interruption longer than the entry
window produces a no-fill; longer than the exit window produces a missing exit.
Missing marks are never filled using a later contract or convenient later price.
Hashes detect receipt modification; administrator access is not cryptographically
prevented by database triggers. Keep an independent private hash checkpoint.

## Evidence and holdout

The first 60 calendar days from `forward_start` are prospective development.
`holdout_start` is predeclared exactly 60 days later. Routine scorecards show
development returns and holdout **counts only**. Holdout returns are embargoed.
The offline evaluator requires, per hypothesis:

- 100 complete, non-overlapping prospective target/reference outcomes;
- at least 90 calendar days between first and last complete entry;
- at least 12 distinct entry weeks;
- at least 30 complete untouched holdout observations;
- complete accounting for every modeled entry, with no unresolved missing exit;
- recomputation from hashed entry/exit quotes with exact frozen identities.

Then one immutable evaluation file locks the input digest and result. Re-running
returns that locked result. Changing rules after evaluation requires a new
future experiment. Whole entry weeks are resampled together (4,000 deterministic
bootstrap draws); a 95% lower bound must exceed zero for holdout net P&L,
risk-scaled excess P&L and the adverse-cost stress case. At least four holdout
weeks are required. Passing means **qualified for further paper validation**,
never proven profitability or permission to trade. Failing at the one locked
evaluation rejects v1; insufficient observations continue collecting. Reporting
and holdout access remain private, and manual access to embargoed returns must
invalidate the untouched designation.

## Bounded costs and reporting

Paper processing uses the existing minute trigger. An indexed per-symbol,
per-session underlying extract is capped at 390 rows. The active queue has one
row. The private daily summary reads at most 1,001 indexed decisions, explicitly
labels a bounded window, and publishes no market data. Limits reserve room before
new work: 25,000 reported paper D1 reads/day, 6,000 writes/day, 250 provider
requests/day; no individual query may report over 25,000 reads and a run stops
above 12,000 reads. These are paper-module counters with conservative bookkeeping
allowance, not an account-wide billing cap. Existing collectors have separate
usage. Quota or authorization denial is not retried; existing provider cooldown
is preserved. Hard failures are surfaced in scheduled invocation status.

The archive tool seals immutable per-day hashes and query receipts, reuses prior
chunks and never queries production itself. Bounded connector extracts should
use `(symbol, observed_minute)` or the primary time index; meter every response
and stop before the approved daily account reserve. Full history is analyzed
from private copies, never repeated full-table scans. Keep incomplete and
no-fill candidates in all exported ledgers.

```sh
PYTHONPATH=src python -m paper_research_analysis archive private_runtime/paper_research_archive
node scripts/paper_price_screen.mjs private_runtime/paper_research_archive/screen_input.json private_runtime/paper_research_archive/historical_screen.json
PYTHONPATH=src python -m paper_research_analysis scorecard private_runtime/ledger.json private_runtime/scorecard.json --evaluation-lock private_runtime/first_evaluation.json
```

The ledger JSON contains the exact registration plus `decisions`, `entries`,
`marks`, and `outcomes` from bounded indexed private extracts. Archive analysis
reports quote spreads, costs and illustrative no-fill/adverse scenarios by
symbol, expiry range, time and observed opening-range regime. These are sampled
quoted liquidity statistics, not realized returns or full-chain coverage.
Historical hypothesis screening uses the exact Worker function and a chronological
70/30 descriptive split; neither segment is called an untouched holdout.

## Release and verification

Required checks run the Python suite and the Node 24 SQLite-backed Worker tests.
Fixtures are synthetic and isolated; production contains only genuine captures.
Apply the additive migration after checks pass; register the exact design JSON,
hash and future starts; upload both Worker modules with the existing D1 binding
and inherited secret. Enable `PAPER_RESEARCH_ENABLED=true` only after registration.
Keep the original minute cron, calendar guards, broad five-minute cadence and
GET-only Tradier allowlist. Compare deployed module hashes with the tested commit.
Rollback uses the preceding Worker version; preserve the append-only ledger.

Production acceptance requires a genuine future selection, four exact entry
receipts, continued same-ID marks and the planned exit, all independently read
from D1. A closed-market deployment cannot satisfy that gate. Verify actual
provider metadata, latency, quotas, resource counters and scorecard persistence
at the next session. Never backdate registration or inject fixtures to claim it.
