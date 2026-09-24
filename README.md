# Private MNPI / Informed-Trading Surveillance Prototype

This prototype is a **historical market-surveillance research system**, not a trading system.
It must not generate trade directions, expected returns, target prices, orders, or position sizes.

## Step 1 — Historical corpus builder

Implemented in `src/corpus_builder.py`.

Input:
- `data/raw/TimeOfFirstTrade.csv` from `vgreg/hacked_earnings_jfe`.

Output:
- `data/processed/historical_events.csv` — normalized historical ground-truth records.
- `data/processed/manifest.json` — source provenance, schema version, hash, validation summary.

The exact public announcement timestamp is deliberately left blank. It will only be populated in a later authorized point-in-time join. This prevents fabricated precision and keeps the historical first-trade label separate from any future market-data adapter.

Run:

```bash
python src/corpus_builder.py \
  --input data/raw/TimeOfFirstTrade.csv \
  --output-dir data/processed
```

Tests:

```bash
pytest -q
```

## Privacy / deployment status

- Local sandbox only.
- No public repository created.
- No external notifications or outreach.
- No brokerage/execution integration.

## Step 2 — Lawful historical market-data adapter

Implemented in `src/market_data_adapter.py`.

The adapter normalizes equity trades, equity quotes, option trades, and option quotes into a single UTC point-in-time event schema, validates malformed/crossed data, and creates minute aggregates in `equity_minutes.csv` and `option_minutes.csv`. Input-file SHA-256 hashes are recorded in `market_data_manifest.json`.

A synthetic fixture is included under `data/examples/` only for automated testing. No live brokerage or data-vendor connection is enabled.

Example run:

```bash
python src/market_data_adapter.py \
  --input equity_trade=data/examples/equity_trades.csv \
  --input equity_quote=data/examples/equity_quotes.csv \
  --input option_trade=data/examples/option_trades.csv \
  --input option_quote=data/examples/option_quotes.csv \
  --source-name synthetic_fixture \
  --output-dir data/processed/market_data_demo
```

Schema details: `docs/market_data_schema.md`.

## Step 3 — Point-in-time baseline engine

Implemented in `src/baseline_engine.py`.

The baseline engine compares every minute observation with the same security at the same local market minute over the preceding 21 available trading dates. It computes rolling mean/std, median/MAD, conventional z-scores, robust z-scores, and baseline ratios without using the current or any future observation.

Minute turnover is supported only when a point-in-time shares-outstanding file is provided. Future share-count records are explicitly excluded.

Example:

```bash
python src/baseline_engine.py \
  --equity-minutes data/processed/market_data_demo/equity_minutes.csv \
  --option-minutes data/processed/market_data_demo/option_minutes.csv \
  --output-dir data/processed/baseline_demo
```

With shares outstanding:

```bash
python src/baseline_engine.py \
  --equity-minutes equity_minutes.csv \
  --shares-file shares_outstanding.csv \
  --output-dir baselines
```

Details: `docs/baseline_engine.md`.

## Step 4 — Backward-looking surveillance feature engine

Implemented in `src/feature_engine.py`.

The feature engine transforms Step-3 baseline z-scores into point-in-time surveillance features: volume/turnover anomalies, persistence and acceleration, spread response, option/equity activity, trailing price behavior, and multivariate change indicators. Every feature uses only the current minute or earlier data.

Example:

```bash
python src/feature_engine.py \
  --baseline-metrics data/processed/baseline_demo/baseline_metrics.csv \
  --equity-minutes data/processed/market_data_demo/equity_minutes.csv \
  --option-minutes data/processed/market_data_demo/option_minutes.csv \
  --output-dir data/processed/feature_demo
```

Details: `docs/feature_engine.md`.

## Step 5 — Point-in-time matched-control generator

Implemented in `src/matched_control_generator.py`.

The matcher selects same-date, same-local-minute control windows using only metadata that was effective at or before the historical treated-event timestamp. Step-4 anomaly features are used only to confirm that a comparable window exists; they are not matching covariates.

Default matching covariates include point-in-time market cap, price, trailing volatility, normal minute volume/turnover/spread, option liquidity, institutional ownership, analyst coverage, borrow cost, and pre-event return. Same sector, index bucket, and scheduled-event status are matched when available. Known positive-event securities on the same date and optional contamination windows are excluded.

Example with the synthetic fixture:

```bash
python src/matched_control_generator.py \
  --events data/examples/matching_events.csv \
  --feature-vectors data/examples/matching_feature_vectors.csv \
  --metadata data/examples/matching_metadata.csv \
  --output-dir data/processed/match_demo
```

Outputs:

- `matched_controls.csv`
- `match_events.csv`
- `match_balance.csv`
- `match_manifest.json`

Details: `docs/matched_controls.md`.

## Step 6 — Offline model-training harness

Implemented in `src/model_training_harness.py`.

The harness converts Step-5 matched events into treated/control training samples and fits two **surveillance-only** classifiers using only the point-in-time Step-4 feature allowlist:

- elastic-net logistic regression;
- shallow histogram gradient boosting.

Their equal-weight blend is calibrated only from grouped out-of-fold development predictions. By default, events before 2015 are development data and 2015+ is a locked temporal holdout. Cross-validation groups on the treated issuer, so a treated event and all of its matched controls stay together and the same treated issuer cannot leak across a fold boundary.

The alert threshold is selected on development OOF predictions subject to a configured false-positive-rate ceiling. Holdout data is not used for model selection, calibration, or threshold tuning.

Example using the included **synthetic-only** fixture:

```bash
python src/model_training_harness.py \
  --matched-controls data/examples/model_training_matched_controls.csv \
  --feature-vectors data/examples/model_training_feature_vectors.csv \
  --output-dir data/processed/model_demo \
  --holdout-start-year 2015 \
  --target-fpr 0.10 \
  --cv-folds 4
```

Outputs:

- `model_bundle.joblib`
- `holdout_scores.csv`
- `training_manifest.json`
- `elastic_net_coefficients.csv`
- `development_calibration.csv`
- `cv_split_audit.json`

The included demo is deliberately easy synthetic data used only to verify plumbing; its near-perfect metrics are **not evidence of real-world detector performance**.

Details: `docs/model_training_harness.md`.

## Step 7 — Blind external-validation harness

Implemented in `src/external_validation_harness.py`.

The external-validation harness freezes the Step-6 model and scores separate historical case families without retraining, recalibration, or threshold tuning. Blind scoring and ground-truth evaluation are split into separate commands: the scoring command cannot read labels or outcomes, while the evaluation command joins a sealed ground-truth file only after scores have been written.

Supported cohort labels include EDGAR-hack, FDA/regulatory, cross-security, M&A tipper-tippee, other adjudicated cases, and synthetic demo fixtures. Adjudication/source metadata is preserved for provenance but never passed into the model feature matrix.

Example using the included **synthetic-only** external-validation fixture:

```bash
python src/external_validation_harness.py score \
  --model-bundle data/processed/model_demo/model_bundle.joblib \
  --registry data/examples/external_validation_registry.csv \
  --feature-vectors data/examples/external_validation_feature_vectors.csv \
  --output-dir data/processed/external_validation_demo/scoring

python src/external_validation_harness.py evaluate \
  --scores-csv data/processed/external_validation_demo/scoring/external_scores.csv \
  --ground-truth data/examples/external_validation_ground_truth.csv \
  --output-dir data/processed/external_validation_demo/evaluation
```

Outputs:

- `scoring/external_scores.csv`
- `scoring/external_scoring_manifest.json`
- `evaluation/external_evaluation_rows.csv`
- `evaluation/external_validation_report.json`

The demo is deliberately separable synthetic data used only to verify blind-scoring plumbing. Its perfect metrics are **not evidence of real-world detector performance**. Real external validation requires lawful historical market features reconstructed around independently documented adjudicated cases.

Details: `docs/external_validation_harness.md`.

## Step 8 — Private case database + evidence generator

Implemented in `src/case_evidence.py`.

Step 8 converts a surveillance score into a local, immutable case file. Core evidence tables reject updates/deletes; human review is append-only and SHA-256 hash chained. Each case snapshots the scored minute, model-input features, matched controls, model/source hashes, and a review history. Export creates a reproducible evidence bundle with a bundle-root integrity hash while deliberately **not embedding raw licensed/proprietary data**.

The case file explicitly states that a surveillance score is not a finding of insider trading or MNPI misuse, and no BUY/SELL, expected-return, target-price, position-size, or order fields are generated.

Synthetic demo:

```bash
python src/case_evidence.py ingest \
  --db data/processed/case_demo/cases.sqlite \
  --case-id CASE-H001 \
  --sample-id H001:TREATED \
  --scores-csv data/processed/model_demo/holdout_scores.csv \
  --feature-vectors data/examples/model_training_feature_vectors.csv \
  --model-bundle data/processed/model_demo/model_bundle.joblib \
  --matched-controls data/examples/model_training_matched_controls.csv \
  --training-manifest data/processed/model_demo/training_manifest.json

python src/case_evidence.py export \
  --db data/processed/case_demo/cases.sqlite \
  --case-id CASE-H001 \
  --output-dir data/processed/case_demo/evidence
```

Details: `docs/case_evidence.md`.

## Step 9 — Private localhost dashboard

Implemented in `src/private_dashboard.py`. The dashboard binds only to loopback, rejects external Host headers, uses per-launch CSRF protection for review/export actions, and displays Step-8 case evidence without exposing raw licensed market data. It includes filters, timelines, feature explanations, matched controls, provenance hashes, review-chain integrity, append-only dispositions, and local evidence export.

Run the synthetic case demo locally:

```bash
python src/private_dashboard.py \
  --db data/processed/case_demo/cases.sqlite \
  --host 127.0.0.1 \
  --port 8765 \
  --open-browser
```

Details: `docs/private_dashboard.md`.


## Step 10 — Final audit and deployment hardening

Implemented in `src/deployment_hardening.py` and the fail-closed launcher `src/private_runtime.py`.

Step 10 adds:

- exact runtime/test dependency locks (`requirements.lock`, `requirements-dev.lock`);
- separate TOML runtime configuration with private local configs ignored by Git;
- owner-only runtime permissions on sensitive files/directories where the OS permits;
- frozen-model and training-manifest verification;
- SQLite integrity/foreign-key/review-chain/model-hash preflight checks;
- verified SQLite online backups with hashed manifests and logical fingerprints;
- atomic, verified restore that refuses corrupt/tampered backups;
- a disaster-recovery drill that deliberately corrupts a temporary backup and requires detection;
- a safe runtime launcher that runs the hardening/preflight before starting the localhost dashboard;
- `docs/deployment_runbook.md` covering installation, backup, recovery, launch, and failure response.

Validated demo commands:

```bash
python src/deployment_hardening.py harden-permissions --config config/runtime.demo.toml
python src/deployment_hardening.py self-check --config config/runtime.demo.toml
python src/deployment_hardening.py recovery-drill --config config/runtime.demo.toml
```

For a private local deployment, copy `config/runtime.example.toml` to `config/runtime.local.toml` and launch via:

```bash
python src/private_runtime.py --config config/runtime.local.toml --open-browser
```

The safe runtime remains surveillance-only, loopback-only, and has no live broker/execution integration.

## Step 10 — Final audit + private deployment hardening

Implemented in `src/deployment_hardening.py`.

Step 10 adds fail-closed runtime configuration, pinned runtime/test dependencies, owner-only filesystem permissions, model/training/database integrity checks, verified SQLite backups, protected backup manifests, restore verification, and a destructive corruption/recovery drill performed only on temporary copies. The runtime policy rejects non-loopback deployment, execution integration, and trade-output enablement.

Validated demo hardening commands:

```bash
python src/deployment_hardening.py harden-permissions \
  --config config/runtime.demo.toml \
  --report data/processed/hardening_demo/permissions.json

python src/deployment_hardening.py self-check \
  --config config/runtime.demo.toml \
  --report data/processed/hardening_demo/self_check.json

python src/deployment_hardening.py recovery-drill \
  --config config/runtime.demo.toml \
  --report data/processed/hardening_demo/recovery_drill.json
```

Private operational instructions: `docs/private_deployment_runbook.md`.

## Step 11 — Cross-Event Intelligence Graph

Implemented in `src/cross_event_graph.py`.

Step 11 adds an append-only, point-in-time relationship graph connecting historical cases/events to issuers, securities, people and organizations. It supports graph-aware related-security expansion, contamination blocklists for matched-control construction, and structural case-similarity search without producing trade directions or expected-return outputs.

The graph has separate `live_surveillance` and `historical_forensics` visibility modes. In live mode, later enforcement/adjudication relationships are hidden until their recorded `public_at` time, preventing future enforcement information from leaking into historical simulations.

The loader accepts only adjudicated/official/public/licensed-authorized/synthetic sources and explicitly rejects live stolen information, leaked credentials, accidental private disclosures, and unverified private sources.

Synthetic demo:

```bash
python src/cross_event_graph.py build \
  --nodes data/examples/cross_event_nodes.csv \
  --edges data/examples/cross_event_edges.csv \
  --db data/processed/graph_demo/cross_event_graph.sqlite \
  --manifest data/processed/graph_demo/graph_manifest.json

python src/cross_event_graph.py expand \
  --db data/processed/graph_demo/cross_event_graph.sqlite \
  --seed-security SEC:SYN-A \
  --as-of 2016-08-18T19:30:00Z \
  --mode live_surveillance \
  --max-hops 2 \
  --output data/processed/graph_demo/related_securities_live.csv
```

Details: `docs/cross_event_intelligence_graph.md`.

## Step 12 — Graph-Aware Surveillance Features

Implemented in `src/graph_feature_engine.py`.

Step 12 combines the Step-4 point-in-time market features with the Step-11 relationship graph to measure related-security breadth, synchronized anomalies, confidence/distance-weighted peer anomaly intensity, propagation strength, graph distance to anomalous peers, and similarity to only those historical cases visible under the same point-in-time rules.

During implementation, Step 11's temporal semantics were tightened: graph edges must now satisfy `observed_at <= as_of` in both live and historical-forensics modes, preventing genuinely later events from being back-projected into earlier graphs. Live mode continues to require `public_at <= as_of`, so later enforcement/adjudication facts cannot leak into live historical scoring.

Synthetic demo:

```bash
python src/graph_feature_engine.py \
  --feature-vectors data/examples/graph_feature_input.csv \
  --graph-db data/processed/graph_demo/cross_event_graph.sqlite \
  --output-dir data/processed/graph_feature_demo \
  --mode live_surveillance \
  --max-hops 2
```

Details: `docs/graph_aware_surveillance_features.md`.

## Step 13 — Graph-Aware Challenger Model

Implemented in `src/graph_challenger_harness.py`.

Step 13 trains an offline challenger that joins the Step-4 point-in-time market-surveillance feature allowlist to the Step-12 `live_surveillance` graph features. The Step-6 champion remains frozen and is SHA-256 checked before and after every challenger run. Historical-forensics graph vectors are rejected from training.

The harness compares three models on the same issuer/time-separated holdout:

1. frozen Step-6 champion;
2. full graph-aware challenger;
3. base-feature-only challenger ablation.

Promotion is never automatic. A challenger can only become *eligible for human review* if it improves temporal and unseen-issuer performance, demonstrates incremental graph value over the base ablation, and stays inside configured false-alert and calibration guardrails. Synthetic fixtures are categorically blocked from promotion eligibility even when metrics look strong.

Synthetic demo:

```bash
PYTHONPATH=src python src/graph_challenger_harness.py \
  --matched-controls data/examples/model_training_matched_controls.csv \
  --base-features data/examples/model_training_feature_vectors.csv \
  --graph-features data/examples/model_training_graph_features.csv \
  --champion-bundle data/processed/model_demo/model_bundle.joblib \
  --output-dir data/processed/graph_challenger_demo \
  --target-fpr 0.10
```

The bundled demo intentionally does **not** justify promotion: the existing synthetic Step-6 fixture is already perfectly separable, so the graph features add no measurable average-precision gain. The active champion is not modified.

Details: `docs/graph_challenger_model.md`.

## Step 14 — Real Historical Graph Reconstruction

Implemented in `src/historical_graph_reconstruction.py`.

Step 14 replaces the synthetic graph-only demonstration with a real historical graph reconstructed from the 174 SEC-complaint-derived first-trade events in `vgreg/hacked_earnings_jfe`. It converts the original New York market timestamps to UTC, creates 174 event nodes, 146 issuer nodes, 146 historical security nodes, and one public SEC case node, then builds 668 provenance-bearing edges.

The enforcement relationship is deliberately **not** back-projected into the original 2011–2015 trade windows. The SEC case edges have `public_at=2015-08-11T23:59:59Z`, a conservative end-of-day timestamp because the official release gives the date but not a release time. As a result, all 174 historical event-time `live_surveillance` probes correctly see zero enforcement-case visibility, while `historical_forensics` can use later-public records to explain earlier events without contaminating live scoring.

The current workspace still does not contain the paper's proprietary merged TAQ/ITCH/CBOE minute-level feature panel. The Step-14 readiness gate therefore refuses to run or report a non-synthetic champion/challenger comparison against the existing synthetic market fixtures. This is intentional fail-closed behavior.

Run:

```bash
PYTHONPATH=src python src/historical_graph_reconstruction.py \
  --historical-events data/processed/historical_events.csv \
  --output-dir data/processed/historical_graph_real \
  --base-features data/examples/model_training_feature_vectors.csv \
  --matched-controls data/examples/model_training_matched_controls.csv
```

Details: `docs/real_historical_graph_reconstruction.md`.


## Step 15 — Authorized Historical Market-Data Backfill

Implemented in `src/historical_market_backfill.py`.

Step 15 adds a production import-contract layer for lawfully obtained historical NYSE Daily TAQ, decoded Nasdaq TotalView-ITCH 5.0, Cboe option trades/quotes, and explicitly mapped equivalent sources. It requires per-source authorization, provenance, data classification, format/specification version, timezone, delimiter, and canonical column mappings; credentials are never stored in the contract.

The backfill reconstructs:

- normalized equity/options event records;
- equity and option minute aggregates;
- decoded ITCH execution/order-flow minutes;
- TAQ-inferred signed volume and effective spreads;
- post-hoc 5-minute realized-spread/price-impact research measures, explicitly barred from live model inputs;
- event-aligned minute panels around each documented first illicit trade;
- per-event coverage and source-hash provenance.

Synthetic fixtures can validate the plumbing but cannot unlock a real champion/challenger comparison. The current workspace still contains no licensed historical TAQ/ITCH/Cboe backfill, so real performance evaluation remains fail-closed.

Validate a source contract:

```bash
python src/historical_market_backfill.py validate-contract \
  --contract config/historical_market_sources.example.json
```

Synthetic plumbing demo:

```bash
python src/historical_market_backfill.py backfill \
  --contract config/historical_market_sources.example.json \
  --events data/examples/backfill_events.csv \
  --output-dir data/processed/historical_market_backfill_demo \
  --pre-minutes 1 \
  --post-minutes 1
```

Details: `docs/historical_market_backfill.md`.

## Step 16 — Coverage planner / real-data readiness audit

`src/coverage_planner.py` turns the 174 historical first-trade events into an exact XNYS calendar-aware import plan. It deduplicates event + 21-session baseline coverage, skips early-close sessions that cannot support the same-minute baseline, enumerates TAQ/options/conditional-ITCH source dates, and fails closed on missing announcement times, real market files, listing history, shares outstanding, and matched-control metadata. It does not fetch or purchase data.


## Step 17 — Point-in-time metadata resolver

Implemented in `src/metadata_resolver.py`.

Step 17 resolves the four non-market-data gates left by the coverage planner:

- exact first-public announcement timestamps;
- historical primary listing exchange;
- effective-dated shares outstanding;
- same-day point-in-time control-universe metadata.

The resolver is fail-closed. EDGAR acceptance timestamps are retained as public proxies but are not treated as proof of the first public-release instant. Historical exchange and shares can be supplied from an authorized NYSE Daily TAQ Master history; future-filed shares facts are rejected. A retrospective research universe such as `SampleFirms` can enumerate same-day candidates but cannot close the point-in-time matching gate unless availability timestamps and the required pre-event covariates are present.

The metadata contract rejects credential-like fields and prohibits live stolen information, leaked credentials, accidental private disclosures, and unauthorized private data.

Synthetic plumbing demo:

```bash
PYTHONPATH=src python src/metadata_resolver.py \
  --events data/examples/metadata/events.csv \
  --symbol-dates data/examples/metadata/symbol_dates.csv \
  --contract config/metadata_sources.demo.json \
  --outdir data/processed/metadata_resolver_demo
```

Real-corpus readiness audit:

```bash
PYTHONPATH=src python src/metadata_resolver.py \
  --events data/processed/historical_events.csv \
  --symbol-dates data/processed/coverage_plan_real/symbol_date_requirements.csv \
  --contract config/metadata_sources.example.json \
  --outdir data/processed/metadata_resolution_real
```

Details: `docs/point_in_time_metadata_resolver.md`.

## Step 18 — Incremental metadata population pipeline

Step 18 turns the Step-17 source contracts into cumulative, content-addressed metadata batches. Each imported source is validated, hashed, privately staged, added to a cumulative active contract, and followed by a fresh readiness calculation. Every batch receives a hash-chained receipt and explicit coverage delta.

The pipeline supports authorized Daily TAQ Master/reference exports, exact authorized/public announcement timestamps, public SEC Companyfacts shares records, and point-in-time control-universe files. Identical source hashes are idempotent no-ops. Raw licensed inputs are never copied into metadata-only report bundles.

A local `sec_companyfacts_normalizer.py` converts already-downloaded SEC Companyfacts JSON plus an effective-dated CIK→historical-symbol map into conservative point-in-time shares records. It does not fetch SEC data itself.

The synthetic population demo closes G1, then G3/G4, then G5 across three separate batches and verifies the append-only ledger. The real 174-event corpus remains fail-closed until genuine authorized/public metadata files are supplied.

See `docs/metadata_population_pipeline.md` and `data/processed/metadata_population_real/step18_release_self_check.json`.

## Step 19 — Metadata quality / reconciliation gate

Implemented in `src/metadata_quality.py` and integrated into `src/metadata_population.py`.

Step 19 makes metadata coverage necessary but no longer sufficient for non-synthetic model evaluation. It compares all point-in-time candidate records across sources and quarantines material contradictions in exact announcement timestamps, overlapping primary-exchange histories, shares-outstanding facts, and duplicate control-universe covariates. Source precedence never overrides a blocking contradiction.

A clean synthetic fixture can exercise the entire layer but is explicitly unable to set the real evaluation release flag. The effective gate is `quality_cleared_for_non_synthetic_model_evaluation`; Step 18 population reports expose the same decision as `evaluation_release_gate`.

The packaged conflict fixture intentionally has complete resolver coverage while containing contradictory metadata. Step 19 blocks it, demonstrating that coverage cannot bypass reconciliation.

See `docs/metadata_quality_reconciliation.md`, `data/processed/metadata_quality_demo/metadata_quality_summary.json`, and `data/processed/metadata_quality_conflict_demo/metadata_quality_summary.json`.

## Step 20 — End-to-end evaluation release controller

Implemented in `src/evaluation_release_controller.py`.

Step 20 adds a single fail-closed controller in front of any non-synthetic offline historical champion/challenger surveillance evaluation. It requires all earlier data gates plus independent integrity checks to pass before it writes `evaluation_release_token.json`.

The controller verifies:

- G1 exact public announcement timing;
- G2 complete authorized non-synthetic historical market-data coverage;
- G3 point-in-time primary listing history;
- G4 point-in-time shares outstanding;
- G5 point-in-time matched-control universe;
- G6 Step-19 metadata quality/reconciliation clearance;
- G7 live-surveillance-only graph features and no prohibited future/post-hoc fields;
- G8 temporal holdout isolation, development-only calibration/threshold selection, and zero grouped-CV overlap;
- G9 SHA-256 provenance across the coverage plan, market backfill, metadata resolver, champion manifest, challenger manifest, and exact feature/control files;
- G10 byte-for-byte champion immutability;
- G11 non-synthetic, research-only policy with trading/execution outputs prohibited.

A release token, when issued, is bound to the exact input hashes and permits one offline historical surveillance comparison only. It never permits auto-promotion, active-champion modification, broker connectivity, order generation, or trading recommendations.

The current 174-event corpus remains correctly **BLOCKED**. Its integrity checks pass, but real market/reference coverage is still absent and the packaged model feature fixtures are synthetic. Therefore no Step-20 release token exists and no real champion/challenger performance claim is produced.

Current assessment:

```bash
cat data/processed/evaluation_release_real/evaluation_release_assessment.json
```

Details: `docs/evaluation_release_controller.md` and `data/processed/evaluation_release_real/step20_release_self_check.json`.

## Step 21 — Authorized-input ingestion orchestrator

Implemented in `src/authorized_input_orchestrator.py`.

Step 21 combines the ingestion/readiness pieces from Steps 15–20 into one auditable local pipeline. It consumes the Step-16 requirements, imports only already-present files described by authorized source contracts, stages them by content hash, reruns metadata resolution/reconciliation, reruns historical-market coverage/backfill readiness, and finally reruns the G1–G11 Step-20 release controller.

Every individual source file receives a before/after gate snapshot. `imported_file_gate_map.csv` records both the gates a source type can affect and the gates it actually closed. Identical re-imports are NO_OPs and cannot claim a second gate closure. All imports are appended to a hash-chained Step-21 ledger.

The orchestrator never fetches or purchases data, stores credentials, copies raw licensed inputs into report bundles, connects a broker, produces orders, or emits trading recommendations. The current real corpus remains blocked because no real authorized market/reference batch has been supplied and the packaged model-evaluation fixtures remain synthetic.

See `docs/authorized_input_ingestion_orchestrator.md` and `data/processed/authorized_input_real/authorized_input_current_assessment.json`.
