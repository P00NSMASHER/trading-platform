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

The current repository state is **53 public exact-time batches / 79 exact-resolved
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

### Batch 0038: Century Aluminum + eHealth + Gardner Denver

A clustered 2013-04-25 sweep recovered Century Aluminum at 2013-04-25 20:00 UTC, eHealth at 2013-04-25 20:15 UTC, and Gardner Denver at 2013-04-26 13:44 UTC. Yahoo/MarketScreener preserve the Marketwired publication clocks and independent SEC/issuer releases corroborate all three. The clocks are 2,280, 1,140, and 66,420 seconds after the frozen first trades. This advances G1 from 46 exact / 128 reviewed exclusions to 49 exact / 125 reviewed exclusions. Scheduled calls, EDGAR acceptance and inferred clocks remain prohibited substitutes. Step 9 remains SOURCE_BLOCKED.

### Batch 0039: Pall Corporation

Pall Corporation is recovered at 2015-02-24 07:00 EST (12:00 UTC) from a MarketScreener-preserved Business Wire publication timestamp, independently corroborated by SEC Exhibit 99.1. The release is 57,420 seconds after the frozen first trade. This advances G1 from 49 exact / 125 reviewed exclusions to 50 exact / 124 reviewed exclusions. The 08:30 EST conference call, EDGAR acceptance time, date-only pages and inferred clocks remain prohibited substitutes. Step 9 remains SOURCE_BLOCKED.

### Batch 0040: MDU Resources + Cabot + Oshkosh

A clustered public-wire sweep recovered MDU Resources at 2015-05-04 17:30 EDT (21:30 UTC), Cabot at 2015-04-29 16:05 EDT (20:05 UTC), and Oshkosh at 2015-04-28 07:00 EDT (11:00 UTC). MarketScreener preserves the Business Wire publication clocks; original Business Wire, issuer IR, and SEC-filed evidence independently corroborate the releases. The clocks are 5,580, 9,120, and 55,860 seconds after their frozen first trades. This advances G1 from 50 exact / 124 reviewed exclusions to 53 exact / 121 reviewed exclusions. Scheduled calls, EDGAR acceptance and inferred clocks remain prohibited substitutes. Step 9 remains SOURCE_BLOCKED.

### Batch 0041: Dendreon + CA Technologies (three timestamps)

A direct primary-newswire sweep recovered Dendreon at 2011-08-03 16:01 EDT (20:01 UTC), CA Technologies at 2011-07-20 16:05 EDT (20:05 UTC), and CA Technologies again at 2012-01-24 16:05 EST (21:05 UTC). PR Newswire's historical company archives preserve the exact publication clocks, while SEC-filed Exhibit 99.1 releases independently corroborate title, issuer, date, and reporting period. The clocks are 300, 1,140, and 9,180 seconds after their frozen first trades. This advances G1 from 53 exact / 121 reviewed exclusions to 56 exact / 118 reviewed exclusions. Scheduled calls, EDGAR acceptance and inferred clocks remain prohibited substitutes. Step 9 remains SOURCE_BLOCKED.

### Batch 0042: Foot Locker + Meredith + International Game Technology

A direct primary-newswire sweep recovered Foot Locker at 2011-08-18 16:45 EDT (20:45 UTC), Meredith at 2012-01-24 09:15 EST (14:15 UTC), and International Game Technology at 2012-01-24 06:30 EST (11:30 UTC). PR Newswire historical company archives preserve the exact publication clocks, while SEC-filed exhibits independently corroborate issuer, release title, date, and reporting period. The clocks are 3,720, 66,960, and 53,940 seconds after their frozen first trades. This advances G1 from 56 exact / 118 reviewed exclusions to 59 exact / 115 reviewed exclusions. Scheduled calls, EDGAR acceptance and inferred clocks remain prohibited substitutes. Step 9 remains SOURCE_BLOCKED.

### Batch 0043: Varian + Astoria + Symmetricom + ISSI + Destination Maternity

A clustered primary-newswire sweep recovered five additional exact first-public clocks after Batch 0042: Varian Medical Systems at 2012-01-25 16:01 EST, Astoria Financial at 16:30 EST, Symmetricom at 16:18 EST, ISSI at 16:10 EST, and Destination Maternity at 2012-01-26 06:00 EST. PR Newswire historical archives preserve the exact publication clocks, while SEC-filed issuer releases independently corroborate issuer, title, date, and reporting period. This advances G1 from 59 exact / 115 reviewed exclusions to 64 exact / 110 reviewed exclusions. Scheduled calls, EDGAR acceptance, archive-capture, date-only, and inferred clocks remain prohibited substitutes. Step 9 remains SOURCE_BLOCKED.

### Batch 0044: IBERIABANK + Microsemi

A primary-newswire sweep recovered two additional exact first-public clocks: IBERIABANK Corporation at 2012-01-25 16:30 EST (21:30 UTC) and Microsemi at 2012-01-26 16:00 EST (21:00 UTC). PR Newswire historical company archives preserve the exact publication clocks, while SEC-filed Exhibit 99.1 releases independently corroborate issuer, title, date, and reporting period. The clocks are 95,820 and 4,140 seconds after their frozen first trades. This advances G1 from 64 exact / 110 reviewed exclusions to 66 exact / 108 reviewed exclusions. Scheduled calls, EDGAR acceptance, archive-capture, date-only, and inferred clocks remain prohibited substitutes. Step 9 remains SOURCE_BLOCKED.

### Batch 0045: IDEXX + Tempur-Pedic

A primary-newswire sweep recovered two additional exact first-public clocks: IDEXX Laboratories at 2012-01-27 07:00 EST (12:00 UTC) and Tempur-Pedic at 2011-07-26 16:05 EDT (20:05 UTC). PR Newswire historical company archives preserve the exact publication clocks, while SEC-filed Exhibit 99.1 releases independently corroborate issuer, title, date, and reporting period. The clocks are 61,980 and 8,700 seconds after their frozen first trades. This advances G1 from 66 exact / 108 reviewed exclusions to 68 exact / 106 reviewed exclusions. Scheduled calls, scheduled-release announcements, EDGAR acceptance, archive-capture, date-only, and inferred clocks remain prohibited substitutes. Step 9 remains SOURCE_BLOCKED.

### Batch 0046: Amerigroup + Metals USA + Landstar

A primary-newswire sweep recovered three additional exact first-public clocks: Amerigroup at 2011-10-28 06:00 EDT (10:00 UTC), Metals USA at 2011-10-20 17:09 EDT (21:09 UTC), and Landstar at 2011-10-24 07:50 EDT (11:50 UTC). PR Newswire historical company archives preserve the exact publication clocks, while SEC-filed Exhibit 99.1 releases independently corroborate issuer, title, date, and reporting period. The clocks are 61,020, 4,860, and 230,520 seconds after their frozen first trades. This advances G1 from 68 exact / 106 reviewed exclusions to 71 exact / 103 reviewed exclusions. Scheduled calls, scheduled-release announcements, EDGAR acceptance, archive-capture, date-only, and inferred clocks remain prohibited substitutes. Step 9 remains SOURCE_BLOCKED.

### Batch 0047: World Acceptance Corporation

A direct primary-newswire recovery established World Acceptance Corporation's exact first-public clock at 2012-01-25 06:30 EST (11:30 UTC), 52,620 seconds after the frozen 2012-01-24 15:53 EST trade. PR Newswire's historical release page preserves the exact publication clock, while SEC-filed Exhibit 99.1 independently corroborates issuer, title, date, and third-quarter fiscal 2012 results. This advances G1 from 71 exact / 103 reviewed exclusions to 72 exact / 102 reviewed exclusions. Conference-call, scheduled-release, EDGAR acceptance, archive-capture, date-only, and inferred clocks remain prohibited substitutes. Step 9 remains SOURCE_BLOCKED.

### Batch 0048: SYNNEX Corporation

A timestamp-preserving StreetInsider mirror of the Business Wire release establishes SYNNEX Corporation's exact first-public clock at 2015-03-31 16:03 EDT (20:03 UTC), 540 seconds after the frozen 15:54 EDT trade. SEC Exhibit 99.1 independently corroborates issuer, title, date, and fiscal first-quarter 2015 results. This advances G1 from 72 exact / 102 reviewed exclusions to 73 exact / 101 reviewed exclusions. The separately stated conference-call time, EDGAR acceptance, archive-capture, date-only, scheduled-release, and inferred clocks are not used. Step 9 remains SOURCE_BLOCKED.

### Batch 0049: RPC, Inc.

A direct primary-newswire recovery established RPC, Inc.'s exact first-public clock at 2012-01-25 07:22 EST (12:22 UTC), 57,720 seconds after the frozen 2012-01-24 15:20 EST trade. PR Newswire's historical RPC archive preserves the exact publication clock, while the SEC-filed Exhibit 99 independently corroborates issuer, title, date, and fourth-quarter/full-year 2011 results. This advances G1 from 73 exact / 101 reviewed exclusions to 74 exact / 100 reviewed exclusions. Conference-call, scheduled-release, EDGAR acceptance, archive-capture, date-only, and inferred clocks remain prohibited substitutes. Step 9 remains SOURCE_BLOCKED.

### Batch 0050: Anadarko Petroleum Corporation

A timestamp-preserving public-wire recovery established Anadarko Petroleum Corporation's exact first-public clock at 2013-05-06 18:15 EDT (22:15 UTC), 17,280 seconds after the frozen 2013-05-06 13:27 EDT trade. MarketScreener preserves the Marketwired release with an explicit 06:15 pm EDT publication clock, while SEC Exhibit 99 independently corroborates issuer, title, date, and first-quarter 2013 results. This advances G1 from 74 exact / 100 reviewed exclusions to 75 exact / 99 reviewed exclusions. Conference-call, scheduled-release, EDGAR acceptance, archive-capture, date-only, and inferred clocks remain prohibited substitutes. Step 9 remains SOURCE_BLOCKED.

### Batch 0051: Metals USA Holdings Corp.

A direct primary-newswire recovery established Metals USA Holdings Corp.'s exact first-public clock at 2012-01-26 16:05 EST (21:05 UTC), 13,440 seconds after the frozen 2012-01-26 12:21 EST trade. PR Newswire's historical Metals USA archive preserves the exact publication clock, while SEC Exhibit 99.1 independently corroborates issuer, title, date, and fiscal-2011 results. This advances G1 from 75 exact / 99 reviewed exclusions to 76 exact / 98 reviewed exclusions. Conference-call, scheduled-release, EDGAR acceptance, archive-capture, date-only, and inferred clocks remain prohibited substitutes. Step 9 remains SOURCE_BLOCKED.

### Batch 0052: ConAgra Foods, Inc.

A timestamp-preserving public-wire mirror established ConAgra Foods, Inc.'s exact first-public clock at 2015-03-26 07:30 EDT (11:30 UTC), 58,260 seconds after the frozen 2015-03-25 15:19 EDT trade. StreetInsider preserves the Business Wire release with an explicit March 26, 2015 7:30 AM EDT publication clock, while SEC Exhibit 99.1 independently corroborates issuer, exact release title, date, and fiscal 2015 third-quarter results. The separately stated 9:30 a.m. EDT conference call is not used. This advances G1 from 76 exact / 98 reviewed exclusions to 77 exact / 97 reviewed exclusions. Conference-call, scheduled-release, EDGAR acceptance, archive-capture, date-only, and inferred clocks remain prohibited substitutes. Step 9 remains SOURCE_BLOCKED.

### Batch 0053: Cornerstone OnDemand and Nordson Corporation

Timestamp-preserving StreetInsider mirrors of the original Business Wire releases establish Cornerstone OnDemand's exact first-public clock at 2015-05-06 16:01 EDT (20:01 UTC), 1,920 seconds after the frozen 15:29 EDT trade, and Nordson Corporation's exact first-public clock at 2015-05-19 16:30 EDT (20:30 UTC), 3,300 seconds after the frozen 15:35 EDT trade. Matching SEC Exhibits 99.1 independently corroborate each issuer, title, date, quarter, and release body. This advances G1 from 77 exact / 97 reviewed exclusions to 79 exact / 95 reviewed exclusions. Conference-call, EDGAR acceptance, archive-capture, date-only, scheduled-release, and inferred clocks are not used. Step 9 remains SOURCE_BLOCKED.
