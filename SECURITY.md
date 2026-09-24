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
PYTHONPATH=src python -m pytest -q
```

The runtime must continue to verify the frozen model SHA-256 before deserialization, bind the dashboard to loopback only, prohibit broker/execution integration, and keep trading outputs disabled.

## Repository integrity

Prefer signed commits/tags where available. Treat `FROZEN_CHAMPION.md`, `RELEASE_MANIFEST.json`, and `SHA256SUMS` as integrity evidence, not as a substitute for an independently trusted release hash.
