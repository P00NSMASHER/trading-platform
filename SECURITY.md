# Security policy

This repository is a private, research-only market-surveillance prototype.

## Sensitive material

Do not commit:

- API keys, passwords, access/refresh tokens, private keys, or broker credentials;
- raw licensed/vendor market datasets;
- private runtime staging directories, backups, or local exports;
- live stolen/private corporate information, leaked credentials, or accidental private disclosures.

Use `private_runtime/` or another ignored local directory for authorized private inputs.

## Validation before merging

Run:

```bash
python scripts/secret_scan.py --root .
python scripts/verify_release_drift.py \
  --root . \
  --expected-exceptions-sha256 <independently-recorded-allowlist-sha256>
PYTHONPATH=src python -m pytest -q
```

The runtime must continue to verify the frozen model SHA-256 before deserialization, bind the dashboard to loopback only, prohibit broker/execution integration, and keep trading outputs disabled.

## Repository integrity

Prefer signed commits/tags where available. Treat `FROZEN_CHAMPION.md`, `RELEASE_MANIFEST.json`, and `SHA256SUMS` as integrity evidence, not as a substitute for an independently trusted release hash.


## Dashboard access

The local dashboard uses a new in-memory authentication token on every launch in addition to loopback binding and CSRF protection. Do not copy authenticated launch URLs into logs, tickets, or shared documents.

## Model persistence

The frozen joblib champion remains allowed only after its trusted SHA-256 is verified before deserialization. Future migrations to `skops.io` must additionally use a separately reviewed trusted-types file whose SHA-256 is configured and verified before loading.


## Signed release evidence

For important releases, build and externally sign `private_runtime/release/release_attestation.json` using `scripts/release_attestation.py`. Keep signing keys and allowed-signers trust files outside the repository. Verification must pin the SHA-256 of the allowed-signers file before accepting the SSH signature.
