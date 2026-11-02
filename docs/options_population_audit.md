# Private prospective selection/admission completeness audit

The options research engine now has TWO independent private-only layers:

1. A [quote-mark evaluator](options_forward_evidence.md) that checks actual
   entry and exit quote observations and estimates bid/ask-based paper P&L.
2. This **admission manifest audit**, which verifies that the private outcome
   file contains a completed outcome for every previously selected signal
   in the submitted population.

The goal is to prevent a spreadsheet containing only winning closed
positions from being mistaken for evidence of a profitable strategy.

## Running locally (no Tradier token, no account access)

Use only privately retained, rights-authorized, non-public CSVs. Never put
the input files in this public GitHub repository or GitHub Actions artifacts.

    PYTHONPATH=src python -m options_population_audit --private-admissions /private/admissions.csv --private-outcomes /private/paper_marks.csv

The admissions file must contain:

    trade_id,underlying,expiry,side,decision_utc,recorded_utc,disposition,reject_reason

- Each signal must have a unique opaque trade_id.
- Underlying, expiry, side and decision_utc identify the observation.
- Both UTC times must be timezone-aware; recorded_utc must occur from the
  decision moment to no later than 120 seconds after it. For selected
  paper entries, recorded_utc must also be no later than entry_utc.
- disposition is SELECTED or REJECTED.
- SELECTED entries require an empty reject_reason. REJECTED entries require
  one of DATA_QUALITY, NO_H1, ACCOUNT_CAPACITY, CONFLICTING_EXPOSURE,
  OTHER_PREDECLARED.
- The admission list is *supposed* to include all candidates in the
  fixed, preregistered observation universe, including rejected candidates.
  **That cannot be independently verified from a user-supplied CSV.**

The outcomes file uses the full private paper quote-mark header described
in [options_forward_evidence.md](options_forward_evidence.md). Its trade_id,
underlying, expiry, side and decision_utc must match a SELECTED admission.

## Fail-closed outcomes

- A SELECTED admission with an expired option and no outcome produces
  INCOMPLETE_EXPIRED_OUTCOMES. An open/unexpired selected admission without
  an outcome produces PENDING_UNCLOSED_SIGNAL_OUTCOMES. **Neither releases
  favorable P&L estimates for the subset that happened to close.**
- An outcome absent from admissions, an outcome attached to a REJECTED
  signal, a duplicated identifier, a changed contract identity/side/expiry,
  or an admission recorded after the paper entry is a hard error.
- If every selected admission has a valid independently quote-marked exit,
  the status is COMPLETE_SUBMITTED_SELECTION_LEDGER_ONLY. The separate
  forward evaluator's aggregate statistical report is nested under
  paper_quote_mark_evaluation. Even apparently positive results remain
  paper-only with edge_verdict=UNPROVEN.
- The report includes counts for selected and rejected signals and rejected
  reason categories, but **no ticker, contract, strike, timestamp, option
  price or trade identifier**. These inputs are read locally only.

## Critical remaining limits

A CSV assertion about recorded_utc is *not* cryptographic proof that the
selection existed at that historical time. A complete *submitted* manifest
is not proof that all eligible market opportunities were included.
Rejected/accepted selection biases, price-selection lookahead, historical
restatements, survivorship of underlying symbols, missing licensed data,
real fills, margin and early-assignment outcomes still require independent
verification and untouched future holdouts.

Accordingly the audit always sets
selection_manifest_timestamp_attested=false,
full_candidate_universe_verified=false,
execution_proof=UNVERIFIED and edge_verdict=UNPROVEN.

CI runs only deterministic synthetic tests, never any private source data.
The existing Tradier scanner and all of its live scheduling, API restrictions,
token protections and raw-data deletion remain unchanged.
