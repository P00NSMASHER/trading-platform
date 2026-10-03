# hacked_earnings_jfe source audit

Source: `vgreg/hacked_earnings_jfe` at `c23c7d79d067a79d70cf20e31b072d3703497eae` (MIT-licensed repository code/data package).

This directory records everything recoverable from the repository that is useful to the historical-event / G2 acquisition program without pretending the repository contains proprietary vendor payloads that are not actually present.

## Repository payload inventory

The source tree has **28 entries** and the recursive tree response is **not truncated**. It includes:

- `Data/SampleFirms.{csv,dta,parquet,xlsx}`
- `Data/TimeOfFirstTrade.{csv,dta,parquet,xlsx}`
- six SEC press-release ZIP archives for 2010–2015 plus their README
- two main-analysis notebooks
- two text-analysis Python scripts, one word-cloud notebook, and one fitted word-weight parquet
- repository README and MIT license

The README documents use of CRSP, I/B/E/S, TAQ, RavenPack, Markit, OptionMetrics, Thomson Reuters 13-F, Nasdaq ITCH, CBOE intraday options, and SEC EDGAR press releases. Those references are source/provenance clues; they are **not evidence that the raw licensed vendor datasets are committed in this repository**.

The notebooks explicitly load omitted proprietary HDF files:
- `../Proprietary Data (cannot be shared)/MainPanel.h5`
- `../Proprietary Data (cannot be shared)/BSI_Summaries_EA_merged.h5`

## Fully extracted public tables

### SampleFirms

Columns: `PERMNO, GVKEY, SYMBOL, date, Hacked, Actual, Soft`.

- rows: **43,687**
- date range: **2010-01-04 → 2015-12-23**
- unique PERMNOs: **3,202**
- unique symbols: **3,303**
- Hacked=1 rows: **8,980**
- Actual=1 rows: **724**
- non-empty Soft scores: **36,750**

Per the source README, `Hacked` marks exposure to a hack, `Actual` marks earnings mentioned in the SEC complaint as evidence of actual hacker trading, and `Soft` is the press-release-text model's predicted announcement-return score.

### TimeOfFirstTrade

- rows: **174**
- unique PERMNOs: **146**
- fields: `PERMNO, SYMBOL, GVKEY, TimeOfFirstTrade`

## 174-event reconciliation

Every one of the 174 first-trade records maps to the earliest `SampleFirms` observation for the same PERMNO on or after that trade date, and **174/174 are within 0–3 calendar days**:

- same date: **133**
- +1 day: **39**
- +3 days: **2**

The joined row contributes a `Soft` score for **160/174** events. The source table's own `Hacked` and `Actual` flags equal 1 for **164/174** reconciled rows; ten rows differ and are preserved as source-data exceptions rather than silently rewritten.

See:
- `data/processed/g2_vendor_requests/hacked_earnings_jfe_event_reconciliation.csv`
- `data/processed/g2_vendor_requests/hacked_earnings_jfe_source_summary.json`

## What is still not in this repository

The source package does **not** contain the raw 2011–2015 TAQ trade/quote payload, raw Nasdaq ITCH event files, raw CBOE options trades/quotes, raw I/B/E/S announcement-time feed, RavenPack feed, OptionMetrics feed, Markit feed, or Thomson Reuters 13-F feed. It contains derived analysis, public labels/scores, SEC press-release archives, and source/processing references.

No credentials, secrets, tokens, or vendor-auth material are copied by this audit.
