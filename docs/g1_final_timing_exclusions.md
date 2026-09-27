# G1 Final Timing Evidence Dossier

**G1 accounting remains complete: 174 / 174 events accounted for (100%).**

- **Exact first-public announcement timestamps resolved:** 1
- **Immutable reviewed fail-closed exclusions:** 173
- **Blocking unresolved:** 0
- **Gate status:** `READY_WITH_REVIEWED_EXCLUSIONS`
- **Events eligible for exact announcement-timing / information-asymmetry analysis:** 1

This does **not** invent announcement times.

The public `vgreg/hacked_earnings_jfe` press-release archive was scanned for all 174 events. It produced candidate release files for 160 events and no candidate file for 14. Across the candidate release text, the scan found **0 clock-time tokens** and **0 release-context clock times**.

The public companion repository `vgreg/earnings_news_jar` shows that the original research constructs `IBES_Timestamp` from proprietary I/B/E/S fields `ANNDATS_ACT` and `ANNTIMS_ACT`. Those proprietary timestamp rows are not present in the public repositories, and no public derivative containing the complete 174-event timestamp join was located.

The machine-readable receipt is `data/processed/authorized_input_real/g1_final_timing_exclusions.json`.

Excluded events are marked `excluded_fail_closed`. They retain blank `public_announcement_ts` and blank `information_asymmetry_seconds`, and they may not participate in timing-dependent analysis. EDGAR acceptance times, before/after-market labels, archive ZIP timestamps, and date-only release evidence are not promoted to exact announcement times.

If authorized exact I/B/E/S timestamps or independently verified exact first-public release times are supplied later, the resolver will reject any stale exclusion rather than masking the new evidence.

## First exact timestamp recovered

CNMD event `HEJFE-A413A5AC6E515E3C` is no longer excluded. SEC EDGAR Exhibit 99.1 contains the issuer's CONMED first-quarter 2011 earnings release and explicitly states `FOR RELEASE: 7:00 AM (Eastern) April 28, 2011`. The normalized public metadata row records `2011-04-28T07:00:00-04:00` as an A-grade `first_public_release` timestamp and binds it to the event ID. The remaining 173 events stay fail-closed until equivalent admissible evidence is found.

Source: https://www.sec.gov/Archives/edgar/data/816956/000091431711000622/ex99-1.htm
