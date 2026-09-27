# Real-data release sprint — Steps 1–12

This sprint converts the 12-step plan into deterministic repository state. It does not allow synthetic fixtures or reviewed exclusions to masquerade as the real source data required by Steps 5, 7, 8, 9, 10, 11, or 12.

## Commands

Freeze the exact requirements and generate acquisition artifacts:

```bash
PYTHONPATH=src python -m real_data_release_sprint freeze \
  --source-date-requirements data/processed/coverage_plan_real/source_date_requirements.csv \
  --event-exchange-resolutions data/processed/authorized_input_real/event_exchange_resolutions.csv \
  --outdir data/processed/real_data_release_sprint
```

Refresh the stale top-level gate view using current canonical metadata:

```bash
PYTHONPATH=src python -m real_data_release_sprint refresh-coverage \
  --coverage-summary data/processed/coverage_plan_real/coverage_summary.json \
  --metadata-readiness data/processed/authorized_input_real/metadata_readiness_summary.json \
  --metadata-quality data/processed/authorized_input_real/metadata_quality_summary.json \
  --requirements-manifest data/processed/real_data_release_sprint/requirements_manifest.json \
  --unresolved-gates data/processed/coverage_plan_real/unresolved_gates.csv
```

Write the 12-step truth receipt:

```bash
PYTHONPATH=src python -m real_data_release_sprint status \
  --requirements-manifest data/processed/real_data_release_sprint/requirements_manifest.json \
  --coverage-summary data/processed/coverage_plan_real/coverage_summary.json \
  --metadata-readiness data/processed/authorized_input_real/metadata_readiness_summary.json \
  --metadata-quality data/processed/authorized_input_real/metadata_quality_summary.json \
  --out data/processed/real_data_release_sprint/step_status.json
```

Add `--require-all-real` to make the command exit nonzero unless all 12 steps are genuinely complete.

## Frozen requirements

- 828 core G2 source-date rows: NYSE Daily TAQ-equivalent equity trades + quotes.
- 828 full-replication option source-date rows: Cboe/OPRA-equivalent option trades + quotes.
- 1,656 total required non-synthetic G2 rows.
- 80 G3-confirmed Nasdaq events requiring conditional event-level ITCH order-flow coverage.
- The older 414-date ITCH requirement remains recorded as a legacy planner scope; it is not treated as proof that every baseline date requires ITCH.

## Data boundary

The repository currently contains no authorized non-synthetic TAQ/OPRA/ITCH corpus, no authorized I/B/E/S exact timestamp extract, and no complete point-in-time matched-control metadata package. The sprint therefore records source-dependent steps as `SOURCE_BLOCKED` instead of fabricating completion.

The production ingestion code already validates declared dates, required symbols, explicit column maps, authorization class, and license references. Synthetic fixtures can exercise plumbing but can never close G2 or unlock non-synthetic model evaluation.

## Completion semantics

`PASS` means the step is actually satisfied by code/evidence present in the repository.

`SOURCE_BLOCKED` means the software path is ready but the required authorized source data is absent.

`DEPENDENCY_BLOCKED` means the step cannot truthfully run until earlier source-dependent steps clear.

The system remains research-only and prohibits BUY/SELL, expected-return, target-price, position-size, order, and execution-instruction outputs.
