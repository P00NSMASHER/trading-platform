# Repository integrity controls

## Current controls

- The repository is public; no raw licensed/vendor inputs, private runtime state, credentials, or signing material may be committed.
- Runtime model bytes are checked against a trusted SHA-256 before `joblib.load`.
- Step-20/21 provenance gates hash critical model/data artifacts.
- Automatic pull-request CI and the manual release-audit workflow both have read-only repository permissions and pin external actions to reviewed full commit SHAs.
- Pull-request jobs explicitly check out the pull request head SHA rather than relying on the default synthetic merge ref.
- PR CI runs the full test suite, secret scan, a dedicated adversarial control-plane suite, and produces a downloadable audit pack.
- The manual release workflow additionally requires the independently recorded release-drift trust-root SHA-256 and produces an externally authenticated release audit pack.
- The workflow receives no market-data credentials, broker credentials, or private runtime inputs.
- A local tracked-file secret scan runs in CI.
- Raw licensed/vendor inputs are ignored and belong outside Git.
- `CODEOWNERS` identifies the repository owner for future protected-review rules.

## GitHub controls

This repository may not have plan-level branch protection/rulesets available. If/when available, enable:

1. require pull requests before merging to `main`;
2. require the synthetic test and secret-scan checks;
3. require the branch to be up to date before merge;
4. block force pushes and branch deletion;
5. require signed commits if practical;
6. require code-owner review when more than one trusted maintainer exists.

Until those controls are available, use PRs for code changes and preserve an independently recorded SHA-256 or signed tag for important releases.

## Release procedure

Before treating a commit as a trusted prototype release:

```bash
python scripts/secret_scan.py --root .
PYTHONPATH=src python -m pytest -q
sha256sum data/processed/model_demo/model_bundle.joblib
```

PR CI additionally runs `tests/test_control_plane_adversarial.py` and generates `control_plane_audit.json`, `CONTROL_PLANE_AUDIT.md`, and audit-pack `SHA256SUMS`. A PR audit pack deliberately reports `release_ready=false` when the independent release-drift trust root was not supplied.

For a release candidate, dispatch `.github/workflows/synthetic-ci.yml` with the independently stored SHA-256 of `config/release_drift_allowlist.json`. That workflow re-verifies historical release drift, runs the full test suite, regenerates the audit pack, and requires `external_release_drift_trust_root_verified=true`.

The model hash must match the currently trusted frozen-champion value before any model deserialization or private runtime launch.


## Historical release drift

`RELEASE_MANIFEST.json` and `SHA256SUMS` remain the immutable Step-21 package record. Later security patches are declared in `config/release_drift_allowlist.json`, which is an explicit reviewed trust root.

Run:

```bash
python scripts/verify_release_drift.py \
  --root . \
  --expected-exceptions-sha256 <independently-recorded-allowlist-sha256>
```

The verifier requires unchanged historical files to match their original SHA-256/size, intentional modified files and repository additions to match reviewed SHA-256 content identities, and rejects undeclared tracked files. It also refuses release approval unless the allowlist itself matches an independently supplied SHA-256. Record that hash outside the repository (for example in an offline release note, signed tag record, or other trusted channel); reading the hash from the same working tree is not an independent trust check.

## Safer model persistence

The currently active champion remains the hash-verified joblib artifact. `src/model_artifact.py` provides an optional migration to `skops.io`. A skops runtime requires both the model artifact SHA-256 and the separately reviewed trusted-types file SHA-256 to match before model loading.


## External signed release attestation

For higher-assurance releases, use `scripts/release_attestation.py` after drift verification. The generated attestation binds the exact Git commit, SHA-256 digest of the tracked tree, Step-21 release evidence, current drift allowlist, and frozen champion.

Sign the attestation with an SSH signing key held outside this repository and verify it against an externally maintained allowed-signers file whose SHA-256 is recorded separately. See `docs/release_attestation.md`.

The private signing key, signed attestation, detached signature, and allowed-signers trust file should remain outside Git.
