# External signed release attestation

The release-drift allowlist now has an independently recorded SHA-256 trust root. A stronger release can additionally be signed with an SSH signing key held outside this repository.

The repository never needs the private signing key.

## 1. Record the drift trust-root hash externally

Compute the SHA-256 of `config/release_drift_allowlist.json` after review and store it outside Git.

## 2. Build the attestation

```bash
python scripts/release_attestation.py build \
  --root . \
  --expected-drift-trust-root-sha256 <external-drift-hash> \
  --expected-champion-sha256 0c8c16c9be734152c0018aa40e576fe4db9f4621359fafe521465890f9945616 \
  --output private_runtime/release/release_attestation.json
```

Building fails unless the tracked worktree is clean, release-drift verification passes, and the frozen champion hash matches.

The attestation binds the Git commit, SHA-256 digest of every tracked file, Step-21 release manifest, SHA256SUMS, current drift allowlist, and frozen champion.

## 3. Sign outside the repository trust boundary

Use an existing SSH signing key held outside this repository:

```bash
python scripts/release_attestation.py sign \
  --attestation private_runtime/release/release_attestation.json \
  --private-key <path-to-external-ssh-private-key>
```

This calls `ssh-keygen -Y sign` using namespace `mnpi-release`. Do not commit the key, attestation, or detached signature.

## 4. Verify against an externally trusted signer

Create an OpenSSH allowed-signers file outside Git, for example:

```text
release-owner ssh-ed25519 AAAA...
```

Record that file's SHA-256 separately, then verify:

```bash
python scripts/release_attestation.py verify \
  --root . \
  --attestation private_runtime/release/release_attestation.json \
  --signature private_runtime/release/release_attestation.json.sig \
  --allowed-signers <external-allowed-signers-file> \
  --expected-allowed-signers-sha256 <external-allowed-signers-sha256> \
  --identity release-owner
```

Verification checks the allowed-signers hash before invoking `ssh-keygen`, verifies the detached signature, and then proves that the current clean checkout, champion, release manifest, SHA256SUMS, and drift policy exactly match the signed attestation.

This is release-integrity infrastructure only. It does not authorize model promotion, trading outputs, execution, or broker connectivity.
