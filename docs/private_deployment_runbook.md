# Private deployment runbook

This prototype is for historical market-surveillance research only. A surveillance score is not a finding of insider trading, MNPI misuse, or any other violation.

## Security boundary

- Keep the runtime on a single-user workstation or private VPC.
- Bind the dashboard only to loopback (`127.0.0.1`, `::1`, or `localhost`).
- Do not expose the dashboard through a reverse proxy, tunnel, public load balancer, or port-forward.
- Do not connect the prototype to a broker, order-management system, execution API, notification-to-trade automation, or any system that can place trades.
- Do not put API keys, passwords, broker credentials, or data-vendor secrets in runtime TOML files. Use a separate local secret manager if future lawful market-data adapters require credentials.
- Keep raw licensed market data outside evidence exports. Evidence bundles should contain hashes/provenance rather than redistributing raw licensed inputs.

## 1. Create a private Python environment

Validated runtime versions are pinned in `requirements.lock` and test tooling in `requirements-dev.lock`.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.lock
python -m pip install -r requirements-dev.lock
```

The validated Step-10 environment used Python 3.13.5. The project requires Python 3.11+.

## 2. Create local runtime configuration

```bash
cp config/runtime.example.toml config/runtime.local.toml
chmod 600 config/runtime.local.toml
```

Edit only local paths/port as needed. Keep the policy block exactly fail-closed:

```toml
[policy]
research_use_only = true
allow_network_bind = false
allow_execution_integration = false
allow_trade_outputs = false
```

The runtime loader rejects any configuration that weakens those four controls or changes the dashboard to a non-loopback address.

## 3. Apply private filesystem permissions

```bash
python src/deployment_hardening.py harden-permissions \
  --config config/runtime.local.toml \
  --report private_runtime/audit/permissions.json
```

Expected POSIX modes:

- sensitive files: `0600`
- private runtime directories: `0700`

On filesystems where POSIX mode semantics differ, inspect the self-check output rather than assuming privacy.

## 4. Run tests before use

```bash
pytest -q
```

Do not continue if any test fails.

## 5. Run the fail-closed self-check

```bash
python src/deployment_hardening.py self-check \
  --config config/runtime.local.toml \
  --report private_runtime/audit/self_check.json
```

Require `"ok": true`. The self-check verifies:

- research-only runtime policy;
- loopback-only dashboard configuration;
- disabled execution integration and trade outputs;
- frozen model-bundle structure and hash;
- no prohibited trade-output keys in model metadata;
- training manifest anti-lookahead policy;
- SQLite integrity and foreign keys;
- evidence review-chain hashes;
- source-artifact hash formatting;
- model hash consistency inside case evidence;
- private filesystem permissions.

## 6. Back up the case database before reviews or upgrades

```bash
python src/deployment_hardening.py backup-db \
  --config config/runtime.local.toml \
  --report private_runtime/audit/backup_report.json
```

The command refuses to back up a database that fails integrity checks. It creates:

- a verified SQLite backup;
- a SHA-256-protected manifest;
- a logical fingerprint based on case/evidence counts, review-chain results, and model provenance.

Keep the backup directory private (`0700`) and backup files owner-only (`0600`).

## 7. Recovery drill

Run after initial setup and after material code/database changes:

```bash
python src/deployment_hardening.py recovery-drill \
  --config config/runtime.local.toml \
  --report private_runtime/audit/recovery_drill.json
```

The drill works only on temporary copies. It verifies a successful backup/restore, deliberately truncates a backup, confirms corruption is detected, and confirms the source database remains unchanged.

## 8. Restore procedure

Never restore directly over the active database first. Restore to a new path and verify it:

```bash
python src/deployment_hardening.py restore-db \
  --config config/runtime.local.toml \
  --backup private_runtime/backups/<backup>.sqlite \
  --manifest private_runtime/backups/<backup>.manifest.json \
  --destination private_runtime/restore_check/cases.sqlite
```

Run a self-check against a temporary config pointing at the restored database. Only replace the active database after the restored copy passes integrity checks and has the expected logical fingerprint.

## 9. Launch the private dashboard

```bash
python src/private_dashboard.py \
  --db data/processed/case_demo/cases.sqlite \
  --host 127.0.0.1 \
  --port 8765 \
  --open-browser
```

The dashboard itself refuses non-loopback binds, rejects hostile/nonlocal `Host` headers, uses a per-launch CSRF token for mutations, and does not serve raw licensed market files.

## 10. Normal shutdown / audit retention

Retain:

- `private_runtime/audit/self_check.json`
- latest `backup_report.json`
- latest `recovery_drill.json`
- evidence bundle hashes
- model/training manifests

Do not commit `private_runtime/`, `runtime.local.toml`, secrets, raw licensed data, or database backups to a public repository.

## Failure rules

Fail closed if any of the following occurs:

1. self-check `ok` is false;
2. model bundle hash changes unexpectedly;
3. database integrity or foreign-key check fails;
4. any review hash chain fails;
5. case evidence references a different model hash than the frozen model;
6. a runtime policy flag permits network bind, execution integration, or trade outputs;
7. dashboard host is not loopback;
8. a backup or backup manifest hash fails;
9. a restore logical fingerprint differs from the backup manifest;
10. test suite fails.

Do not “repair around” a failed integrity check. Preserve the affected files, restore from the last verified backup to a new path, and compare hashes/manifests before resuming research.

## Scope limitation

The included model/demo cases are synthetic plumbing fixtures. Perfect demo metrics are not evidence of real-world detection performance. Real historical validation requires lawfully obtained point-in-time market data and separately documented adjudicated case labels. The prototype remains a research/surveillance system and is not an execution or investment-decision system.
