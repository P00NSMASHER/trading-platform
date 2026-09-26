# G1 — exact public announcement timestamp adapter

`src/g1_announcement_adapter.py` is the fail-closed bridge between an **authorized I/B/E/S actual-announcement export** and the existing point-in-time metadata resolver.

## Why this exists

The public `vgreg/hacked_earnings_jfe` replication package provides the 174 first-trade observations, but its README says the earnings announcement dates and times used by the study come from I/B/E/S. The companion public repository `vgreg/earnings_news_jar` shows the exact source fields used by the authors:

- `ANNDATS_ACT`
- `ANNTIMS_ACT`

and constructs `IBES_Timestamp` from those two fields.

The proprietary I/B/E/S data itself is not in either public repository. This adapter therefore **does not invent or infer announcement times** and does not relabel SEC filing acceptance times, "before market", "after market", or date-only data as exact release timestamps.

## Accepted inputs

The I/B/E/S CSV must contain:

- `ANNDATS_ACT`
- `ANNTIMS_ACT`
- either `PERMNO`, or a ticker column (`TICKER`/`OFTIC`) plus `--ibes-link`

When `--ibes-link` is used, the link CSV must contain the same four fields used by the public companion research code:

- `TICKER`
- `PERMNO`
- `sdate`
- `edate`

No credentials belong in any input or config file.

## Run

```bash
PYTHONPATH=src python src/g1_announcement_adapter.py \
  --events data/processed/historical_events.csv \
  --ibes /private/path/authorized_ibes_actuals.csv \
  --ibes-link /private/path/ibes_ticker_permno_link_file.csv \
  --output-dir private_runtime/g1 \
  --source-reference "INTERNAL-IBES-ENTITLEMENT-REFERENCE"
```

For a pinned source import, add:

```bash
--expected-ibes-sha256 <64-hex-digest>
```

## Outputs

- `announcement_timestamps.csv` — canonical exact timestamp rows accepted by `metadata_resolver.py`
- `metadata_source_contract.json` — enabled G1 source contract pointing at the generated CSV
- `unresolved_events.csv` — events that cannot be resolved exactly
- `ambiguous_events.csv` — events with conflicting exact times on the nearest release date
- `g1_summary.json` — source hashes and readiness counts

`ready_for_g1` is true only when **every historical event** has exactly one eligible timestamp and there are zero unresolved or ambiguous events.

## Fail-closed behavior

The adapter rejects or leaves unresolved:

- missing `ANNTIMS_ACT`
- date-only records
- inferred BMO/AMC clock times
- conflicting exact timestamps on the same nearest release date
- announcements outside the configured forward horizon
- mismatched source hashes

This keeps G1 a real evidence gate. Installing the adapter does **not** make the current 174-event dataset pass G1 by itself; an authorized exact timestamp export must be supplied and fully resolve the corpus.
