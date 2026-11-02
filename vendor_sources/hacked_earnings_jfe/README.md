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


## Deeper extraction findings

### Repository history and forks

The source repository has three commits total:

- `16104a8dcda6e145178fd58d2fa50afa15537ad2` — initial root
- `558ffddc9b4ae5b2327fcbc6cf369c3b76631517` — initial published payload
- `c23c7d79d067a79d70cf20e31b072d3703497eae` — DOI README update / current HEAD

A recursive tree comparison across all three commits found **no historical-only paths**: nothing was deleted or renamed out of the published payload after it appeared.

Four public forks found during this audit (`ollie0317`, `chaozhoucn`, `liuxiaoqun`, and `baridhi`) all point their `main` branch at the exact same source HEAD SHA `c23c7d79d067a79d70cf20e31b072d3703497eae`. They do not expose a divergent copy of omitted proprietary data.

### Text-model pipeline

The repository scripts establish the reproducible soft-information pipeline:

- lowercase alphabetic tokenization with regexp `[a-z]+`
- NLTK English stopword removal
- Porter stemming
- first **400 words** retained per press release
- `CountVectorizer` with document-frequency ratios **0.005 minimum / 0.4 maximum**
- `ElasticNetCV` with **5-fold CV**, `l1_ratio=0.5`, `max_iter=10000`
- dependent variable: `LRet_12pm_OpenNext`
- fitted word table contains **2,393 vocabulary rows**

The committed Wordcloud notebook exposes coefficient extremes from that fitted table. The most negative displayed coefficient is stem `disappoint` (-0.027961); the most positive displayed coefficient is stem `rais` (+0.006816). The exact notebook output and model settings are preserved in `data/processed/g2_vendor_requests/hacked_earnings_jfe_notebook_extraction.json`.

### Recoverable notebook results

The committed notebooks contain plaintext outputs for published descriptive and regression tables even though their proprietary HDF inputs are omitted. Those outputs have been extracted verbatim, with their generating cell source, into the notebook-extraction JSON.

Notable descriptive values recovered from `Main Analysis.ipynb` include:

- 43,687 observations for Surprise, absolute Surprise, log market cap, institutional ownership, analyst count, share turnover, and option turnover
- 35,273 observations for log Q-value
- 36,750 observations with the `Soft` score
- mean Surprise 0.0004; median 0.0006
- mean institutional ownership 68.37; median 77.53
- mean share turnover 1.99; median 1.46
- mean option turnover 0.20; median 0.04

The insider-trading-measures notebook also preserves full plaintext regression tables for PM versus AM order-flow/spread measures and their differences.

### 174-event derived analytics

The event reconciliation supports further source-derived analytics, stored in `hacked_earnings_jfe_event_analytics.json`:

- first-trade years: 2011=15, 2012=23, 2013=37, 2014=2, 2015=97
- first-trade clock range: 10:14–15:59; median 15:19; mean approximately 15:01
- 109/174 first trades occur at or after 15:00; 68/174 at or after 15:30
- 160/174 mapped events have a non-empty `Soft` score
- among those 160: 105 positive and 55 negative; mean 0.0026134; median 0.0033403
- maximum mapped `Soft`: CAT, +0.0347990
- minimum mapped `Soft`: DNDN, -0.0325529
- the exact 14 missing-soft events and 10 source-label exceptions are recorded explicitly

### Remaining binary archive boundary

Six ZIP files contain the SEC-derived press-release text corpus:

- 2010.zip — 27,346,855 bytes
- 2011.zip — 28,136,902 bytes
- 2012.zip — 26,908,193 bytes
- 2013.zip — 28,229,369 bytes
- 2014.zip — 26,563,716 bytes
- 2015.zip — 27,696,531 bytes

Their source README states that internal text files follow `PERMNO_YYYYMMDD_X.txt`, where PERMNO is the CRSP identifier, YYYYMMDD is the earnings date, and X disambiguates multiple quarterly-report appendices. The current GitHub connector can inventory these binary archives but does not expose their compressed contents as UTF-8 text, so no claim is made here that every internal text member has been enumerated. The public CSV/Notebook-derived information above is fully extracted from the connector-visible payload.


### Direct reproducibility dependency: earnings_news_jar

The source README explicitly says its I/B/E/S and RavenPack processing reused `vgreg/earnings_news_jar`. That linked repository adds concrete reproducibility clues:

- I/B/E/S active announcement timestamp is constructed as `ANNDATS_ACT + ANNTIMS_ACT` into `IBES_Timestamp`.
- The I/B/E/S processing notebook links `PERMNO` to I/B/E/S `TICKER` with effective start/end dates and retains fields including `FPEDATS`, `REVDATS`, `ANNDATS_ACT`, `ANNTIMS_ACT`, and `ACTUAL`.
- The RavenPack notebook is specifically described as retrieving earnings-announcement timestamps and analyst-recommendation-revision news.
- The companion repository contains a `PERMNO_TRHT _Ticker.csv` mapping from PERMNO to Thomson Reuters Tick History RIC and TRTH trade/quote extraction code.

Those companion-repository clues are provenance/processing contracts, not additional raw vendor rows. The current trading-platform LSEG extraction artifacts already operationalize the reusable PERMNO/RIC information separately.

### Published-source reproducibility caveats

The audit also found several internal reproducibility inconsistencies that should be preserved rather than silently repaired:

- The source README says the code was tested with Python 3.9.7 and packages listed in `requirements.txt`, but no `requirements.txt` exists in the current tree or any of the three repository commits.
- `Text Analysis/clean_pr_text.py` reads `../Proprietary Data (cannot be shared)/MainPanel.hdf`, while `Main Analysis/Main Analysis.ipynb` reads `../Proprietary Data (cannot be shared)/MainPanel.h5`; neither proprietary panel is committed.
- The committed `Text Analysis/pr sentiment.py` references `text_col` in its top-level parquet read before assigning it in the shown script, while the later fit call passes `["text_clean_stemmed"]`. Treat the file as a processing recipe unless its missing runtime context is restored.
- That same script's coefficient-output expression appends `_WORDS.parquet` to `out_fn[:-8]`, while the supplied `out_fn` already ends in `_WORDS.parquet`. The committed coefficient artifact therefore should be treated as authoritative evidence of the fitted result, not assumed to be byte-for-byte reproducible from the script exactly as published.

These caveats do not invalidate the public tables or notebook outputs extracted above; they define the boundary between recoverable evidence and missing execution environment/context.

### Broader public label universe

`SampleFirms` contains a broader labeled universe than the 174 rows with exact first-trade clocks. Its label cross-tab is:

- Hacked=0 / Actual=0: **34,707** rows; 29,311 have `Soft` (84.45%).
- Hacked=1 / Actual=0: **8,256** rows; 6,820 have `Soft` (82.61%).
- Hacked=1 / Actual=1: **724** rows; 619 have `Soft` (85.50%), covering 457 unique PERMNOs.
- There are **zero Hacked=0 / Actual=1 rows** in the public table, so `Actual=1` implies `Hacked=1` there.

The 724 `Actual=1` rows are useful as a broader auxiliary label set, but they must not be substituted for the 174 `TimeOfFirstTrade` events because they do not supply the exact first-trade clock. The public `SampleFirms` table has no Hacked=1 rows in 2014, while `TimeOfFirstTrade` has two 2014 events; both are among the ten preserved source-label exceptions. This is another reason to keep the two source tables distinct rather than forcing label agreement.
