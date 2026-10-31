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
