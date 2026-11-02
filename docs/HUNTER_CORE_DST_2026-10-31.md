# Hunter A: Historical market-data DST integrity | 2026-10-31

## Canonical owner / non-conflict
- Repository: `P00NSMASHER/trading-platform`, isolated from the active `Tradier Options Research` option quote-depth / prospective selection PRs #509-#512, the G1/G2 vendor evidence lanes, and Portfolio Brain's owner-controlled observation baseline.
- This patch only changes **offline, historical, CSV-based, research-only** market data normalization. No Tradier API calls, credentials, orders, live trading, frozen champion, external data purchases or product deployments.

## Reproduced risk and deterministic repair
- Pre-fix `_parse_timestamp` attached `ZoneInfo(input_tz)` to a naive wall time with `replace(tzinfo=...)` and immediately converted it to UTC. Python `zoneinfo` does not reject DST gap/fold input automatically; different UTC instants could result from the same naive timestamp.
- North American examples: 2024-03-10 02:30 never existed in America/New_York, while 2024-11-03 01:30 occurred twice. Silently accepting either is unsuitable as point-in-time market source evidence.
- New algorithm tests both `fold=0` and `fold=1` possible UTC instants and round-trips each to the original naive wall time. Exactly **one unique UTC instant** is required; zero fails as nonexistent, two fail as ambiguous. The input row and timezone are retained in errors.
- Explicit-offset ISO-8601 timestamps still directly normalize to UTC; ordinary naive timestamps remain supported. No new dependency, lockfile change, third-party code copy, exchange timestamp invention, or source evidence promotion.
- Added parametrized trade/quote, spring-gap, autumn-fold, explicit-offset, ordinary-time and invalid-unused-zone regression cases. CI must independently run the full repository tests before any protected merge.

## Public GitHub candidates: license and implementation decision
1. [dateutil/dateutil](https://github.com/dateutil/dateutil) at commit `71d92da6f0318101653039ab3f051aef5d7e0438` (2026-10-25), dual **BSD-3-Clause / Apache-2.0** licensing in [LICENSE](https://github.com/dateutil/dateutil/blob/master/LICENSE). Supports timezone ambiguity/gap helpers; would add a dependency for one source-local ingest rule.
2. [python-pendulum/pendulum](https://github.com/python-pendulum/pendulum) at commit `e06dacedc4cdea90fa1286b3965d180ab94cf251` (2026-10-12), **MIT** licensed in [LICENSE](https://github.com/python-pendulum/pendulum/blob/master/LICENSE). Useful for broader date/time APIs; unnecessary for this narrow source integrity gate.
3. [Python standard datetime/zoneinfo documentation](https://docs.python.org/3/library/zoneinfo.html) explains `fold`, gaps and chronology. Reused documented standard-language functionality only.

Decision: independently written standard-library implementation, not imported library code. New external runtime/transitive licenses, security advisories and NOTICE duties are therefore **none**. No claim that library review itself saved a measurable amount of engineering labor.

## Evidence, policy, and release boundary
- Bounded isolated Python 3.13 preflight executed six DST cases successfully before GitHub patch. That preflight does not substitute for repository CI on Python 3.11 or independent audit.
- Full regression / secret scan / release-drift checks and exact-head protected GitHub CI must pass. Do not count test functions as genuine successful CI until the hosted run completes.
- The frozen release baseline remains immutable. Any changes to `src/market_data_adapter.py`, `tests/test_market_data_adapter.py`, `docs/market_data_schema.md`, and this new note must be declared with their exact post-commit SHA-256 in the source-reviewed `config/release_drift_allowlist.json`.
- **Important: a new allowlist hash is not a trusted external root.** No source release/attestation can be claimed authentic until an independently approved trust-root update and real CI/review are completed through existing governance. Never use a candidate-generated digest as independent acceptance authority.
- Rollback: revert this scoped branch/PR before promotion; there is no schema or historical-data migration.

## Engineering-time impact and follow-up
- Prevented consequence: DST gap/fold timestamps silently contaminating chronological event attribution; exact downstream avoided incidents and saved hours are **unknown / not measured**. Bounded estimate, if a later incident were diagnosed manually, 1-4 engineering hours avoided is hypothetical, not a realized savings report.
- Next owner action only if the code is accepted: review the exact SHA-256 allowlist changes and independently approve the protected release trust anchor; do not self-approve it in a task run.
- Continue trading research as paper-only. Coordinate on future market-source defects with existing repository owners before further patches.

## Exact source-size normalization extension (same isolated ingestion PR)
- Reproduced binary float coercion: source `0.99999999999999999` and `1.0000000000000001` both became integer 1; `9007199254740993` became 9007199254740992. This falsifies source provenance/volume before any market analysis.
- New standard-library `decimal.Decimal` parsing requires a finite, exactly integral value, retains common vendor `100.0`/`1e2` forms, and rejects sizes outside signed 64-bit magnitude or source strings longer than 128 characters. All four trade/quote kinds have positive and negative checks.
- Reviewed [pydantic/pydantic](https://github.com/pydantic/pydantic/tree/69e9ca4658a6471cadae5216b44ebfb4fde040f3) (MIT, active 2026-10-31) and [marshmallow-code/marshmallow](https://github.com/marshmallow-code/marshmallow/tree/b762ea2d59ca52fe5df76b90de14bed7e5ec5607) (MIT, active 2026-10-19). Both support schema conversion but would add unneeded dependencies; no third-party code copied or installed.
- Prior validation: Python 3 decimal parser checked adversarial fractional, >2^53 exact, 64-bit-boundary, NaN, infinity and exponential strings; this is not hosted CI. Caveat: floating price calculations elsewhere in this legacy adapter are outside this change, and no live market execution/capacity proof follows from these integrity tests.
