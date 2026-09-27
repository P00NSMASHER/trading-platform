# One-command real-data replay

`src/real_data_replay.py` is the handoff point between licensed vendor delivery and the existing research pipeline.

It is deliberately provider-agnostic. The replay command does not know whether the authorized files came from NYSE, Cboe, Nasdaq, LSEG, or another lawful provider. It consumes the existing explicit market and metadata source contracts, validates the contents, recomputes every coverage/metadata gate, and advances only as far as the evidence permits.

## Run

Create a real market contract at `config/historical_market_sources.real.json` (never commit credentials), then:

```bash
PYTHONPATH=src python src/real_data_replay.py \
  --config config/real_data_replay.example.json
```

To make CI or a release job fail unless the non-synthetic offline evaluation is genuinely released:

```bash
PYTHONPATH=src python src/real_data_replay.py \
  --config config/real_data_replay.example.json \
  --require-ready
```

## Stages

The replay command performs these stages in order:

1. Rebuild exact market coverage against the supplied market contract.
2. Rerun point-in-time metadata resolution.
3. Rerun metadata quality/reconciliation.
4. Materialize only **resolved** shares-outstanding rows into baseline-engine format.
5. Run real market backfill when at least one non-synthetic authorized source is present.
6. Build historical baselines.
7. Build base feature vectors.
8. Build live-surveillance graph features when a graph DB is supplied.
9. Build matched controls when candidate-level point-in-time control metadata is supplied.
10. Train a challenger and execute the fail-closed release controller only when all real-data gates are genuinely ready.

Every run writes `real_data_replay_status.json` with the exact stage status and input hashes.

## Fail-closed rules

- Synthetic and real market sources are never silently mixed.
- Synthetic-only contracts can exercise tests but cannot run a real backfill.
- Reviewed G1/G4/G5 exclusions do not satisfy exact-timing, shares, or real-control requirements.
- Excluded shares rows are not materialized into turnover inputs.
- Challenger/release execution is dependency-blocked until G2, exact G1, real G5 controls, and metadata quality all clear.
- The active champion is never modified or auto-promoted.
- BUY/SELL, expected-return, target-price, position-size, order, and execution-instruction outputs remain prohibited.

## When licensed files arrive

The intended workflow is:

`drop files -> update source contract paths/mappings -> run one command -> inspect status receipt`

No vendor-specific code change should be necessary unless a vendor format itself cannot be mapped to the canonical schemas.
