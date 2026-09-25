# Control-Plane Step 5 - Recursive Lineage and Recovery

Step 5 adds immutable recursive provenance for research-only control-plane derivatives and an atomic recovery path that refuses to restore bytes unless the complete ancestry verifies.

## Lineage registry

The control SQLite registry now contains two additional append-only/immutable structures:

- `lineage_artifact` — one deterministic derived-artifact identity bound to its content SHA-256, size, artifact kind, transformation ID/version, and exact lineage-manifest SHA-256;
- `lineage_parent` — ordered parent bindings for each artifact.

A parent is either:

1. an existing `information_object`, bound to the exact historical control-event hash and the source content SHA-256; or
2. an existing derived artifact, bound to its deterministic artifact ID and content SHA-256.

Lineage rows cannot be updated or deleted.

## Eligible roots

A structured information object is lineage-eligible only at an `ADMITTED_STRUCTURED` event.

An unstructured information object is lineage-eligible only at a `PUBLICITY_CLEARED` event. A `PUBLICITY_PENDING`, `REVIEW_REQUIRED`, or `QUARANTINED` object cannot seed a derived artifact.

For a `PUBLICITY_CLEARED` root, recursive verification also requires the content-addressed signed-clearance archive introduced in Step 4.

The parent is bound to the historical event hash that existed when the derivative was created. Later append-only events do not erase that provenance. The complete event chain must nevertheless remain valid, and currently held/quarantined roots fail closed.

## Derived artifact identity

Every artifact ID is deterministic over:

- exact derived content SHA-256;
- artifact kind;
- transformation ID;
- transformation version;
- ordered parent identities;
- bound parent event heads/content hashes.

The payload and a canonical lineage manifest are stored privately under:

`<control-dir>/lineage/artifacts/<artifact_id>/`

The registry stores the exact manifest SHA-256. Re-ingesting the identical derivation is idempotent; the same artifact identity cannot be rebound to different bytes, parents, or transformation metadata.

All Step 5 derivatives remain:

- `research_use_only = true`;
- `model_plane_eligible = false`.

## Recursive verification

Verification walks the complete artifact graph to its information roots and fails closed on:

- cycles;
- a missing artifact or parent;
- a tampered payload;
- a missing/tampered lineage manifest;
- registry/manifest disagreement;
- invalid information event chains;
- an ineligible bound information state;
- mismatched parent content hashes;
- missing HOLDING snapshots;
- missing signed-clearance archives for publicity-cleared roots.

## Recovery

`recover_artifact(...)` first verifies the full recursive ancestry. Only then does it copy the archived payload to a temporary destination, verify the recovered SHA-256, and atomically place it.

Existing destinations are never overwritten unless `overwrite=True` is explicitly supplied. A failed ancestry check leaves the destination untouched.

This is control-plane artifact recovery only. It does not restore, retrain, alter, promote, or execute the frozen model/champion and does not close G1-G11.

G12-G15 and release authority remain Step 6.
