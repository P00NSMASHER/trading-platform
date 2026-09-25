# Control-Plane Step 3 - JUNAS Unstructured Lane

Step 3 adds a fail-closed intake lane for unstructured documents without connecting those documents to features, models, the frozen champion, evaluation gates, or trading outputs.

## Implemented boundary

Every JUNAS document is:

1. copied into the existing content-addressed private HOLDING store before policy evaluation;
2. registered as an immutable domain = "unstructured" information object;
3. recorded through the existing append-only hash-chained control-event ledger;
4. allowed to leave HOLDING only as PUBLICITY_PENDING, REVIEW_REQUIRED, or QUARANTINED.

The registry enforces that transition rule, so an unstructured object cannot move directly from HOLDING to ADMITTED_STRUCTURED.

## Policy behavior

- prohibited classifications are copied into hash-verified quarantine and become QUARANTINED;
- unsupported or insufficiently evidenced classifications become REVIEW_REQUIRED;
- supported publicity candidates become PUBLICITY_PENDING;
- a declaration that material is public is not treated as clearance.

PUBLICITY_PENDING, REVIEW_REQUIRED, and QUARANTINED are terminal for unstructured objects in Step 3. A later control-plane step must explicitly introduce and verify any onward transition.

## Model-plane isolation

The JUNAS lane creates no parsed corpus, embeddings, features, labels, model inputs, champion changes, gate closures, recommendations, orders, or execution artifacts.

Every JUNAS receipt explicitly records:

- publicity_clearance_present = false
- model_plane_eligible = false
- downstream_export_created = false
- research_use_only = true

The lane stores source-path fingerprints rather than raw external source paths in the control registry.

## Interface

src/control_plane/junas.py supports a schema-version 1 JSON manifest with a non-empty documents list and can be invoked as:

    python -m control_plane.junas --manifest <manifest.json> --control-dir <private-control-dir>

Each document entry requires source_id, path, and data_classification. Optional policy evidence includes authorized, license_reference, and source_reference.

Step 3 intentionally does not implement publicity verification or signed clearance. Those remain Step 4.
