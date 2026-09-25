# Control-Plane Step 2 - HOLDING and Structured Source Registry

This patch introduces the first runtime control-plane boundary around Step 21.

Implemented properties:

- every selected structured source is copied into a content-addressed private HOLDING snapshot before downstream validation;
- the original external path is represented only by a SHA-256 path fingerprint in control metadata;
- each exact source object receives a deterministic information_id and immutable receipt timestamp;
- control registry objects/events/locations are append-only or immutable in SQLite;
- prohibited source classifications are quarantined and cannot modify active contracts or close G1-G11 gates;
- unknown classifications stop at REVIEW_REQUIRED;
- admitted structured inputs are revalidated and staged only from the HOLDING snapshot;
- Step-21 receipts link information_id, control state, source-policy decision, HOLDING SHA-256, and control event head;
- a TOCTOU regression mutates the external source after HOLDING and verifies the pipeline still consumes the captured bytes;
- the frozen champion and existing G1-G11 semantics remain regression constraints.

This step does not add unstructured information review, publicity clearance, model inputs, broker connectivity, order execution, or trading recommendations.
