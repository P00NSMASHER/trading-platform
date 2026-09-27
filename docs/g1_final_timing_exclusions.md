# G1 Final Timing Evidence Dossier

**G1 accounting remains complete: 174 / 174 events accounted for (100%).**

- **Exact first-public announcement timestamps resolved:** 3
- **Immutable reviewed fail-closed exclusions:** 171
- **Blocking unresolved:** 0
- **Gate status:** `READY_WITH_REVIEWED_EXCLUSIONS`
- **Events eligible for exact announcement-timing / information-asymmetry analysis:** 3

This does **not** invent announcement times.

The public `vgreg/hacked_earnings_jfe` press-release archive was scanned for all 174 events. It produced candidate release files for 160 events and no candidate file for 14. Across the candidate release text, the scan found **0 clock-time tokens** and **0 release-context clock times**.

The public companion repository `vgreg/earnings_news_jar` shows that the original research constructs `IBES_Timestamp` from proprietary I/B/E/S fields `ANNDATS_ACT` and `ANNTIMS_ACT`. Those proprietary timestamp rows are not present in the public repositories, and no public derivative containing the complete 174-event timestamp join was located.

The machine-readable receipt is `data/processed/authorized_input_real/g1_final_timing_exclusions.json`.

Excluded events are marked `excluded_fail_closed`. They retain blank `public_announcement_ts` and blank `information_asymmetry_seconds`, and they may not participate in timing-dependent analysis. EDGAR acceptance times, before/after-market labels, archive ZIP timestamps, and date-only release evidence are not promoted to exact announcement times.

If authorized exact I/B/E/S timestamps or independently verified exact first-public release times are supplied later, the resolver will reject any stale exclusion rather than masking the new evidence.

## First exact timestamp recovered

CNMD event `HEJFE-A413A5AC6E515E3C` is no longer excluded. SEC EDGAR Exhibit 99.1 contains the issuer's CONMED first-quarter 2011 earnings release and explicitly states `FOR RELEASE: 7:00 AM (Eastern) April 28, 2011`. The normalized public metadata row records `2011-04-28T07:00:00-04:00` as an A-grade `first_public_release` timestamp and binds it to the event ID. The remaining 173 events stay fail-closed until equivalent admissible evidence is found.

Source: https://www.sec.gov/Archives/edgar/data/816956/000091431711000622/ex99-1.htm

## Public newswire batch 0002

Two additional events now have exact public-release timestamps from PR Newswire issuer archives and are removed from the reviewed G1 exclusion set:

- `HEJFE-95933AA0B84D2F60` (CAT): `2012-01-26T07:30:00-05:00`. PR Newswire's Caterpillar archive timestamps the earnings release at Jan. 26, 2012, 07:30 ET; Caterpillar's archived 4Q 2011 release corroborates the title and date.
- `HEJFE-A9D220DE2F7E7FC3` (DE): `2015-02-20T07:00:00-05:00`. PR Newswire's Deere archive timestamps the earnings release at Feb. 20, 2015, 07:00 ET; SEC Exhibit 99.1 corroborates the title and date.

The other 171 events remain fail-closed until equivalent admissible evidence is located.
