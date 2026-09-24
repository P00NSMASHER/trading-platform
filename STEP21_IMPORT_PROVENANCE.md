# Step 21 Import Provenance

Source upload: `MNPI_Prototype_Step21.zip`

Original uploaded package SHA-256:
`33ed148d480808474b6aab6c958aa476e6fe73be5a9eeb467e156ec88f3b4158`

GitHub source-import archive SHA-256:
`75ab615013af3b136cd5e74489f427cb95ea17339d7e610c1fd8d30ced592790`

Validation before import:
- staged import archive SHA-256: PASS
- package SHA256SUMS: 338 / 338 files verified
- independent clean extraction: 183 / 183 tests passed using `PYTHONPATH=src python -m pytest -q`
- obvious credential/private-key scan: no hits

Frozen champion SHA-256:
`0c8c16c9be734152c0018aa40e576fe4db9f4621359fafe521465890f9945616`

The historical `FROZEN_CHAMPION.md` file is intentionally retained.

The one-time GitHub Actions import runner failed before allocating a runner, so the already-staged, hash-verified payload was imported directly through GitHub's Git data API. Package contents were not changed during import.
