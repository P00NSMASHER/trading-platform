# Repository integrity controls

## Current controls

- The repository is private.
- Runtime model bytes are checked against a trusted SHA-256 before `joblib.load`.
- Step-20/21 provenance gates hash critical model/data artifacts.
- The staged GitHub Actions workflow is synthetic-only and has read-only repository permissions.
- Hosted runner allocation is currently unavailable for this private repository, so the workflow is manual-only until that account/repository constraint is resolved.
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

The model hash must match the currently trusted frozen-champion value before any model deserialization or private runtime launch.


## Historical release drift

`RELEASE_MANIFEST.json` and `SHA256SUMS` remain the immutable Step-21 package record. Later security patches are declared in `config/release_drift_allowlist.json`, which is an explicit reviewed trust root.

Run:

```bash
python scripts/verify_release_drift.py \
  --root . \
  --expected-exceptions-sha256 <independently-recorded-allowlist-sha256>
```

The verifier requires unchanged historical files to match their original SHA-256/size, intentional modified files and repository additions to match their reviewed Git blob identities, and rejects undeclared tracked files. It also refuses release approval unless the allowlist itself matches an independently supplied SHA-256. Record that hash outside the repository (for example in an offline release note, signed tag record, or other trusted channel); reading the hash from the same working tree is not an independent trust check.

## Safer model persistence

The currently active champion remains the hash-verified joblib artifact. `src/model_artifact.py` provides an optional migration to `skops.io`. A skops runtime requires both the model artifact SHA-256 and the separately reviewed trusted-types file SHA-256 to match before model loading.
