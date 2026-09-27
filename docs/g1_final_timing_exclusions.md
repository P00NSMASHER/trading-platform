# G1 Final Timing Evidence Dossier

**G1 accounting remains complete: 174 / 174 events accounted for (100%).**

- **Exact first-public announcement timestamps resolved:** 8
- **Immutable reviewed fail-closed exclusions:** 166
- **Blocking unresolved:** 0
- **Gate status:** `READY_WITH_REVIEWED_EXCLUSIONS`
- **Events eligible for exact announcement-timing / information-asymmetry analysis:** 8

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

## Public newswire batch 0003

One additional event now has an exact public-release timestamp from the issuer-specific PR Newswire archive and is removed from the reviewed G1 exclusion set:

- `HEJFE-30CA515BC590DDA6` (ROL): `2012-01-25T07:30:00-05:00`. Rollins' PR Newswire archive records `Rollins, Inc. Reports Fourth Quarter and Full-Year 2011 Financial Results` at Jan. 25, 2012, 07:30 ET.

The other 170 events remain fail-closed until equivalent admissible evidence is located.

## Public newswire batch 0004

One additional event now has an exact public-release timestamp from the issuer-specific PR Newswire archive and is removed from the reviewed G1 exclusion set:

- `HEJFE-D1D8268651584B6A` (MKC): `2013-04-02T06:30:00-04:00`. McCormick's PR Newswire archive records `McCormick Reports First Quarter Financial Results, Reaffirms 2013 Outlook` at Apr. 2, 2013, 06:30 ET.

The other 169 events remain fail-closed until equivalent admissible evidence is located.

## Issuer archive batch 0005

One additional event now has an exact public-release timestamp from the issuer's historical press-release archive and is removed from the reviewed G1 exclusion set:

- `HEJFE-F170013A9B3F85E2` (SKX): `2015-04-22T16:01:00-04:00`. Skechers' issuer archive records `SKECHERS Announces First Quarter 2015 Financial Results` at Apr. 22, 2015, 4:01 pm EDT and identifies Business Wire distribution.

The other 168 events remain fail-closed until equivalent admissible evidence is located.

## Issuer archive batch 0006

Two additional ADI events now have exact public-release timestamps from Analog Devices' issuer investor-relations archive and are removed from the reviewed G1 exclusion set:

- `HEJFE-D9C52E6CC595C380` (ADI): `2015-02-17T16:05:00-05:00`. Analog Devices' archive records the first-quarter fiscal 2015 results at Feb. 17, 2015, 4:05 PM EST.
- `HEJFE-09EB83905864C50A` (ADI): `2015-05-19T16:00:00-04:00`. Analog Devices' archive records the second-quarter fiscal 2015 results at May 19, 2015, 4:00 PM EDT.

The other 166 events remain fail-closed until equivalent admissible evidence is located.
