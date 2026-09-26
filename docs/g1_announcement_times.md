# G1 — Exact public announcement times

G1 is intentionally fail-closed. It becomes ready only when every historical event has a timezone-aware exact public earnings-announcement timestamp from an authoritative/authorized source.

The original *Price Revelation from Insider Trading: Evidence from Hacked Earnings News* replication repository documents that the study used I/B/E/S announcement dates and times. Its companion processing code constructs the timestamp from `ANNDATS_ACT + ANNTIMS_ACT`. The public replication package does **not** publish those proprietary values.

Do not close G1 with:

- an earnings date with an assumed clock time;
- Yahoo/other calendar scheduled times that are not verified as first-public-release times;
- SEC EDGAR acceptance timestamps by themselves;
- later news articles;
- inferred market-reaction times.

Those remain candidates/proxies, not exact public-release evidence.

## Authorized I/B/E/S adapter

`src/g1_ibes_timestamp_adapter.py` converts an authorized I/B/E/S detail-history extract into the narrow G1 schema without copying analyst estimates, actual EPS values, or other raw licensed rows into the normalized output.

Required vendor fields:

- `TICKER` or `OFTIC`
- `ANNDATS_ACT`
- `ANNTIMS_ACT`

Example:

```bash
PYTHONPATH=src python src/g1_ibes_timestamp_adapter.py \
  --events data/processed/historical_events.csv \
  --ibes-detail /secure/path/IBES_Detail_History_1970_2019.csv.gz \
  --output private_runtime/g1/announcement_timestamps.csv \
  --report private_runtime/g1/g1_report.json \
  --entitlement-reference INTERNAL-WRDS-IBES-ENTITLEMENT \
  --require-complete
```

The adapter:

1. treats the historical first-trade timestamp as New York time when the source value is naive;
2. matches the first unique I/B/E/S actual-announcement timestamp strictly after that trade and within seven calendar days by default;
3. collapses duplicate detail-history rows only when they agree on the exact timestamp;
4. fails closed on missing or conflicting times;
5. writes `event_id` into every normalized record, avoiding the old same-calendar-date fallback assumption;
6. records the source-file SHA-256 and entitlement reference in the report;
7. does not embed raw licensed I/B/E/S rows in the normalized output.

A complete extract produces `g1_ready=true`. The normalized CSV can then be enabled as the existing `ibes_announcement` metadata source and run through `metadata_resolver.py` / the authorized-input orchestrator. The production resolver still requires all events to resolve exactly before `G1_ANNOUNCEMENT_TIMES` becomes READY.

## Why this does not weaken G1

The adapter changes the ingestion path, not the gate definition. In particular, it does not relabel public proxies as exact timestamps and it does not alter any of G2–G6.
