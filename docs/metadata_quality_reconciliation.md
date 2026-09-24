# Step 19 — Metadata quality and reconciliation gate

Step 19 sits between metadata coverage (Steps 17–18) and any non-synthetic champion/challenger evaluation. Coverage alone is no longer sufficient to unlock evaluation.

## Core rule

A metadata set is usable for real historical evaluation only when:

1. the Step-17 point-in-time coverage gates are complete;
2. Step 19 finds no blocking cross-source quality conflict;
3. the inputs are not synthetic-only; and
4. source-contract validation remains clean.

The effective release flag is:

`quality_cleared_for_non_synthetic_model_evaluation`

Step 18's population status now also exposes this as `evaluation_release_gate`.

## Announcement reconciliation

For each event, Step 19 compares all matching candidate timestamps rather than trusting only the resolver's selected record.

- Only `first_public_release` and `official_newswire_release` with A/B source grades count as exact candidates.
- Two exact candidates that differ by more than 60 seconds trigger `ANN_EXACT_CONFLICT` and quarantine the event.
- Small non-zero disagreements inside 60 seconds are warnings.
- An exact first-public timestamp at or before the documented first illicit trade triggers `ANN_NOT_AFTER_FIRST_TRADE` because it contradicts the event-clock definition.
- EDGAR acceptance and other public proxies remain proxies and cannot manufacture an exact release time.

## Historical listing exchange

All effective security-master rows covering an event date are compared.

- If overlapping rows imply different normalized primary exchanges, the event is quarantined with `EXCHANGE_OVERLAP_CONFLICT`.
- Multiple sources agreeing on the same exchange are recorded as corroboration.
- A source-precedence table exists for deterministic normal selection, but precedence never suppresses a material conflict.

## Shares outstanding

Every shares candidate must already satisfy point-in-time availability.

- Equally fresh candidates differing by more than 2% trigger `SHARES_SAME_DATE_CONFLICT`.
- Nearby facts within seven days differing by more than 10% trigger `SHARES_NEARBY_FACT_CONFLICT` pending corporate-action reconciliation.
- Resolved facts older than 130 days are blocking; facts older than 90 days receive an aging warning.
- Abrupt value changes attributed to the same effective fact date are treated as internally inconsistent.

These thresholds are conservative quality controls, not claims that legitimate corporate actions cannot cause large changes. Quarantine means manual/contextual reconciliation is required before the data can be used for model evaluation.

## Matched-control universe

Step 19 compares duplicate point-in-time rows for the same control security/date.

- categorical covariates must agree;
- numerical covariates differing by more than 5% are considered conflicting;
- a conflicting duplicate triggers `CONTROL_DUPLICATE_CONFLICT` for the entire event date;
- a date can never be quality-cleared if the resolver claims readiness with fewer than three complete point-in-time candidates.

## Outputs

`metadata_quality_summary.json` — overall quality status and effective evaluation gate.

`metadata_quality_issues.csv` — blocking/warning/info findings with source IDs and conflicting values.

`metadata_domain_quality.csv` — coverage and quality-clear counts for announcement, exchange, shares and controls.

`metadata_quarantine.csv` — event/date/symbol-date keys excluded from evaluation pending reconciliation.

`metadata_quality_gate.csv` — explicit G6 gate status.

## Demonstrations

Clean synthetic plumbing:

```bash
PYTHONPATH=src python src/metadata_quality.py \
  --events data/examples/metadata/events.csv \
  --symbol-dates data/examples/metadata/symbol_dates.csv \
  --contract config/metadata_sources.demo.json \
  --resolver-dir data/processed/metadata_resolver_demo \
  --outdir data/processed/metadata_quality_demo
```

The clean synthetic fixture is internally quality-clear but remains `SYNTHETIC_ONLY`, so it cannot unlock a real evaluation.

Conflict/quarantine demonstration:

```bash
PYTHONPATH=src python src/metadata_quality.py \
  --events data/examples/metadata/events.csv \
  --symbol-dates data/examples/metadata/symbol_dates.csv \
  --contract config/metadata_sources.quality_conflict_demo.json \
  --resolver-dir data/processed/metadata_quality_conflict_resolver \
  --outdir data/processed/metadata_quality_conflict_demo
```

This deliberately contradictory synthetic contract is coverage-complete but quality-blocked, proving that Step 19 prevents Step-17/18 coverage from silently authorizing model evaluation.

## Research boundary

Step 19 performs historical data-quality/reconciliation only. It has no BUY/SELL, expected-return, target-price, sizing, order, or execution interface. Live stolen information, leaked credentials, accidental private disclosures, and unauthorized private data remain prohibited metadata classifications.
