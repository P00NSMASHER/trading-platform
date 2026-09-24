# Private Deployment Runbook — Step 10

## Scope and boundary

This is a local, historical market-surveillance research prototype. It is not a trading system and must not be connected to brokerage execution, order routing, automated position sizing, or trade-direction outputs.

The safe runtime is designed to fail closed. Before the dashboard starts it:

1. applies owner-only permissions to the active config, case database, model bundle, and training manifest;
2. verifies the frozen model bundle and research-only policy;
3. checks the SQLite database with `PRAGMA integrity_check` and `PRAGMA foreign_key_check`;
4. verifies every case review hash chain;
5. verifies model/source hash consistency recorded in the case database;
6. refuses non-loopback network binding;
7. refuses configurations that enable execution integration or trade outputs.

## 1. Create an isolated Python environment

Validated Step-10 environment:

- Python 3.13.5
- joblib 1.5.3
- numpy 2.3.5
- scipy 1.17.0
- scikit-learn 1.8.0
- threadpoolctl 3.6.0

Install runtime dependencies from the exact lock:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.lock
```

For tests:

```bash
python -m pip install -r requirements-dev.lock
pytest -q
```

Do not treat a different dependency graph as validated until the full test suite and recovery drill pass again.

## 2. Create private runtime configuration

Copy the public template rather than editing it in place:

```bash
cp config/runtime.example.toml config/runtime.local.toml
chmod 600 config/runtime.local.toml
```

`runtime.local.toml` is ignored by `.gitignore`.

Do not put passwords, broker credentials, data-vendor secrets, API keys, or other secrets in this file. Keep secrets outside this prototype and outside shell history. The current prototype has no live provider or broker integration and does not need secrets.

Required safety policy values:

```toml
[policy]
research_use_only = true
allow_network_bind = false
allow_execution_integration = false
allow_trade_outputs = false
```

Dashboard host must be one of `127.0.0.1`, `::1`, or `localhost`.

## 3. Apply private filesystem permissions

```bash
python src/deployment_hardening.py harden-permissions \
  --config config/runtime.local.toml \
  --report private_runtime/audit/permissions.json
```

Expected effective modes on POSIX systems:

- active config: `0600`
- case database: `0600`
- model bundle: `0600`
- training manifest: `0600`
- backup directory: `0700`
- export directory: `0700`
- audit directory: `0700`

## 4. Run fail-closed preflight

```bash
python src/deployment_hardening.py self-check \
  --config config/runtime.local.toml \
  --report private_runtime/audit/self_check.json
```

Do not launch if `ok` is not `true`.

The preflight verifies:

- policy boundary;
- exact model-bundle structure and research-only marker;
- training-manifest anti-lookahead marker;
- SQLite integrity and foreign keys;
- all review hash chains;
- stored model-hash consistency;
- owner-only filesystem permissions.

## 5. Create a verified database backup

Use SQLite's online backup API through the hardening tool; do not copy an active SQLite file by hand.

```bash
python src/deployment_hardening.py backup-db \
  --config config/runtime.local.toml \
  --report private_runtime/audit/latest_backup.json
```

Each backup receives:

- a SHA-256 hash;
- a logical database fingerprint;
- table row counts;
- review-chain validation status;
- a separately hashed manifest.

The tool refuses to back up a database that already fails integrity checks.

Recommended operating practice:

- make a verified backup before schema/code changes;
- keep at least two prior verified backups;
- store additional encrypted/offline copies according to your own data-retention policy;
- never assume a backup is valid merely because the file exists.

## 6. Test disaster recovery

```bash
python src/deployment_hardening.py recovery-drill \
  --config config/runtime.local.toml \
  --report private_runtime/audit/recovery_drill.json
```

The drill works only on temporary copies. It:

1. copies the source database to an isolated temporary directory;
2. performs a verified SQLite backup;
3. restores it to a new file;
4. verifies logical fingerprints and review chains;
5. deliberately truncates a separate backup copy;
6. requires the verifier to detect that corruption;
7. confirms the original case database was not modified.

A deployment should not be considered recoverable unless this drill reports `ok: true`.

## 7. Restore from a verified backup

Restores are explicit and fail closed.

```bash
python src/deployment_hardening.py restore-db \
  --config config/runtime.local.toml \
  --backup /path/to/cases_YYYYMMDDTHHMMSSZ.sqlite \
  --manifest /path/to/cases_YYYYMMDDTHHMMSSZ.manifest.json \
  --destination /path/to/restored_cases.sqlite \
  --report private_runtime/audit/restore.json
```

The restore process verifies the manifest hash, backup SHA-256, SQLite integrity, foreign keys, review chains, and logical fingerprint before atomically moving the restored file into place.

An existing destination is never overwritten unless `--overwrite` is supplied explicitly.

## 8. Start the safe local runtime

Use the fail-closed wrapper rather than launching the dashboard module directly:

```bash
python src/private_runtime.py \
  --config config/runtime.local.toml \
  --open-browser
```

The wrapper reapplies private permissions, writes `startup_self_check.json`, and starts the dashboard only if the audit passes.

The dashboard remains loopback-only and keeps the Step-9 protections:

- hostile Host headers rejected;
- per-launch CSRF token for review writes;
- restrictive CSP;
- `X-Frame-Options: DENY`;
- no-cache responses;
- no raw licensed market-data serving;
- no trade/order outputs.

## 9. Normal shutdown

Use `Ctrl-C` in the terminal running `private_runtime.py`.

Before changing the database or model:

1. stop the dashboard;
2. run a verified database backup;
3. preserve the current model bundle and training manifest together;
4. run the full test suite after the change;
5. rerun the self-check and recovery drill.

## 10. Failure response

### Self-check fails

Do not bypass it. Inspect the failing section in the JSON audit.

### Review-chain failure

Treat the case database as integrity-compromised for investigative purposes. Do not rewrite history to make the chain pass. Restore a previously verified backup and separately preserve the suspect database for forensic comparison.

### SQLite integrity or foreign-key failure

Stop the dashboard. Preserve the damaged file, restore from a verified backup, then compare source artifacts and review histories before resuming.

### Model hash mismatch

Do not score or review cases with the mismatched model. Restore the frozen model bundle associated with the case database or create a new, separately versioned research environment.

### Backup manifest/hash mismatch

Do not restore it. Use another verified backup.

### Dependency/version drift

Recreate the validated environment from `requirements.lock`, rerun all tests, self-check, and recovery drill.

## 11. Data-retention and export boundary

Evidence exports intentionally include hashes and reproducible case snapshots, not raw licensed/proprietary market files. Retain raw source data according to its lawful entitlement and privacy requirements outside the evidence ZIP.

A case score is anomaly prioritization only. It is not a determination that a person or firm possessed MNPI or violated law.
