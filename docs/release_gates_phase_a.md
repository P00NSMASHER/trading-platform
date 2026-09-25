# Release Gates Phase A — Historical Reference Data

## Objective

Phase A targets:

- **G3_PRIMARY_LISTING_HISTORY** — point-in-time primary listing exchange.
- **G4_SHARES_OUTSTANDING** — point-in-time shares outstanding.

Current committed requirements:

- 174 historical events
- 146 unique historical symbols
- 3,828 required symbol/date pairs
- G3 resolved: 0 / 174
- G4 resolved: 0 / 3,828

## Verified blocker

The repository does not contain an authorized historical NYSE Daily TAQ Master/reference export or equivalent historical security-master file. It also does not contain a populated SEC Companyfacts shares extract.

G3 must not be closed using guessed or current exchange assignments. G4 must not use future-filed shares facts.

## Canonical Phase A inputs

### Preferred historical security master

Use the existing source ID:

`authorized-nyse-daily-taq-master`

Expected logical fields:

- `symbol`
- `trade_date`
- `listed_exchange`
- `shares_outstanding_millions`

The source contract must contain the real entitlement/license reference. Raw licensed data belongs outside the public repository.

### Supplemental public shares source

The existing `src/sec_companyfacts_normalizer.py` supports already-downloaded SEC Companyfacts JSON and converts it into point-in-time shares records containing:

- `historical_symbol`
- `cik`
- `fact_date`
- `available_at`
- `shares_outstanding`
- `form`
- `accession`
- `source_reference`

Companyfacts can supplement G4. It does not replace the historical exchange source needed for G3.

## Ingestion

After the real files are present and the source paths/license references are configured, run:

```bash
PYTHONPATH=src python src/authorized_input_orchestrator.py ingest \
  --root . \
  --batch-manifest config/authorized_input_batch.phase_a.example.json \
  --runtime-dir private_runtime/authorized_input_ingestion \
  --outdir data/processed/authorized_input_ingestion \
  --expected-champion-sha256 0c8c16c9be734152c0018aa40e576fe4db9f4621359fafe521465890f9945616
```

The orchestrator will stage by content hash, rerun metadata resolution and quality checks, and report whether G3 and G4 actually transitioned to READY.

## Completion criteria

Phase A is gate-complete only when:

- `ready_g3_primary_listing_history = true`
- `ready_g4_shares_outstanding = true`

No synthetic, current-only, inferred, or guessed reference records should be used to force either gate.
