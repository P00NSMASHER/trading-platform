# Step 21 — Authorized-input ingestion orchestrator

`src/authorized_input_orchestrator.py` is the single fail-closed ingestion entrypoint for the historical surveillance research pipeline.

It does **not** fetch, purchase, scrape, or connect to any external data provider. It only accepts local files that are already present and explicitly described by Step-15/17-compatible source contracts.

## What it does

For each selected source file, in deterministic order, the orchestrator:

1. validates the source contract and rejects credential-like fields;
2. verifies authorization/license metadata where required by the underlying Step-15/17 contract;
3. hashes the local source file with SHA-256;
4. stages market/reference inputs in a private content-addressed runtime directory;
5. updates the cumulative active market or metadata contract;
6. reruns the point-in-time metadata resolver and Step-19 reconciliation gate;
7. reruns the Step-16 market coverage audit and Step-15 historical backfill manifest;
8. reruns the Step-20 G1–G11 release controller;
9. records the before/after gate state for that exact source file;
10. appends a hash-chained receipt to `authorized_input_ingestion_ledger.jsonl`.

Raw licensed source files are never copied into the report/output directory. The report bundle contains hashes, gate transitions, readiness summaries, and manifests only.

## Gate attribution

`imported_file_gate_map.csv` distinguishes:

- `potential_gates`: gates the source type can logically affect;
- `closed_gates`: gates that actually transitioned from BLOCKED to READY immediately after this file was imported;
- `opened_gates`: gates that regressed from READY to BLOCKED, which is treated as an auditable warning rather than silently ignored.

Examples:

- announcement timestamp → G1, plus derivative G6 quality;
- security master → G3/G4, plus derivative G6;
- shares series → G4, plus derivative G6;
- control universe → G5, plus derivative G6;
- TAQ/options/ITCH market source → G2.

G7–G11 are not claimed by a file merely because the file was imported. They remain independent controller gates.

## Batch manifest

```json
{
  "schema_version": "1",
  "batch_id": "authorized-import-001",
  "metadata": {
    "source_contract": "config/metadata_sources.example.json",
    "source_ids": ["your-announcement-source"]
  },
  "market": {
    "source_contract": "config/historical_market_sources.example.json",
    "source_ids": ["your-taq-trades-2015-02-17"]
  }
}
```

Do not put API keys, passwords, access tokens, refresh tokens, secrets, or other credentials in a batch manifest or source contract. Step 21 rejects credential-like manifest keys; earlier source-contract validators enforce the same policy.

## Run

```bash
PYTHONPATH=src python src/authorized_input_orchestrator.py ingest \
  --root . \
  --batch-manifest config/authorized_input_batch.example.json \
  --runtime-dir private_runtime/authorized_input_ingestion \
  --outdir data/processed/authorized_input_ingestion \
  --expected-champion-sha256 0c8c16c9be734152c0018aa40e576fe4db9f4621359fafe521465890f9945616
```

Current-state assessment without importing anything:

```bash
PYTHONPATH=src python src/authorized_input_orchestrator.py assess-current \
  --root . \
  --runtime-dir private_runtime/authorized_input_ingestion \
  --outdir data/processed/authorized_input_real \
  --expected-champion-sha256 0c8c16c9be734152c0018aa40e576fe4db9f4621359fafe521465890f9945616
```

Verify the append-only Step-21 ledger:

```bash
PYTHONPATH=src python src/authorized_input_orchestrator.py verify-ledger \
  --runtime-dir private_runtime/authorized_input_ingestion
```

## Release semantics

Step 21 does not itself authorize or run trading. It merely drives the existing offline surveillance-research readiness pipeline. A Step-20 `evaluation_release_token.json` can appear only if the complete G1–G11 controller passes on the exact cumulative inputs.

Even then, that token permits only the single offline historical champion/challenger surveillance evaluation described by Step 20. Automatic model promotion, broker connectivity, order generation, trade recommendations, position sizing, target prices, or live confidential-data ingestion remain prohibited.
