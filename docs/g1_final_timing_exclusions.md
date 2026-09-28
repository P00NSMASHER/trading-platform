# G1 Final Timing Evidence Dossier

**G1 accounting remains complete: 174 / 174 events accounted for (100%).**

- **Exact first-public announcement timestamps resolved:** 30
- **Immutable reviewed fail-closed exclusions:** 144
- **Blocking unresolved:** 0
- **Gate status:** `READY_WITH_REVIEWED_EXCLUSIONS`
- **Events eligible for exact announcement-timing / information-asymmetry analysis:** 30

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

## SEC release-clock batch 0007

One additional event now has an exact first-public release clock directly stated in the issuer's SEC-hosted earnings exhibit:

- `HEJFE-7ED8DBD4804E4330` (JWN): `2015-02-19T16:05:00-05:00`. Nordstrom Exhibit 99.1 states `FOR RELEASE: February 19, 2015 at 1:05 PM PST`, which converts to 4:05 PM EST.

The other 165 events remain fail-closed until equivalent admissible evidence is located.

## Original-wire archive batch 0008

One additional event now has an exact public-release timestamp from the original PR Newswire issuer archive and is removed from the reviewed G1 exclusion set:

- `HEJFE-87DDC59E7BB99A84` (ALSN): `2015-04-27T16:10:00-04:00`. PR Newswire's Allison Transmission archive lists `Allison Transmission Announces First Quarter 2015 Results` at Apr. 27, 2015, 04:10 ET.

The other 164 events remain fail-closed until equivalent admissible evidence is located.

## SEC release-clock batch 0009

One additional event now has an exact public-release timestamp directly stated in the issuer's SEC-hosted earnings release:

- `HEJFE-76B03970FA6BDB42` (AVA): `2013-02-20T07:05:00-05:00`. Avista's release states `SPOKANE, Wash. – Feb. 20, 2013, 4:05 a.m. PT`, which converts to 7:05 a.m. ET.

The other 163 events remain fail-closed until equivalent admissible evidence is located.

## Issuer/original-wire archive batch 0010

One additional event now has an exact public-release timestamp from Gilead's archived Business Wire earnings release:

- `HEJFE-C4D39B22234902F2` (GILD): `2015-02-03T16:07:00-05:00`. Gilead's archived fourth-quarter and full-year 2014 results release is timestamped `February 3, 2015 4:07 PM ET` and identifies Business Wire distribution.

The other 162 events remain fail-closed until equivalent admissible evidence is located.

## Independently verified Business Wire batch 0011

One additional event now has an exact public-release timestamp recovered from a preserved Business Wire mirror and corroborated against the issuer's identical Business Wire release:

- `HEJFE-8A11E54A9679E09D` (ILMN): `2015-01-27T16:05:00-05:00`. The preserved Business Wire copy is published at Jan. 27, 2015, 4:05 PM EST; its Business Wire tracking request exposes story ID `20150127006397`. Illumina's issuer archive reproduces the identical Business Wire earnings release. This row is deliberately graded `B`, not `A`, because the exact clock is recovered from the preserved wire mirror rather than a currently fetchable first-party Business Wire article page.

The other 161 events remain fail-closed until equivalent admissible evidence is located.

## Independently verified issuer-attributed distribution batch 0012

One additional event now has an exact public-release timestamp recovered from an issuer-attributed distribution archive and corroborated against the issuer's official archive:

- `HEJFE-0B87675BF7BEDBCA` (EA): `2015-01-27T16:35:00-05:00`. EIN Presswire preserves `Electronic Arts Reports Q3 FY15 Financial Results` as `News Provided By Electronic Arts` at Jan. 27, 2015, 21:35 GMT (4:35 PM EST). EA's official news archive independently reproduces the same release title, date, and content. This row is deliberately graded `B`, not `A`, because the exact clock is recovered from the issuer-attributed distribution archive rather than EA's own page.

The other 160 events remain fail-closed until equivalent admissible evidence is located.

## Independently verified Business Wire batch 0013

One additional event now has an exact public-release timestamp recovered from a preserved Business Wire mirror and corroborated against the issuer's SEC-hosted Business Wire exhibit:

- `HEJFE-DC66D5F2BDEC7C74` (NOW): `2015-01-28T16:05:00-05:00`. MarketScreener preserves `ServiceNow Reports Financial Results for Fourth Quarter and Fiscal Year 2014` as published Jan. 29, 2015 at 08:05 AEDT, equivalent to Jan. 28 at 4:05 PM EST. SEC Exhibit 99.1 independently corroborates the identical Business Wire release. This row is deliberately graded `B`, not `A`, because the exact clock is recovered from the preserved mirror rather than a currently fetchable first-party Business Wire article page.

The other 159 events remain fail-closed until equivalent admissible evidence is located.

## Independently verified Business Wire batch 0014

One additional event now has an exact public-release timestamp recovered from a preserved Business Wire mirror and corroborated against the SEC-hosted issuer release:

- `HEJFE-6101FFEDBA6EE41B` (MDU): `2015-02-02T17:30:00-05:00`. MarketScreener preserves `MDU Resources Reports Higher 2014 Earnings, Initiates Guidance for 2015` as published Feb. 2, 2015 at 5:30 PM EST and identifies Business Wire. SEC Exhibit 99 independently reproduces the same release title, date, and content. This row is deliberately graded `B`, not `A`, because the exact clock is recovered from the preserved wire mirror rather than a currently fetchable first-party Business Wire article page.

The other 158 events remain fail-closed until equivalent admissible evidence is located.

## Independently verified Business Wire batch 0015

One additional event now has an exact public-release timestamp recovered from a preserved Business Wire mirror and corroborated against the SEC-hosted issuer release:

- `HEJFE-3ADF019D07BA84CE` (HBI): `2015-01-29T16:05:00-05:00`. MarketScreener preserves `HanesBrands Reports Fourth-Quarter 2014 Financial Results` as published Jan. 29, 2015 at 4:05 PM EST and identifies Business Wire. SEC Exhibit 99.1 independently reproduces the same issuer release title, date, and content. This row is deliberately graded `B`, not `A`, because the exact clock is recovered from the preserved wire mirror rather than a currently fetchable first-party Business Wire article page.

The other 157 events remain fail-closed until equivalent admissible evidence is located.

## Issuer-hosted Business Wire batch 0016

One additional event now has an exact first-public release timestamp directly preserved by the issuer's investor-relations archive:

- `HEJFE-E342F6A93B35E012` (GNRC): `2015-02-11T06:00:00-05:00`. Generac's issuer-hosted archive explicitly timestamps `Generac Reports Fourth Quarter and Full-Year 2014 Results` at `Feb. 11, 2015 11:00 UTC` and identifies Business Wire distribution. SEC Exhibit 99.1 independently corroborates the same release title, date, and content. This row is graded `A` because the exact clock is preserved by the issuer-hosted release itself.

The other 156 events remain fail-closed until equivalent admissible evidence is located.

## Independently verified Business Wire batch 0017

One additional event now has an exact public-release timestamp recovered from a preserved Business Wire article and corroborated against the SEC-hosted issuer release:

- `HEJFE-48B08BAEDCEEDEFC` (SNDK): `2015-01-21T16:05:00-05:00`. MarketScreener preserves `SanDisk Announces Fourth Quarter and Fiscal 2014 Results` as published Jan. 21, 2015 at 4:05 PM EST and labels it Business Wire. SEC Exhibit 99.1 independently reproduces the same SanDisk release title, date, and content. This row is deliberately graded `B`, not `A`, because the exact clock is recovered from the preserved Business Wire mirror rather than a currently fetchable first-party Business Wire article page.

The other 155 events remain fail-closed until equivalent admissible evidence is located.

## Independently verified issuer-attributed distribution batch 0018

One additional event now has an exact public-release timestamp recovered from EIN Presswire's historical release calendar and independently corroborated against both the issuer archive and SEC exhibit:

- `HEJFE-753716A61B8622B0` (GME): `2015-03-26T16:29:00-04:00`. EIN Presswire records `GameStop Reports Sales and Earnings for Fiscal 2014 and Provides 2015 Outlook` at `March 26, 2015 - 20:29 GMT` and reproduces the Business Wire dateline. GameStop's issuer archive and SEC Exhibit 99.1 independently match the same release. This row is deliberately graded `B`, not `A`, because the exact clock is recovered from an issuer-attributed distribution archive rather than the issuer-hosted page itself.

The other 154 events remain fail-closed until equivalent admissible evidence is located.

## Independently verified Business Wire batch 0019

One additional event now has an exact public-release timestamp recovered from a preserved Business Wire article and corroborated against the SEC-hosted issuer release:

- `HEJFE-00D863517A3A754C` (URI): `2015-01-21T16:10:00-05:00`. MarketScreener preserves `United Rentals Announces Fourth Quarter and Full Year 2014 Results and Provides 2015 Outlook` as published Jan. 21, 2015 at 4:10 PM EST and labels it Business Wire. SEC Exhibit 99.1 independently reproduces the same United Rentals release title, date, and content. This row is deliberately graded `B`, not `A`, because the exact clock is recovered from the preserved Business Wire mirror rather than a currently fetchable first-party Business Wire page.

The other 153 events remain fail-closed until equivalent admissible evidence is located.

## Issuer-hosted release-clock batch 0020

One additional event now has an exact first-public release timestamp directly preserved by the issuer's newsroom:

- `HEJFE-1E37362063697486` (FLR): `2015-02-18T08:30:00-05:00`. Fluor's issuer-hosted newsroom explicitly timestamps `Fluor Reports Fourth Quarter and Full Year 2014 Results` on Wednesday, February 18, 2015 at 08:30 AM. SEC Exhibit 99.1 independently corroborates the same release title, date, and content. This row is graded `A` because the exact clock is preserved by the issuer-hosted release itself.

The other 152 events remain fail-closed until equivalent admissible evidence is located.

## Independently verified PR Newswire batch 0021

One additional event now has an exact public-release timestamp recovered from a preserved PRNewswire article and corroborated against the SEC-hosted issuer release:

- `HEJFE-76DCF0FCA248E814` (CB): `2012-01-26T16:03:00-05:00`. MarketScreener preserves `Chubb Reports Fourth Quarter Net Income per Share of $1.60; Operating Income per Share Is $1.63; Combined Ratio Is 89.9%` as published Jan. 26, 2012 at 4:03 PM EST and identifies PRNewswire. PR Newswire's Chubb archive lists the same release at 04:03 ET, while SEC Exhibit 99.1 independently reproduces the same release title, date, and content. This row is deliberately graded `B`, not `A`, because the explicit PM clock is recovered from the preserved wire mirror rather than a currently fetchable first-party PRNewswire article page.

The other 151 events remain fail-closed until equivalent admissible evidence is located.

## Independently verified Marketwired batch 0022

One additional event now has an exact public-release timestamp recovered from a preserved Marketwired distribution page and corroborated against Juniper Networks' issuer-hosted release:

- `HEJFE-2558DC6865781793` (JNPR): `2013-04-23T16:05:00-04:00`. The preserved distribution page explicitly shows `April 23, 2013 16:05 ET` for `Juniper Networks Reports Preliminary First Quarter 2013 Financial Results` and identifies Juniper Networks as the source. Juniper's issuer-hosted PDF independently reproduces the same release title, date, and content. This row is deliberately graded `B`, not `A`, because the exact clock is recovered from the preserved distribution archive rather than a currently fetchable original Marketwired article page.

The other 150 events remain fail-closed until equivalent admissible evidence is located.

## Independently verified PR Newswire batch 0023

One additional event now has an exact public-release timestamp recovered from a preserved PR Newswire article and corroborated against Honeywell's SEC-hosted issuer release:

- `HEJFE-8D40B9782E1E6F33` (HON): `2012-01-27T07:30:00-05:00`. MarketScreener preserves Honeywell's full-year 2011 earnings release as published Jan. 27, 2012 at 12:30 PM GMT (7:30 AM EST) and labels the article PRNewswire. SEC Exhibit 99 independently reproduces the same Honeywell release title, date, and content; Honeywell's 8-K also states that the earnings release was distributed on PR Newswire approximately two hours before its 9:30 AM ET conference call. This row is deliberately graded `B`, not `A`, because the exact clock is recovered from the preserved PR Newswire mirror rather than a currently fetchable first-party PR Newswire article page.

The other 149 events remain fail-closed until equivalent admissible evidence is located.

## Preserved Business Wire distribution copy batch 0024

One additional event now has an exact public-release timestamp recovered from a preserved copy of the original Business Wire distribution and independently corroborated against PVH's issuer archive and SEC exhibit:

- `HEJFE-DF726FADF321F8E3` (PVH): `2015-03-25T16:01:00-04:00`. The preserved distribution copy records `PVH Corp. Reports 2014 Fourth Quarter and Full Year Results and Announces 2015 Outlook` at `Wed March 25, 2015 4:01 PM | Business Wire`. PVH's issuer-hosted page independently reproduces the same Business Wire release and date, and SEC Exhibit 99.1 corroborates the release text. This row is deliberately graded `B`, not `A`, because the literal clock survives in the preserved distribution copy rather than the current issuer page.

The other 148 events remain fail-closed until equivalent admissible evidence is located.

## SEC issuer release-clock batch 0025

One additional event now has an exact first-public release clock directly stated in the issuer's SEC-hosted earnings exhibit:

- `HEJFE-E8C5063581BE7EB7` (F): `2015-01-29T07:00:00-05:00`. Ford's Exhibit 99 states that Ford Motor Company releases its preliminary 2014 fourth-quarter financial results at `7:00 a.m. EST` on Thursday, January 29, 2015. The exhibit separately schedules the earnings conference call for 9:00 a.m. EST, so the 7:00 a.m. value is explicitly the release time rather than the call time. Ford's media-hosted copy independently preserves the same language. This row is graded `A`.

The other 147 events remain fail-closed until equivalent admissible evidence is located.

## Independently verified Business Wire batch 0026

One additional event now has an exact public-release timestamp recovered from a preserved Business Wire article and independently corroborated against both the issuer archive and SEC filing:

- `HEJFE-EC5EB2BE0D97833F` (STT): `2015-01-23T05:52:00-05:00`. MarketScreener preserves State Street's fourth-quarter/full-year 2014 results release as `Published on 01/23/2015 at 10:52 am GMT` and labels it `Business Wire`. State Street's issuer-hosted archive reproduces the same Business Wire release, and its SEC Form 8-K states that on January 23, 2015 State Street issued the news release announcing those results. This row is deliberately graded `B`, not `A`, because the literal clock is recovered from the preserved Business Wire mirror rather than the issuer-hosted page itself.

The other 146 events remain fail-closed until equivalent admissible evidence is located.

## Independently verified Business Wire batch 0027

One additional event now has an exact public-release timestamp recovered from a preserved distribution feed and corroborated against both the issuer archive and SEC exhibit:

- `HEJFE-0BCEF81B6C0111FB` (COLM): `2015-04-30T16:00:00-04:00`. StreetInsider's historical COLM feed preserves `Columbia Sportswear Company Reports Record First Quarter` at `Apr. 30, 2015 04:00PM`. Columbia's issuer-hosted page identifies the matching release as `BUSINESS WIRE`, and SEC Exhibit 99.1 independently corroborates the same title, date, and content. This row is deliberately graded `B`, not `A`, because the literal clock is recovered from the preserved distribution mirror rather than the issuer-hosted page itself.

The other 145 events remain fail-closed until equivalent admissible evidence is located.

## Independently verified Business Wire batch 0028

One additional event now has an exact public-release timestamp recovered from a preserved Business Wire article and corroborated against the SEC-hosted issuer release:

- `HEJFE-4DEF5FDB3210E91B` (SWKS): `2015-01-22T16:15:00-05:00`. MarketScreener preserves `Skyworks Exceeds Q1 FY15 Revenue and EPS Guidance` as published Jan. 22, 2015 at 4:15 PM EST and labels it Business Wire. SEC Exhibit 99.1 independently reproduces the same release title/date/content and separately schedules the conference call for 5:00 PM Eastern, confirming the 4:15 PM clock is the publication time rather than the call time. This row is deliberately graded `B`, not `A`, because the exact clock is recovered from the preserved Business Wire mirror.

The other 144 events remain fail-closed until equivalent admissible evidence is located.
