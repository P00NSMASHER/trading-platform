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

## 2026-09-28 source-research integration

The public exact-time sweep now has a separate machine-readable research layer at
`data/public/metadata/g1_source_research_20260928.json`, validated by
`src/g1_source_research.py`.

The current repository state is **37 public exact-time batches / 46 exact-resolved
historical event records**. Those are different counters because some batches resolve
more than one historical event.

The latest repository/dataset search did **not** locate a public one-stop dataset
containing the full 174-event exact first-public clock-time join. The public replication
press-release archive remains useful for release identity/date discovery, but its
candidate files do not preserve the required release-context clock times. The companion
public code confirms that the original research constructs exact timestamps from
I/B/E/S `ANNDATS_ACT + ANNTIMS_ACT`; the licensed rows themselves are not public.

The source-research map therefore records two things separately:

1. **Priority historical events** for the next public sweep: QLIK, TNGO, CAKE, NKE,
   and two NATI events. BCR has been removed after resolution in batch 0029. Ryder has also been resolved independently in batch 0030 from an issuer-hosted exact newsroom timestamp.
2. **Source-family probes** that help locate archives but are not evidence. In
   particular, 2026 Cheesecake Factory and Tangoe pages demonstrate durable
   issuer/Business Wire/SEC trails, but they are wrong-year and/or date-only records
   and are explicitly ineligible to resolve the 2015 G1 events.

Run the research queue validator with:

```bash
PYTHONPATH=src python -m g1_source_research
```

The validator cross-checks every priority event against the current fail-closed exclusion
dossier. A source-discovery probe cannot become evidence unless it matches the historical
event and carries an authoritative/authorized exact first-public clock. Wrong-year,
date-only, archive-capture, scheduled, inferred, and EDGAR-acceptance timestamps remain
ineligible.

If public searching stalls, the identified lawful one-stop path remains an entitled
LSEG I/B/E/S extract containing `ANNDATS_ACT` and `ANNTIMS_ACT`, passed through the
existing `g1_ibes_timestamp_adapter.py`.

### Batch 0030 recovery

Ryder event `HEJFE-A25F33B630365184` is resolved at `2015-02-03T08:55:00-05:00` from Ryder's issuer-hosted newsroom timestamp, with the matching SEC Exhibit 99.1 retained as corroboration. The frozen first documented trade occurred on February 2 at 3:43 PM New York time, so the release is strictly later and remains within the seven-calendar-day promotion window. The six existing priority events remain fail-closed and stay at the front of the public-research queue.

### Batch 0031 recovery

Acadia Healthcare event `HEJFE-6F0A7632D9B4FFF6` is resolved at `2015-04-28T16:00:00-04:00` from StreetInsider's preserved Business Wire distribution timestamp, with SEC Exhibit 99 retained as independent corroboration. The frozen first documented trade occurred at 2:35 PM New York time, so the release is strictly later and remains within the seven-calendar-day promotion window. The research queue remains fail-closed for all unresolved priority events.

### Batch 0032: AMD and Haemonetics public-clock recoveries

AMD resolves at 2013-10-17 16:15 Eastern from the original Marketwired distribution, now preserved by GlobeNewswire. Haemonetics resolves at 2012-01-30 08:00 Eastern from the explicit FOR RELEASE header in SEC Exhibit 99.1. Each is corroborated by its issuer archive. See the batch_0032 evidence dossier for exact URLs and short timestamp excerpts. This is 35 exact / 139 reviewed exclusions, not Step 9 completion. No WRDS access or vendor extract was used.

### Batch 0033: NVR original-wire recovery

NVR is recovered at 2012-01-26 08:50 ET (13:50 UTC) from PR Newswire's original issuer release, independently corroborated by SEC Exhibit 99.1. The clock is 60,840 seconds after the frozen first trade. This advances 35 exact / 139 reviewed exclusions to 36 exact / 138 reviewed exclusions and preserves every previous exact resolution, including AMD and Haemonetics. Evidence references and prior timestamps are in `data/public/metadata/g1_public_batch_0033_evidence.json`. Step 9 remains SOURCE_BLOCKED; no WRDS or paid vendor extract was used.

### Batch 0034: FleetCor + Starbucks preserved Business Wire clocks

FleetCor is recovered at 2015-04-30 16:01 EDT (20:01 UTC) from a preserved Business Wire publication timestamp, corroborated by SEC Exhibit 99.1. Starbucks is recovered at 2015-01-22 16:03 EST (21:03 UTC) from a preserved Business Wire publication timestamp, corroborated by the Starbucks investor-relations release. These clocks are 1,980 and 9,660 seconds after the frozen first trades respectively. The batch advances G1 from 36 exact / 138 reviewed exclusions to 38 exact / 136 reviewed exclusions. Conference-call times, EDGAR acceptance times, archive capture times and inferred AMC clocks remain prohibited substitutes. Step 9 remains SOURCE_BLOCKED.

### Batch 0035: Meritage x2 + Proofpoint + VeriSign

Meritage's own investor-relations archive supplies exact first-public clocks of 2013-04-24 08:00 EDT for Q1 and 2013-07-24 07:00 EDT for Q2. Preserved Yahoo copies of the original Marketwired releases supply 2013-04-25 20:05 UTC for both Proofpoint and VeriSign, independently corroborated by SEC Exhibit 99.1 copies. The four releases are 63,360, 56,520, 3,900 and 7,080 seconds after their frozen first trades respectively. This advances G1 from 38 exact / 136 reviewed exclusions to 42 exact / 132 reviewed exclusions. Scheduled conference-call times, EDGAR acceptance times, date-only pages and inferred clocks remain prohibited substitutes. Step 9 remains SOURCE_BLOCKED.

### Batch 0036: Micrel + Juniper Q2

Yahoo-preserved original Marketwired metadata supplies exact first-public timestamps of 2013-04-25 20:01 UTC for Micrel and 2013-07-23 20:05 UTC for Juniper Q2, independently corroborated by matching SEC Exhibit 99.1 releases. These are 5,340 and 3,720 seconds after the frozen first trades. This advances G1 from 42 exact / 132 reviewed exclusions to 44 exact / 130 reviewed exclusions. Conference-call times, EDGAR acceptance times, date-only pages and inferred clocks remain prohibited substitutes. Step 9 remains SOURCE_BLOCKED.

### Batch 0037: Monarch Casino + Stamps.com

Yahoo Finance preserves the original Marketwired publication metadata for Monarch Casino at 2013-04-25 20:05 UTC and Stamps.com at 2013-04-24 20:30 UTC. Matching SEC-filed issuer releases independently corroborate both. These clocks are 3,420 and 3,720 seconds after the frozen first trades. This advances G1 from 44 exact / 130 reviewed exclusions to 46 exact / 128 reviewed exclusions. Scheduled calls, EDGAR acceptance and inferred clocks remain prohibited substitutes. Step 9 remains SOURCE_BLOCKED.
