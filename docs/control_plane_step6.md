# Control-Plane Step 6 - G12-G15 and Signed Release Authority

Step 6 preserves the existing G1-G11 assessment and adds the four gates represented by the original Steps 12-15 before an offline historical evaluation may execute.

The legacy `evaluation_release_token.json` is no longer sufficient by itself to enter `run_if_released()`. The runner still reruns G1-G11 exactly as before, but it now also requires a freshly verified signed control-plane release-authority token.

## G12 - Point-in-time graph features

`G12_POINT_IN_TIME_GRAPH_FEATURES` requires the Step-12 graph feature evidence to remain:

- schema-compatible with Step 12;
- `research_use_only=true`;
- `visibility_mode=live_surveillance`;
- guarded by `observed_at <= as_of`;
- guarded by `public_at <= as_of` in live mode;
- explicit that later enforcement facts are excluded from live historical features;
- free of trading/output semantics;
- bound to the exact graph-feature SHA-256 already recorded by the G1-G11 assessment.

Historical-forensics graph features cannot pass G12.

## G13 - Graph challenger and ablation guardrails

`G13_GRAPH_CHALLENGER_GUARDRAILS` requires the Step-13 challenger to be non-synthetic and eligible only for human promotion review after all configured research checks pass:

- temporal average-precision gain;
- incremental graph value over the base-feature-only ablation;
- false-alert guardrail;
- Brier/calibration guardrail;
- no degradation on the unseen-issuer holdout;
- zero grouped-CV overlap for challenger and base ablation.

The frozen champion SHA-256 must match before and after the challenger run. Automatic promotion and active-model modification must remain disabled.

The exact challenger manifest and CV audit must match the hashes already bound into G1-G11.

## G14 - Real historical graph reconstruction

`G14_REAL_HISTORICAL_GRAPH` requires the Step-14 reconstruction to preserve the point-in-time distinction between live surveillance and later historical explanation:

- later enforcement information is invisible to historical live queries;
- live traversal uses `public_at`;
- the reconstruction is research-only;
- live stolen/private inputs remain prohibited;
- no historical live row sees the later enforcement case;
- the forensic audit sees the case only for explanation;
- the non-synthetic comparison-readiness gate is clear;
- the historical-event corpus hash agrees with the Step-15 market backfill.

Synthetic market fixtures cannot be relabeled as real Step-14 readiness.

## G15 - Authorized historical market backfill

`G15_AUTHORIZED_MARKET_BACKFILL` requires Step 15 to contain actual authorized, non-synthetic historical market sources:

- `eligible_for_real_feature_backfill=true`;
- `eligible_for_champion_challenger_unlock=true`;
- no `synthetic_fixture` source remains;
- every non-synthetic source is explicitly authorized;
- every non-synthetic source has a non-empty license/entitlement reference;
- credentials are not stored in source contracts;
- post-hoc five-minute realized-spread and price-impact fields remain barred from live model inputs;
- trading/output semantics remain prohibited;
- the exact market-backfill manifest hash matches G1-G11.

## Control-plane prerequisite

G12-G15 are not sufficient if the Step-2 through Step-5 control plane is unhealthy.

Before authority can be built, `verify_control_plane()` must pass its SQLite/FK checks, hash-chained information-event checks, HOLDING/quarantine hashes, signed publicity-clearance archives, active-contract checks, and recursive lineage verification.

## Signed release authority

An authority claim is built only when:

1. the unchanged G1-G11 assessment is release-ready;
2. G12-G15 all pass;
3. control-plane integrity passes;
4. the active champion hash equals the expected frozen champion.

The claim uses the fixed SSH namespace:

`mnpi-release-authority`

It binds:

- the deterministic G12-G15/control-plane assessment hash;
- a deterministic G1-G11 assessment hash with volatile generation time removed;
- the frozen champion SHA-256;
- every G1-G11 input hash;
- every Step-12 through Step-15 evidence hash;
- one-evaluation scope;
- research-only policy;
- explicit prohibition of automatic promotion, champion modification, broker connectivity, order generation, trade recommendations, position sizing, expected-return output, and live confidential-data ingestion.

The private signing key must remain outside the repository. Verification requires an external OpenSSH allowed-signers file whose SHA-256 is independently supplied and checked before `ssh-keygen` runs.

The exact verified claim and detached signature are archived content-addressably under:

`<control-dir>/release_authority/<authority_claim_sha256>/`

## Execution enforcement

`evaluation_release_controller.run_if_released()` still reruns G1-G11 and still hashes the champion before and after the challenger run.

Step 6 adds an additional fail-closed requirement: before the challenger harness is invoked, `run_if_released()` freshly verifies the signed authority and recomputes G12-G15 against the current evidence. A stale token, changed evidence, changed champion, bad signer trust, failed gate, or absent authority stops execution.

A successful authority still permits only one offline historical surveillance evaluation. It does not authorize model promotion, live confidential-data ingestion, trading advice, brokerage integration, or execution.

G1-G11 assessment semantics remain unchanged. Dashboard and account surveillance remain Step 7.
