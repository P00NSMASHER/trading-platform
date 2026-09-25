# Control-Plane Step 4 - Signed Publicity Clearance

Step 4 adds the only allowed transition out of `PUBLICITY_PENDING`: a signed, externally trusted `PUBLICITY_CLEARED` decision.

## Clearance subject binding

A clearance binds all of the following before it can be signed:

- exact `information_id`;
- exact source ID;
- exact HOLDING content SHA-256;
- the current pre-clearance control-event head;
- an archived public-release evidence SHA-256;
- a non-empty public-release reference;
- an explicit timezone-qualified public-release timestamp;
- fixed signature namespace `mnpi-publicity-clearance`;
- `decision_scope = publicity_only`;
- `research_use_only = true`;
- `model_plane_eligible = false`.

A changed source object, changed evidence artifact, or advanced control-event chain invalidates the clearance subject.

## External signature trust

The repository does not need the publicity-review private key.

The `control_plane.publicity.sign_clearance(...)` API refuses a private signing key stored anywhere under the repository root and delegates signing to OpenSSH `ssh-keygen -Y sign` using the fixed publicity namespace.

Verification requires an OpenSSH allowed-signers file stored outside the repository. Its SHA-256 must match an independently supplied trust-root digest before `ssh-keygen` is invoked. Verification uses immutable temporary copies of both the trusted allowed-signers bytes and detached signature bytes, while the exact clearance bytes are supplied to `ssh-keygen` on stdin. This closes the file-substitution window between hashing and signature verification.

## Fail-closed transition

The registry rejects direct `PUBLICITY_PENDING -> PUBLICITY_CLEARED` events unless the event contains the verified signature metadata, trusted signer-file hash, public-release evidence hash, clearance hash, fixed namespace, signer identity, and the exact prior event head.

A successfully verified clearance is archived content-addressably under:

`<control-dir>/publicity_clearances/<clearance_sha256>/`

with the exact signed `clearance.json` and detached signature. Control-plane integrity checks require that archived claim and signature to remain present for any object in `PUBLICITY_CLEARED`.

Invalid signatures, stale clearances, wrong information identities, changed HOLDING bytes, changed release evidence, wrong namespaces, or signer trust-root mismatches leave the object in `PUBLICITY_PENDING`.

## Boundary preserved

`PUBLICITY_CLEARED` means only that the publicity decision passed this signed control boundary. Step 4 does not create parsed corpora, lineage admission, features, labels, model inputs, champion changes, G1-G11 closures, trading recommendations, orders, position sizing, or execution capability.

Recursive lineage and recovery remain Step 5.
