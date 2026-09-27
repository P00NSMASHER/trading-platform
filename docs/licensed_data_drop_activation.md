# Licensed private-drop activation

This layer closes the gap between local file arrival and the provider-agnostic real-data replay.

It does **not** download vendor files, read credentials, infer a license, or treat filenames as authorization. A file becomes executable only when its exact SHA-256 is present in a local entitlement manifest whose entry explicitly says `authorized: true` and includes a nonblank license reference.

## Private layout

Recommended local-only structure:

```
data/private/licensed/
  drop/
  intake/
  entitlement_manifest.json
  historical_market_sources.real.json
  real_data_replay.generated.json
```

Do not commit populated private files.

## Step 1 — drop the vendor files

Copy the lawfully obtained TAQ/options/decoded-ITCH files into:

`data/private/licensed/drop/`

Original vendor filenames are preserved.

## Step 2 — bind authorization to exact hashes

Create a local entitlement manifest from:

`config/licensed_entitlement_manifest.example.json`

Each approved file entry must contain:

- exact SHA-256
- `authorized: true`
- a nonblank license/entitlement reference
- source family
- record kind
- trade date

The processor refuses to activate an entry when the scanned source family, record kind, or trade date disagrees with the entitlement entry.

## Step 3 — activate

```bash
PYTHONPATH=src python src/licensed_data_drop_processor.py activate \
  --drop-dir data/private/licensed/drop \
  --work-dir data/private/licensed/intake \
  --entitlement-manifest data/private/licensed/entitlement_manifest.json \
  --market-contract-out data/private/licensed/historical_market_sources.real.json \
  --replay-config-template config/real_data_replay.example.json \
  --replay-config-out data/private/licensed/real_data_replay.generated.json
```

The generated market contract is executable only for files whose exact hashes were approved.

## Step 4 — activate and immediately replay

Add:

`--run-replay`

The processor then calls the provider-agnostic replay with the generated real market contract.

## Optional watch mode

For a bounded polling session:

```bash
PYTHONPATH=src python src/licensed_data_drop_processor.py watch \
  --drop-dir data/private/licensed/drop \
  --work-dir data/private/licensed/intake \
  --entitlement-manifest data/private/licensed/entitlement_manifest.json \
  --market-contract-out data/private/licensed/historical_market_sources.real.json \
  --replay-config-template config/real_data_replay.example.json \
  --replay-config-out data/private/licensed/real_data_replay.generated.json \
  --run-replay \
  --interval-seconds 60 \
  --max-iterations 60
```

The watcher reruns activation only when the drop-folder fingerprint or entitlement-manifest hash changes.

## Hard boundaries

- No exact SHA match → no activation.
- Blank license reference → no activation.
- `authorized: false` → no activation.
- Schema/date/family mismatch → no activation.
- Raw ITCH binary → inventory only; it must first pass through an authorized decoder.
- No credentials are read or stored.
- No synthetic file can become a real source through this layer.
- Replay/release gates remain fail-closed.
