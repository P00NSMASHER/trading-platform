# Private prospective options evidence evaluator

**Research only. No brokerage API, no orders, no raw quote uploads.**

The existing GitHub Actions Tradier scanner discovers current options but
destroys its raw quote snapshots and cannot calculate later outcomes. This
independent **offline-only** evaluator validates PRIVATE pre-entry and exit
observations if the user independently retains them under applicable terms.
It does not create that private dataset or retroactively invent fills.

## Running locally with authorized data

Keep the private source CSV **outside this public repository** and any
committed or public GitHub Actions artifact. Python 3.11+:

    PYTHONPATH=src python -m options_forward_evaluator --private-csv /private/path/paper_marks.csv

No network access or brokerage token is needed. The command emits aggregate
statistics and a sanitized status. It never prints raw prices, contracts,
underlying symbols, trade identifiers, or timestamps.

CSV: **one independently preregistered H1 paper outcome per row**. Required
column header, in any order:

    trade_id,underlying,expiry,side,decision_utc,entry_utc,entry_quote_utc,greeks_time_utc,exit_utc,exit_quote_utc,entry_spot,short_strike,long_strike,short_contract,long_contract,entry_short_bid,entry_short_ask,entry_long_bid,entry_long_ask,exit_short_bid,exit_short_ask,exit_long_bid,exit_long_ask,short_open_interest,long_open_interest,atm_iv,rv20,multiplier

- trade_id: unique opaque local key. underlying: uppercase ticker; expiry:
  YYYY-MM-DD; side: bear_call or bull_put.
- All timestamp columns: **timezone-aware** ISO 8601 with offset or Z.
  Keep original observations and independent capture/recording provenance
  privately. The evaluator itself cannot prove when records were created.
- Require **both bid and ask on each leg at both entry and exit**,
  with no crossed markets and no bid/ask width greater than 25% of mid.
  Conservative paper **entry** sells the short bid, buys the long ask;
  **exit** buys short at ask and sells long at bid. Quotes must be no older
  than 120 seconds before each event. The preregistered decision must be
  within 120 seconds of entry and cannot predate its own quote snapshot.
  The Greek calculation timestamp must be within 90 minutes of decision.
- Both 100-share option legs have >=100 open interest, positive entry
  credit, OTM defined-width strikes (width <= $3), <= $100 modeled
  per-spread risk and 7–21 calendar DTE at the Eastern decision date.
  short_contract and long_contract must be actual OCC standard option
  symbols (root + YYMMDD + C/P + 8-digit strike in thousandths), with
  matching unadjusted underlying root, exact expiration, right and strike.
  Missing or changed contract identities are rejected.
- atm_iv must be paired same-expiry near-ATM IV in decimals; rv20 is
  prior-completed-close 20-day realized vol in decimals. H1 requires
  atm_iv / rv20 >= 1.20. Short-leg skew cannot substitute for ATM-IV.

## Economics and acceptance

For a standard one-lot vertical:

    entry_credit_usd = 100 * (entry_short_bid - entry_long_ask)
    close_debit_usd = 100 * max(0, exit_short_ask - exit_long_bid)
    net_quote_mark_usd = entry_credit_usd - close_debit_usd - 2.60 - extra_slippage

Cost assumptions: four contract sides x $0.65, plus +$0 / +$5 / +$10
per-spread full-roundtrip adverse-fill stress. Actual Tradier plan, exchange
fees, early assignment, dividend obligations, margin, transaction failure,
tax and execution losses can exceed this stylized model. **Quote marks
do not prove executable fills or broker-confirmed P&L.**

The engine rejects duplicate trade IDs, correlated same-symbol/expiry/day
choices and overlapping positions in one underlying. It computes peak
concurrent modeled risk, marks it nonconforming if above $100 total, and
reports anonymized descriptive aggregate outcomes: completed marks,
distinct entry dates/weeks, timespan, mean, fraction of positive marks,
worst mark, exit-mark drawdown and a reproducible 1,500-rep **entry-week
clustered bootstrap** interval under each slippage scenario.

The exploratory minimum is 60 independently selected nonoverlapping marks,
at least a 90-day entry span across 12 entry weeks, peak modeled account
risk <= $100, and a positive lower bootstrap bound for net quote-marked
P&L under an additional $5 fill penalty. The strongest possible status
is PAPER_ONLY_PROMISING_NOT_VERIFIED. Both edge_verdict=UNPROVEN and
execution_proof=UNVERIFIED remain invariant. Proving an actual edge
still needs matched baselines, an untouched holdout period, independent
prospective entry attestations and actual authorized fills.

## Security

The evaluator and its **synthetic-only** acceptance tests run in CI without
the brokerage token. Protected-main market research continues using the
existing GET-only Tradier scanner, and deletes ephemeral CSVs. CI never
runs the evaluator on real/private market data.

**No private forward ledger is connected yet**. This is a researched,
tested validation capability, not evidence of profits.
