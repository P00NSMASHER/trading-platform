# Licensed data acquisition map

The user has stated they hold the required licenses. This document records the provider delivery paths and the exact repository scope to retrieve. Credentials are never stored in Git.

## NYSE Daily TAQ — core equity trades and quotes

Repository requirement: **828 source-date rows** across **414 market dates** (trade + quote for each date), spanning 2011-03-21 through 2015-05-20.

NYSE states Daily TAQ historical data are available back to 1993. Recent files use NYSE Managed File Transfer; earlier historical files are accessed through the NYSE FTP/SFTP entitlement. The production audit supports split/sharded files for one date, including NYSE quote files split across multiple files.

Public product page:
- https://www.nyse.com/data-products/catalog/daily-taq

Current MFT entry point:
- https://mftus.nyx.com

Expected data classification in the local source contract:
- `authorized_historical_market_data`
- explicit nonblank `license_reference`

## Cboe/OPRA historical options

Repository requirement: **828 source-date rows** across the same 414 market dates:
- Option Trades
- Option Quotes

Product pages:
- https://datashop.cboe.com/option-trades
- https://datashop.cboe.com/option-quote-intervals

Cboe's FAQ lists Option Trades and Option Quotes availability from January 2010, which covers the 2011-2015 research window. Some current individual product-page text advertises a later start date, so 2011 entitlements may require the legacy historical-order path or DataShop support rather than the default current UI.

FAQ:
- https://datashop.cboe.com/faqs

The importer can accept Cboe-native files or another lawfully licensed provider mapped through `generic_authorized_market_data`.

## Nasdaq Historical TotalView-ITCH

G3 proves **80 Nasdaq events** require event-level ITCH order-flow coverage.

Version split frozen from the event dates:
- **35 events — ITCH 4.1** (before 2014-04-08)
- **45 events — ITCH 5.0** (2014-04-08 onward)

Nasdaq's historical SFTP documentation lists:
- host: `itchdata.nasdaq.com`
- ITCH 4.1 archive coverage back to May 2010
- ITCH 5.0 coverage beginning April 8, 2014

The importer accepts both:
- `nasdaq_itch_4_1_decoded`
- `nasdaq_itch_5_0_decoded`

Raw binary must be decoded under the authorized entitlement before entering the canonical importer; the exact format version is retained in the source contract.

## LSEG I/B/E/S exact announcement times

G1 exact-timing analysis requires **174 exact first-public clocks**.

Target fields:
- `ANNDATS_ACT`
- `ANNTIMS_ACT`

WRDS exposes LSEG I/B/E/S Historical Estimates / Detail History with Actuals to entitled institutions, and LSEG I/B/E/S Actuals is designed for point-in-time earnings analysis. The existing repository adapter is ready to ingest the authorized extract.

WRDS product/demo entry points:
- https://wrds-www.wharton.upenn.edu/pages/about/data-vendors/lseg/
- https://wrds-www.wharton.upenn.edu/demo/ibes/form/

LSEG product:
- https://www.lseg.com/en/data-catalogue/company-data/ibes-estimates/actuals

## G5 point-in-time controls

G5 model-evaluation controls require at least three genuine candidates per one of the 72 event dates, with complete pre-event covariates. The existing retrospective SampleFirms package is not promoted to point-in-time evidence.

Once licensed TAQ/options/I/B/E/S and the user's licensed CRSP/Compustat/ownership data are staged, the control builder should derive the required point-in-time covariates and replace the 72 fail-closed exclusions.

## Local staging policy

Recommended private staging root (not committed):

`data/private/licensed/`

Suggested subdirectories:

- `taq/`
- `options/trades/`
- `options/quotes/`
- `itch/v41/`
- `itch/v50/`
- `ibes/`
- `controls/`

The acquisition process must preserve original vendor filenames and produce SHA-256 receipts before any transformation.

## October 2, 2026 G2 vendor-reply evidence

Machine-readable evidence is recorded at:

`data/processed/g2_vendor_requests/vendor_reply_evidence_2026-10-02.json`

Cboe Data Vantage (Dorraine Burrell, Director, Data Vantage Sales) confirmed that historical tick data is offered only for the full OPRA universe, not only the requested 137 historical underlyings. Rough pricing was **$40,000 for 2 years 5 months** and **$24,000 for one calendar year**; the requested **309 selected trading days across several years** would be a custom job and could cost more. The paid bulk route is therefore **out of scope for the current research** and must not be purchased or treated as G2 coverage.

Tick Data did not provide written availability or pricing for the requested 2011–2015 OPRA tick-level scope. After the requester explicitly stated that a mandatory phone call would make the written quote unavailable, Tick Data again required a phone call. Record this route as **unpriced / written-quote unavailable**; do not infer availability from the exchange and do not count any coverage.

The Cboe zero-cost historical acceptance probe from PR #258 is logically separate from the paid bulk quote. PR #258 was merged on October 2, 2026; the probe remains dry-run by default and cannot authorize a purchase, subscription, or coverage-count change. Only actual validated historical rows can change G2 coverage.

