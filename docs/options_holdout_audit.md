# Private chronological holdout audit (research only)

**Status:** Synthetic acceptance tests; no authorized private prospective quote outcomes connected, no genuine out-of-sample trading edge verified, no orders.

The existing [forward mark evaluator](options_forward_evidence.md) checks pricing, friction and weekly clustered uncertainty. This *additional* offline audit prevents development-set outcomes from leaking into a chronological test subset. It does **not** demonstrate that the cutoff was registered before outcomes, that a strategy was frozen, that signal admissions are complete, or that any paper quote is executable.

## Usage (privately retained, authorized records only)

Keep raw private option quote and position evidence **outside** the public repository and all public GitHub logs/artifacts. With Python 3.11+ and no broker token:

    PYTHONPATH=src python -m options_holdout_audit --private-csv /private/paper_marks.csv --holdout-start-utc 2026-07-01T00:00:00Z

The input is the full preselected entry/exit private CSV described in [options_forward_evidence.md](options_forward_evidence.md), never a favorable subset. The supplied holdout cutoff is an ISO timezone-qualified timestamp. It MUST have been externally preregistered before the holdout and independently preserved for a future genuine study; this local tool cannot verify that.

## Fail-closed split

- All input rows first pass the existing full-population paper-evidence and account-capacity checks. Duplicate IDs, hindsight quotes, contract mismatches or overlapping same-underlying exposure reject the entire audit.
- **Development:** signal decision more than 21 days before holdout start **and** the outcome's exit timestamp is at or before the cutoff. A longer 21–365-day embargo may be provided by the library API.
- **Withheld:** pre-holdout entries that are too close to the boundary, or would reveal outcomes not yet known at the cutoff.
- **Holdout:** signal decision at or after the immutable study cutoff. A pre-cutoff decision whose later entry crosses the boundary is withheld, not admitted to holdout. No training evidence or future outcomes are used to construct this subset.
- Only holdout quote marks are statistically screened; no training P&L is printed. Output is aggregate-only; no option symbol, raw price, timestamp or identifier is logged.
- All reports retain `edge_verdict=UNPROVEN`, `execution_proof=UNVERIFIED`, `holdout_boundary_precommitted_verified=false`, `unretuned_strategy_verified=false`, `matched_controls_verified=false` and `complete_selection_population_verified=false`.
- The strongest possible label is **PAPER_HOLDOUT_SCREEN_ONLY_UNATTESTED**. It is NOT a profitable-strategy claim, even for artificially successful synthetic marks. The concurrent $100 account risk limit remains enforced.

## Next real-data gate

Collect a legally retained, private, contemporaneously attested SELECTED/REJECTED population and complete entry/exit option quotes, lock the cutoff and strategy BEFORE observing outcomes, apply the [admission completeness audit](options_population_audit.md), and compare with matched controls under $0/$5/$10 fill stress. No retrospective ticker-only history can substitute for executable option quotes.
