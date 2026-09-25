# Control-Plane Implementation Baseline

This file freezes the pre-control-plane reference state used to judge later integration regressions.

## Source revision

- Baseline source branch: `main`
- Baseline source commit: `579730f1abb595579de199277a95a8c89f733d0f`
- Baseline source tree: `9e2045b68118ce6c475a2b4d553178795c6c73c5`
- Source commit signature reported by GitHub: verified

No control-plane implementation files existed at this source revision.

## Frozen champion

Expected frozen champion SHA-256:

`0c8c16c9be734152c0018aa40e576fe4db9f4621359fafe521465890f9945616`

The current release assessment records the same champion hash and records the challenger before/after hashes as identical.

## G1-G11 release-controller baseline

Reference artifact:

`data/processed/evaluation_release_real/evaluation_release_assessment.json`

Recorded state:

- `evaluation_release_permitted = false`
- `release_status = BLOCKED`
- check count: 22
- passed checks: 15
- blocking failures: 7

Blocking gates:

- G1_ANNOUNCEMENT_TIMES
- G2_REAL_MARKET_DATA
- G3_PRIMARY_LISTING_HISTORY
- G4_SHARES_OUTSTANDING
- G5_MATCHED_CONTROL_UNIVERSE
- G6_METADATA_QUALITY
- G11_NON_SYNTHETIC_RESEARCH_ONLY

Passing control areas include:

- G7 temporal feature integrity
- G8 holdout isolation
- G9 provenance/hash consistency
- G10 champion immutability

The baseline therefore intentionally remains fail-closed for a non-synthetic evaluation.

## Existing runtime-hardening evidence

Reference artifact:

`data/processed/hardening_demo/final_self_check.json`

Recorded state:

- overall self-check: PASS
- model verification: PASS
- case DB integrity: PASS
- review chains: PASS
- filesystem permission checks: PASS
- loopback-only policy: PASS
- network binding disabled: PASS
- execution integration disabled: PASS
- trade outputs disabled: PASS

Recorded hardening audit SHA-256:

`d86b4f944698ddc79a60347407ff4677472370d968067235c9851f2c3cf52977`

## Existing test evidence

Persisted hardening test artifact:

`data/processed/hardening_demo/pytest.txt`

records:

`83 passed in 10.36s`

`FROZEN_CHAMPION.md` separately records `155 / 155 passing` at the champion freeze.

These are historical repository artifacts, not a claim that pytest was re-executed locally at the source commit during this baseline step.

The connected execution sandbox could not resolve github.com for a local clone, and GitHub Actions has no completed workflow run attached to source commit `579730f1abb595579de199277a95a8c89f733d0f`. A draft PR from the implementation branch is used to obtain fresh PR-CI evidence without changing surveillance runtime code.

## Release-drift trust-root state

Current `config/release_drift_allowlist.json` content SHA-256 as independently recomputed in this session from the GitHub file bytes:

`f23db7d3da5af4df47a0ad5a1fb2b79806baffd71d8de6f92e368374236ff964`

This value is recorded as a candidate baseline digest only. It is not represented here as an independently stored external trust root. Release verification must continue to require the external trust-root value.

## Regression contract for subsequent implementation steps

Every subsequent control-plane step must verify, unless an explicitly reviewed change says otherwise:

1. frozen champion remains byte-identical;
2. existing G1-G11 semantics remain unchanged;
3. current intentionally blocked real evaluation does not become released merely because control-plane code is added;
4. no broker/order/execution capability is introduced;
5. no control-plane field becomes a predictive feature;
6. protected source content does not leak into ordinary audit/report artifacts.

This baseline is evidence only. It does not authorize a model release, model promotion, trade recommendation, broker connection, or order execution.
