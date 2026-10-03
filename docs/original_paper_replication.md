# Original-paper replication target

This project must reproduce the published 2022 JFE paper **Price Revelation from Insider Trading: Evidence from Hacked Earnings News**, rather than substitute convenient modern data sources.

## Canonical sample

The final published sample contains **43,687 earnings announcements**, including **8,980 announcements exposed to hacked newswires**, from January 2010 through December 2015.

The existing 174 prosecuted events and frozen G2 manifests are valuable for case-study validation, but they are **not the full paper sample** and cannot by themselves reproduce the main regressions.

## Canonical licensed source stack

For a paper-faithful rebuild, verify access to:

1. **CRSP US Stock**
2. **S&P Compustat North America + CRSP/Compustat Merged (CCM)**
3. **LSEG/Refinitiv I/B/E/S Historical Estimates (Global / historical detail)**
4. **RavenPack RPNA 4.0 legacy Press Release + Dow Jones editions** (or a current entitlement that contractually exposes the same historical raw records)
5. **NYSE TAQ Monthly for 2010–2013**
6. **NYSE TAQ Daily for 2014–2015**
7. **OptionMetrics IvyDB US**
8. **Thomson Reuters Institutional Managers (13f) Holdings**
9. **Markit/S&P Global Securities Finance – Analytics – Equity – America**
10. **Cboe/LiveVol historical Option Trades including legacy 2010–2011 data**
11. **NASDAQ Historical TotalView-ITCH archive (4.1 and 5.0)** for the paper's ITCH case-study validation.

Public SEC/DOJ records and the public press-release/reproduction repositories do not require a paid market-data entitlement.

## Fidelity rules

- Do **not** replace TAQ with LSEG Tick History for Table 6.
- Do **not** replace Cboe option transactions with LSEG if the objective is exact paper replication.
- LSEG Tick History remains valuable for identifier resolution, companion JAR/TRTH reconstruction, and independent validation.
- WRDS precomputed intraday indicators may be used as a formula/QA cross-check, but not as a silent substitute for the authors' Holden–Jacobsen + custom Python TAQ processing.
- Do not invent missing treatment dates, RavenPack relevance thresholds, or proprietary intermediate fields.

## Table 6 timing nuance

The paper describes the morning order-flow window as **09:30–12:00** and afternoon as **12:00–16:00**, but footnote 16 states the **spread measures start at 09:45** to avoid the opening-spread spike. Figure 7 also uses 09:45–12:00 for the morning spread distributions.

## Unpublished intermediates

The public notebooks load two proprietary files that were not found in public Git history:

- `MainPanel.h5`
- `BSI_Summaries_EA_merged.h5`

Exact reproduction therefore requires rebuilding these from the canonical licensed sources and the recovered public preprocessing code. The machine-readable source-to-output plan is in:

`data/processed/real_data_release_sprint/original_paper_replication_matrix.json`
