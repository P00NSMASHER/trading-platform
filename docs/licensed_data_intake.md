# Licensed-data intake

`src/licensed_data_intake.py` inventories files that have already been lawfully delivered to a local/private folder.

It does **not**:
- download data,
- read browser passwords or cookies,
- assert that a license exists,
- mark sources authorized,
- parse raw Nasdaq ITCH binary directly,
- or unlock the real-data replay by itself.

## Recommended private folder

Use any ignored path such as:

```
data/private/licensed-drop/
```

The repository already ignores `data/private/`, `data/licensed/`, `data/vendor/`, `data/incoming/`, and `data/staging/`.

## Scan

```bash
PYTHONPATH=src python src/licensed_data_intake.py \
  --input-dir data/private/licensed-drop \
  --output-dir data/private/licensed-intake \
  --license-reference "internal entitlement reference"
```

Outputs:

- `intake_files.csv` — every file, size, SHA-256, detected date, candidate record kind, and status.
- `market_contract.pending.json` — **non-executable** candidate source contract.
- `intake_manifest.json` — counts and intake policy.

## Status meanings

- `PENDING_AUTHORIZATION_AND_REVIEW`: header appears complete for one canonical market-data record kind, but authorization remains false.
- `PENDING_SCHEMA_MAPPING`: likely supported data, but one or more canonical fields still need explicit mapping.
- `REQUIRES_AUTHORIZED_DECODER`: raw Nasdaq ITCH-like binary; must be decoded separately under the entitlement.
- `UNCLASSIFIED`: the scanner cannot safely identify the file.

## Promotion to a real contract

A pending source may be copied into a real private market contract only after:

1. the file is known to be lawfully obtained,
2. the source family and record kind are reviewed,
3. the detected date is verified,
4. the delimiter/encoding and column map are confirmed,
5. `authorized` is explicitly changed to `true`,
6. a nonblank license/entitlement reference is attached.

Then run:

```bash
PYTHONPATH=src python src/real_data_replay.py --config config/real_data_replay.example.json
```

The replay layer will independently re-validate content coverage. Intake classification alone can never satisfy G2.
