# Control-Plane Step 8 - Adversarial CI and Final Audit Pack

Step 8 closes the implementation phase with an explicit adversarial CI lane and a deterministic final audit pack.

The goal is not to claim that the research system is ready for live trading. The goal is to prove that the control boundaries added in Steps 1-7 fail closed under the attack cases we can exercise in CI and that a reviewer can reconstruct the exact code, test, and trust state of the reviewed commit.

## Exact-head CI

Pull-request CI now explicitly checks out:

`github.event.pull_request.head.sha`

for every PR job.

This avoids relying on GitHub's default pull-request merge ref when the purpose of the audit is to bind evidence to the exact reviewed branch head.

All workflow jobs retain:

- `permissions: contents: read`;
- `persist-credentials: false`;
- full-SHA pins for external GitHub Actions.

## Adversarial CI job

PR CI contains a dedicated `Control-plane adversarial audit` job that runs only after the ordinary full test suite and independent secret scan succeed.

The adversarial suite attacks the main fail-closed boundaries directly:

- direct unstructured `HOLDING -> ADMITTED_STRUCTURED` bypass;
- forged publicity-clearance event;
- post-registration lineage-parent injection;
- ancestor-payload corruption during recursive recovery;
- repository-local release-authority signing key;
- allowed-signers trust-root mismatch before SSH verification;
- legacy G1-G11 execution bypass without signed G12-G15 authority;
- account mappings containing identity data;
- raw account-key persistence;
- non-loopback dashboard binding;
- committed-secret detection;
- release-drift verification with a wrong external trust root;
- frozen-champion hash drift.

The adversarial suite is additive to the full pytest suite. It does not replace normal regression testing.

## Deterministic audit pack

`scripts/control_plane_audit_pack.py` generates:

- `control_plane_audit.json`;
- `CONTROL_PLANE_AUDIT.md`;
- `SHA256SUMS`;
- the JUnit XML used as test evidence.

The pack binds:

- exact Git commit;
- exact Git tree;
- commit timestamp;
- SHA-256 over the full tracked-file tree;
- tracked-file count;
- frozen-champion SHA-256;
- current release-drift allowlist SHA-256;
- adversarial/full-test JUnit counts;
- repository secret-scan result;
- workflow supply-chain checks;
- security-policy presence;
- internal release-drift identity verification;
- external release-drift trust-root status.

The audit-pack ID is a SHA-256 over the canonical report body.

The commit timestamp rather than wall-clock generation time is used so repeated pack generation for the same checkout and test evidence remains reproducible.

## PR audit vs release audit

A PR audit and a release audit have deliberately different trust semantics.

### Pull-request audit

Automatic PR CI does not possess the independently stored release-drift trust root.

Therefore a valid PR pack can report:

- `audit_pack_pass=true`;
- `release_ready=false`;
- blocker: `external_release_drift_trust_root_not_verified`.

That is expected and fail closed.

### Manual release audit

`.github/workflows/synthetic-ci.yml` remains manual and requires the independently recorded SHA-256 of `config/release_drift_allowlist.json`.

The workflow:

1. checks out the exact dispatched commit;
2. verifies historical release drift against that externally supplied trust root;
3. applies runtime permission hardening;
4. runs the full test suite with JUnit evidence;
5. generates the audit pack with `--require-external-trust-root`;
6. uploads the resulting release-audit artifact;
7. independently runs the repository secret scan.

A wrong, missing, or stale external trust root prevents release-audit success.

## Audit artifact retention

The automatic PR audit pack is uploaded as a GitHub Actions artifact for 30 days.

The manually authenticated release audit pack is uploaded for 90 days.

The artifact-upload action is itself pinned to a reviewed full commit SHA.

## Final safety boundary

Completion of Step 8 means the eight-step control-plane implementation is complete and CI-verifiable.

It does not mean:

- the current 174-event corpus has obtained missing lawful real-market inputs;
- G1-G15 currently pass on the real corpus;
- an external release-drift trust root has been supplied for this branch;
- a release-authority signer has approved an evaluation;
- the challenger is approved for model promotion;
- the system is a trading system.

Automatic promotion, active-champion modification, broker connectivity, order generation, trade recommendations, position sizing, expected-return outputs, and live confidential-data ingestion remain prohibited.

Final release remains blocked until every external prerequisite required by the existing fail-closed release paths is satisfied and independently verified.
