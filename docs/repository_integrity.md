# Repository integrity controls

## Current controls

- The repository is private.
- Runtime model bytes are checked against a trusted SHA-256 before `joblib.load`.
- Step-20/21 provenance gates hash critical model/data artifacts.
- CI is synthetic-only and has read-only repository permissions.
- CI receives no market-data credentials, broker credentials, or private runtime inputs.
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
