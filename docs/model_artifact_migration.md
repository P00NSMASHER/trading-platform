# Safer model artifact migration

The active frozen champion remains the existing SHA-256-verified `joblib` bundle until a replacement artifact is explicitly reviewed and approved.

Python pickle/joblib loading can execute code during deserialization. The runtime already checks a trusted SHA-256 before loading the frozen joblib bundle. This migration layer adds an optional `skops.io` path so future runtime deployments can avoid pickle-based persistence.

## Install the optional serializer

```bash
python -m pip install -r requirements.lock
python -m pip install -r requirements-skops.lock
```

## Convert only the trusted frozen joblib bundle

```bash
PYTHONPATH=src python src/model_artifact.py export-skops \
  --source-joblib data/processed/model_demo/model_bundle.joblib \
  --expected-joblib-sha256 0c8c16c9be734152c0018aa40e576fe4db9f4621359fafe521465890f9945616 \
  --output-skops private_runtime/model/model_bundle.skops \
  --inspection-report private_runtime/model/skops_inspection.json
```

The export report lists types that `skops.io` does not trust by default. **Do not automatically copy that list into the trusted-types file.** Review each type against the trained pipeline and the exact locked environment.

After review, copy `config/skops_trusted_types.example.json` to a private local file and list only the reviewed types. Configure the runtime with `model_format = "skops"`, the converted artifact path/hash, and the reviewed trusted-types file.

At load time the runtime:

1. verifies the artifact SHA-256 before parsing/loading;
2. asks `skops.io` which types are not trusted by default;
3. refuses any type not present in the separately reviewed allowlist;
4. only then loads the model.

This is a migration path, not an automatic model promotion or model change. Champion/challenger and research-only controls remain unchanged.
