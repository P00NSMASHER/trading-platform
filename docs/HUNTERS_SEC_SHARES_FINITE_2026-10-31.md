# Source Hunter A | SEC shares integrity | 2026-10-31

## Ownership and source-grounded defect

Canonical repo: `P00NSMASHER/trading-platform` on protected `main`, inspected 2026-10-31. Existing market-data source repair #516 and research experiments #517/#518 remain separately owned; this change touches none of their files and makes no Tradier connection, order, live fill or profit assertion. Portfolio Brain's 12-hour observation baseline is untouched.

In `src/sec_companyfacts_normalizer.py`, the original gate `float(val) <= 0` accidentally accepted positive-looking non-finite values: `float('NaN') <= 0` and `float('Infinity') <= 0` both evaluate false. JSON boolean `true` also evaluated as numeric 1. Such values could become `shares_outstanding` records in offline downstream CSV and taint point-in-time research.

Remedy: `math.isfinite(float(val))` and reject boolean count values explicitly; retain all existing source dates, availability time, deduplication, filing metadata, mapping and output format. **No prices, signals, trades or actual broker observations were created.**

## Two inspected, compatible external candidates

1. [pydantic/pydantic](https://github.com/pydantic/pydantic) at `69e9ca4658a6471cadae5216b44ebfb4fde040f3` (2026-10-31), [MIT](https://github.com/pydantic/pydantic/blob/main/LICENSE), license blob `488c6260c10f2e88fa1fae58a63fccec8d600cd1`. Mature rich validation but unnecessary dependency and migration overhead for this single primitive.
2. [python-jsonschema/jsonschema](https://github.com/python-jsonschema/jsonschema) at `c497561ea0a95f5aac09cd63d15eb1420eb7bbec` (2026-10-07), [MIT](https://github.com/python-jsonschema/jsonschema/blob/main/COPYING), license blob `af9cfbdb134f42e5205ecbad597421d778826481`. JSON type/schema validation could enforce number but is excessive for existing typed, downstream-normalized records without a schema migration.

Selected independently authored Python standard-library `math.isfinite` guard, no imported code, extra package, change to lockfiles, third-party NOTICE, network access or telemetry.

## Reproduction and acceptance

Baseline Python: `float('NaN') <= 0` returns `False`, and `float('Infinity') <= 0` returns `False`. New `tests/test_sec_companyfacts_finite_shares.py` constructs a local synthetic SEC-shaped JSON file with **9 rejected adversarial values** and **2 legitimate shares observations**, asserts counters, source dates, canonical symbol, finite numeric output and conservative after-filing availability. Run `PYTHONPATH=src python -m pytest -q tests/test_sec_companyfacts_finite_shares.py tests/test_sec_companyfacts_normalizer.py` plus existing exact-head CI/security/source gates.

No genuine SEC feed was downloaded or independently rescored in this patch; the fixture is explicitly synthetic. Reject policy is intentionally narrow: this does not solve all companyfacts metadata identity or filing-lag uncertainties.

## Cost/rollback and next

New dependencies: **0**. Estimated **0.5–2 engineer hours avoided** versus adopting a full schema validation library, low confidence, based on likely integration/review/testing rather than observed labor time.

Rollback: revert this isolated PR; no schema, data migration or production changes. Before any merge, reconcile with owner PRs and require current exact-head CI and release attestation. Next: assess any non-finite ingress in neighboring public-source adapters under separate non-overlapping PRs, preserving immutable source evidence. Never treat synthetic QA as profit validation.

## Follow-on share-count exactness and malformed observations (2026-10-31)

**Reproduced on original guard:** `float('1.00000000000000001')` rounds to `1.0`, passing `float(val) > 0 and isfinite(float(val))`; a positive noninteger `1.5` also passed the guard, despite an SEC outstanding-share count being a discrete integer. A null array member raised `AttributeError` before the guarded parsing branch and could abort all other records in that file.

**Implemented:** require `Decimal(str(val))` to be finite, positive and mathematically integral after preserving the original finite float preflight. Explicitly quarantine malformed non-dictionary observation entries. Standard-library only, no dependency, price source, source date, market signal, broker connection, order, schema or customer data changed. Original source `val` textual representation remains unmodified in output.

**Adversarial test:** existing source-shape fixture now includes positive fractional JSON numbers and numeric strings (including a near-integer precision trap), null, arrays and strings inside `units.shares`. It must retain exactly two legitimate observations and skip every malformed row; provenance and point-in-time availability assertions remain. Inputs are synthetic, not proof of SEC live-feed incidence.

**External candidate recheck:** [python-attrs/attrs](https://github.com/python-attrs/attrs), MIT LICENSE blob `2bd6453d255e19b973f19b128596a8b6dd65b2c3`, upstream main `c8bb9bfaa2843e7844b5bb13bed4370b51feec4f` (2026-10-24), zero core runtime dependencies, and [pydantic/pydantic](https://github.com/pydantic/pydantic), MIT LICENSE blob `488c6260c10f2e88fa1fae58a63fccec8d600cd1`, upstream `824cf7bfbfdc5e921d62a82dedda7e5b0f9789dc` (2026-10-31) are suitable for larger typed ingestion; both are disproportionate for this primitive. Third-party advisory scans were not authoritative and no third-party code/imports or NOTICE changes were made.

**Verification / gate:** run exact-head `PYTHONPATH=src python -m pytest -q tests/test_sec_companyfacts_finite_shares.py tests/test_sec_companyfacts_normalizer.py`, mandatory manifest hashes, security and hosted CI. Existing independent release trust-root remains unverified; **do not merge** on self-signed test results. Estimated additional 0.5–1.0 engineer hours avoided (low confidence planning estimate for avoiding rework and a new validation package, not stopwatch measurement). Rollback through this PR; recheck source-byte manifest on any revert.

## Third follow-on: malformed Companyfacts frames and future-filed observations (2026-10-31)

**Additional reproduced source-boundary defects:** a top-level JSON list, `facts: null`, `dei: []`, or `units.shares: null` raised before the existing per-observation guard, aborting a batch despite unrelated valid Companyfacts files. A fact dated after its `filed` date was accepted, making future measurement available to a historical source join. Python `date.fromisoformat` also accepts compact `YYYYMMDD`, even though lexicographic mapping and CSV consumers require canonical `YYYY-MM-DD` strings.

**Minimal correction:** treat malformed schema containers as one quarantined record and continue independently sourced files, while preserving absent concepts as legitimate empty input. Reject a share row unless its fact and filed dates round-trip to exact ISO civil dates, and its filing date is not before the measured fact date. Preserve the existing conservative 23:59:59 New York release timestamp for legitimate rows, raw count text, ticker mapping, CSV format, and amendments. This is a source plausibility/point-in-time control, **not** evidence of a trading advantage.

**Adversarial tests added:** 4 malformed file frames, one future-dated fact, one compact-date fact, alongside the existing 12 malformed share values and 3 malformed row shapes; 2 independently testable valid rows must survive. All data is synthetic, not observed SEC incidence. Run `PYTHONPATH=src python -m pytest -q tests/test_sec_companyfacts_finite_shares.py tests/test_sec_companyfacts_normalizer.py`, full exact-head PR CI, SHA-256 drift, control-plane and secret scans. A passing self-reported audit still does **not** establish the independently issued release trust root.

**External-source decision:** reuses no imported code: previously inspected MIT `attrs` and MIT `Pydantic`, plus MIT `python-jsonschema`, remain disproportionate for two simple schema and chronology invariants. Keep the same pinned upstream/license comparisons and do not claim unverified advisory clearance. No new dependencies, orders, live quotes or production action. Estimated additional 0.5–1.5 engineering hours avoided, **low confidence** based on a standalone parser/test integration estimate, not actual tracked labor. Roll back the follow-on commits with their source/test evidence SHA pins; never bypass release governance.
