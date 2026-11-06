# Golden Goose | Phases 1–4 engineering handoff

**As of November 5, 2026 (ET):** Read-only research implementation. No live orders, brokerage trading, contact with third parties, or scheduled paper admissions.

## Evidence inventory

- workers/tradier_poller_v23.mjs: exact active v23 Cloudflare Worker source preserved in GitHub, without private tokens.
- workers/tradier_poller_v24_candidate.mjs: safe error categories for read-quota, database, provider, and transport failures; uploaded to Cloudflare as an **inactive** Worker version, not deployed.
- src/golden_goose_query_guard.py: indexed symbol/time plans with bound SQL parameters and fail-closed research row-read budgets.
- src/golden_goose_data.py: quote provenance, point-in-time freshness, standard OCC identity checks, volume and gap coverage, selected paper decision ledger.
- src/golden_goose_signals.py: 30-minute opening range, verified catalyst known before decision, retest, 20-day prior volume baseline, sector/market confirmation.
- src/golden_goose_candidates.py: 5–14 DTE debit-spread research, bid/ask costs, $100 portfolio risk cap, theoretical >=3:1 max reward/risk, holdout evidence requirement.
- src/golden_goose_simulator.py: **Phase 6 preparation only**, disabled without validated paper population.

This GitHub repository is public. No Tradier token, account balances, actual quotes, or private trading data should be committed.

## Phase 1 — PARTIAL (not yet production-verified)

Verified: active Worker version preserved verbatim in GitHub, v24 uploaded to a separate inactive Cloudflare version, and existing D1 primary keys and symbol/time indexes inspected. Bounded research plans require one contract or symbol, <=390-minute interval, <=390 output rows, <=25,000 actual rows_read per request, and an offline client budget of <=100,000 research rows per UTC day. These budgets are deliberately conservative, but apply only to clients using the new library.

Remaining: account-wide Cloudflare daily D1 free-quota headroom cannot be assured. Earlier unbounded analytical SQL joins consumed large read volumes; other apps share the same account limit. The generic v23 option_scan_failed errors require more diagnostic evidence and next-session verification. v24 has NOT been deployed and must not be called repaired until a live production run proves it.

Promotion gate: green GitHub CI and secret scans, source drift check, retained D1 and Tradier bindings, unchanged one-minute schedule, and verified new-session option captures after deployment.

## Phase 2 — PARTIAL (code exists, live end-to-end ingestion pending)

Implemented: point-in-time normalized vendor quotes, 120-second freshness check, OCC root/expiry/strike checks, market-minute gap reporting, cumulative-volume differentiation with first minute UNKNOWN, and a decision ledger explicitly recording selected, rejected, no-fill, and missing-exit outcomes.

Still required: private durable admission/mark store; monitoring **all open paper contract IDs** until their planned exits; completed 20 prior market sessions of historical same-minute volume baselines; an exchange holiday/calendar gate; rights-cleared, verified public event timestamps. Rotating option snapshots are NOT full chain data and cannot prove exits.

## Phase 3 — IMPLEMENTED FOR TESTING, EDGE NOT VERIFIED

Screen requires 09:30–09:59 ET initial range, >=10:05 decision, public catalyst known no more than four hours prior, >=20 prior completed comparable-volume sessions, relative volume >=1.5, preceding-bar retest, and market+sector directional agreement. Training and holdout split along chronological sessions. Reject missing data, lookahead, event ambiguity, or inconsistent source identity.

These are experimental thresholds. No independent trading edge, win rate, or real-money return has been established. Counterfactual and random-event benchmarks, bid/ask complete outcomes, and unseen-market tests remain necessary.

## Phase 4 — IMPLEMENTED FOR TESTING, NO ACTIONABLE TRADE VERDICT

Research candidate uses long leg ASK and short leg BID plus at least $6.60 modeled total additional fees/slippage, standard 100-share contracts only, DTE 5–14, OI >=100 on each leg, max bid/ask spread 10%, max one-lot loss lower of $100 / 10% hypothetical equity / $100 minus existing modeled open risk. Theoretical maximum net payoff/risk must be >=3. Candidates are labeled RESEARCH_ONLY_NOT_VALIDATED even if arithmetically attractive.

A paper-only positive-expectancy hypothesis requires >=100 fully reconciled, non-overlapping, bid/ask-marked prospective outcomes, >=90 calendar days, >=12 entry weeks, genuinely unseen holdout evaluation, and a positive week-cluster-bootstrap 95% lower bound for net dollar expectancy. Missing options or exits remain UNKNOWN; they are never counted as wins or discarded.

## Phase 5 — PREPARED, NOT STARTED

Before starting a recurring paper system: secure private persistent admission/outcome storage, quote subscription or repeated GET follow-through for each selected contract, source/market-data rights checks, complete holiday/event feed, queue and idempotent replay, paper execution estimates, predefined exits, and a sustained healthy collector. Do not turn on scheduling before a full forward-entry-to-exit smoke test. There are no real-money order functions in this implementation.

## Phase 6 — PREPARED, NOT STARTED

Offline simulation code is present and refuses to produce chance-of-doubling or chance-of-halving numbers without a positive complete prospective evidence verdict. When eligible, resample weekly clusters to preserve within-week dependencies, report ending doubled fraction, touched-half fraction and ending equity. Initial research ruin constraint: <=5% estimated probability of touching half the initial equity. Any output is a paper model, not a guarantee.

## Operations

- Read D1 using symbol-indexed bounded queries, avoid exploratory full-history joins.
- Inspect per-minute audit rows and saved option contracts; successful crons are not evidence of useful collection.
- Keep credentials in Cloudflare secrets. Public GitHub CI uses synthetic fixtures only.
- No emails, third-party submissions, trading, or account changes are authorized.

## November 6 D1 row-read quota incident (research engineering)

Authenticated Cloudflare account SQL analytics for Nov 5 identified the
**options research D1 database**, not the RETALLY inquiry database, as the
dominant row-read consumer. A repeatedly evaluated historical option-box
self-join of `quote_samples_v17` was sampled reading **605,278** rows for
**two** returned rows, with individual samples at 19:36:19 and 19:36:55 UTC.
Other historical aggregate scans also ran. The available telemetry names the
database and query, **not the user, script, agent or HTTP client submitting
it**. Approximate query-count aggregates are sampling-weighted, not a bill.

Do **not** run the historical wide C/P self-join again to benchmark it.
`src/golden_goose_query_guard.py::plan_box_minute` now plans an
existing-primary-key-indexed exact-minute, one-root, fixed-source SELECT.
`src/golden_goose_box_research.py::run_box_minute` computes four-leg bid/ask
math in private caller memory; it requires a **fresh authenticated account-wide
UTC-day read total** (no older than 120 seconds) with at least **500,000**
remaining rows reserved for other Cloudflare services and an external
per-day research budget (100,000 rows). It charges each D1
`meta.rows_read`, rejects missing meters and saturated LIMIT results, and
refuses to present rotating snapshots as full chains or executable prices.
Before and after every invocation, persist the research budget outside D1 with
serialized access; this helper does not safely coordinate concurrent writers
on its own. Do not use direct REST SQL access or an ad-hoc multi-minute scan
as a fallback when the quota preflight is unavailable.

Production D1 observed, read-only: an indexed one-minute, one-root retrieval
returned 12 rows with `meta.rows_read=54`; `EXPLAIN QUERY PLAN` confirmed
the existing `observed_minute` index. The contrast with 605,278 reads is a
**different-scope, feasibility comparison**, not an equivalent whole-history
optimization or evidence that historical results were replicated.

The protection applies **only to clients adopting this helper**. There is
no account-wide Cloudflare mechanism established here to reject external
unbounded SQL automatically. This PR deliberately changes no production
database, index, Worker, token, schedule, deployment, or inquiry endpoint.
In particular, the safe collector is not confirmed to be the source of the
expensive read query. Its v24 error-handling/reliability work is a separate
release. The recovery-check automation remains responsible for read-only D1
and inquiry service recovery; this section is root-cause engineering only.

**Acceptance before declaring permanent repair:** trace the direct query
caller(s), replace or remove their high-read SQL, secure usage of the bounded
research path and metered budget, independently exercise representative
synthetic math/negative cases, and collect a complete **post-adoption UTC day**
of Cloudflare per-database read totals below the **5,000,000 shared account**
limit with meaningful reserve. Check successful RETALLY submission only
through a separately authorized noncustomer test; its email-draft fallback
must remain usable without D1. Never submit a real customer inquiry as QA.
