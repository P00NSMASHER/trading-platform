# Step 20 — End-to-End Evaluation Release Controller

Step 20 adds a single fail-closed controller in front of any non-synthetic offline champion/challenger surveillance evaluation.

It does **not** create trading advice, connect to a broker, ingest live confidential information, or promote a model automatically.

## Release gates

A release token is written only when every blocking gate passes:

1. **G1 — exact announcement timing**: all historical events have accepted point-in-time first-public timestamps.
2. **G2 — real historical market data**: the Step-16 source/date footprint is fully covered by authorized non-synthetic market data and the Step-15 backfill reports eligible real coverage.
3. **G3 — primary listing history**: historical primary exchange is resolved point-in-time.
4. **G4 — shares outstanding**: every required symbol/date has point-in-time shares data.
5. **G5 — matched-control universe**: every required event date has a point-in-time control universe.
6. **G6 — metadata quality**: Step 19 is clear, with zero blocking conflicts/quarantines and non-synthetic status.
7. **G7 — temporal feature integrity**: graph rows are `live_surveillance` only, research-only flags are present, and prohibited future/post-hoc fields are absent from model inputs.
8. **G8 — holdout isolation**: temporal development/holdout separation is reproduced, no event/sample crosses the boundary, grouped CV has zero group overlap, and calibration/threshold selection remain development-only.
9. **G9 — provenance**: the events, market contract, matched controls, base features, and graph features exactly match the hashes recorded in their producing manifests.
10. **G10 — champion immutability**: the active champion SHA-256 equals its frozen expected hash and the Step-13 before/after hashes.
11. **G11 — non-synthetic research-only policy**: no synthetic fixture is present, every component is research-only, and trading/execution outputs remain prohibited.

## Release token

When all gates pass, `evaluation_release_token.json` binds the authorization to the exact input SHA-256 values and champion hash. It permits one **offline historical surveillance evaluation** only. It does not authorize auto-promotion or active-model modification.

When any gate fails, no token is written.

## Controlled execution

`run_if_released()` reruns all checks, then invokes the existing graph-aware challenger harness only if the release assessment is clear. The active champion is hashed immediately before and after the evaluation and the run aborts if it changes.

The current public/synthetic prototype remains blocked because the authorized real market-data footprint and real point-in-time metadata are not populated.
