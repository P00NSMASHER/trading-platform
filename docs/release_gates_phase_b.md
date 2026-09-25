# Release Gates Phase B — Exact First-Public Announcement Times

## Objective

Phase B targets **G1_ANNOUNCEMENT_TIMES**.

The current coverage plan requires an exact point-in-time public-release timestamp for **174 historical events**. The repository currently resolves **0 / 174**.

## Source hierarchy

The original study documentation identifies **I/B/E/S** as the source for earnings-announcement dates/times and **RavenPack** for matching announcements to press releases/newswires. Those are the cleanest bulk paths if an authorized entitlement/export is available.

The public fallback is an independently verified original issuer/newswire/SEC exhibit that explicitly preserves the actual release time.

### Accepted exact records

A row is eligible only when all of the following are true:

- the event ID/symbol/date match the historical corpus;
- `public_announcement_ts` is timezone-aware;
- `timestamp_kind` is `first_public_release` or `official_newswire_release`;
- `source_grade` is `A` or `B`;
- `source_reference` identifies the exact source used;
- the timestamp is later than the documented first illicit trade;
- cross-source exact timestamps do not create a blocking Step-19 conflict.

### Not sufficient

The following must not be promoted into an exact timestamp merely to satisfy the gate:

- SEC EDGAR `ACCEPTANCE-DATETIME` by itself;
- conference-call start time;
- a page that gives only the announcement date;
- a current earnings-calendar reconstruction with no historical provenance;
- an inferred timestamp based on market reaction.

## Files

Populate the private input file:

`data/private/metadata/announcement_timestamps.csv`

using the header in:

`data/templates/announcement_timestamps.phase_b.csv`

The raw/private working file must not be committed to the public repository.

Audit before ingestion:

```bash
python src/announcement_timestamp_audit.py \
  --requirements data/processed/coverage_plan_real/announcement_timestamp_requirements.csv \
  --events data/processed/historical_events.csv \
  --candidates data/private/metadata/announcement_timestamps.csv \
  --outdir data/processed/announcement_timestamp_audit
```

A Phase-B audit is complete only when the summary reports:

- `required_events = 174`
- `ready_events = 174`
- `missing_events = 0`
- `blocking_events = 0`
- `g1_candidate_ready = true`

Then ingest through Step 21:

```bash
PYTHONPATH=src python src/authorized_input_orchestrator.py ingest \
  --root . \
  --batch-manifest config/authorized_input_batch.phase_b.example.json \
  --runtime-dir private_runtime/authorized_input_ingestion \
  --outdir data/processed/authorized_input_ingestion \
  --expected-champion-sha256 0c8c16c9be734152c0018aa40e576fe4db9f4621359fafe521465890f9945616
```

Step 17/19/20 remain authoritative. The Phase-B audit is an earlier fail-fast check, not a replacement release gate.

## Current blocker

The repository does not contain an authorized I/B/E/S/RavenPack export or a complete 174-row independently verified official timestamp set. Therefore G1 must remain BLOCKED until the exact source data are supplied.
