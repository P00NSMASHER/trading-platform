# hacked_earnings_jfe extraction audit

Audited source: `vgreg/hacked_earnings_jfe` @ `c23c7d79d067a79d70cf20e31b072d3703497eae` on 2026-10-03.

## What is now preserved

- Full `Data/SampleFirms.csv`: 43,687 earnings observations, 3,202 unique PERMNOs, 3,303 historical symbols, spanning 2010-01-04 through 2015-12-23.
- `Hacked=1`: 8,980 observations across 2,274 PERMNOs.
- `Actual=1`: 724 observations across 457 PERMNOs.
- `Soft`: 36,750 non-missing press-release ML scores; 6937 rows do not have a score.
- `TimeOfFirstTrade`: 174 documented first-trade timestamps across 146 PERMNOs.
- Embedded notebook outputs and notebook-referenced schema/formulas are extracted to text/JSON for searchability.

## 174-event enrichment

The 174 first-trade events were joined to the nearest `SampleFirms` earnings observation on or after the first-trade date for the same PERMNO. This is an enrichment, not a replacement of the SEC-complaint-derived first-trade label.

- Nearest row has `Actual=1`: 164/174.
- Nearest row is on the same calendar date: 133/174.
- Same-day and `Actual=1`: 126/174.
- Join-quality distribution: `{"HIGH_NEAREST_ACTUAL_0_1D":162,"SOURCE_LABEL_CONFLICT_NEAREST_NONACTUAL":10,"NEAREST_ACTUAL_GT1D":2}`.
- 10 rows conflict with the broader `SampleFirms` labels and are explicitly marked `SOURCE_LABEL_CONFLICT_NEAREST_NONACTUAL`; they are not silently coerced.

Conflicting symbols: ALSN, DE, F, CMTL, MKC, PNRA, NATI, NATI, PAY, DGI.

## Additional source information recovered

The source README identifies the study's upstream data stack: CRSP, I/B/E/S, TAQ, RavenPack, Markit, OptionMetrics, Thomson Reuters 13-F, Nasdaq ITCH, CBOE intraday options, and SEC EDGAR earnings press releases.

The public text-analysis code shows the `Soft` score pipeline: press-release text is lowercased/tokenized, English stop words are removed, Porter stemming is applied, the first 400 words are vectorized with `min_df=0.005` and `max_df=0.4`, and an ElasticNetCV model (`cv=5`, `l1_ratio=0.5`, `max_iter=10000`) predicts `LRet_12pm_OpenNext`.

The Wordcloud notebook reports 2,393 word/coefficient rows. Visible extremes embedded in the notebook include negative `disappoint=-0.027961` and positive `rais=0.006816`.

## Reproducibility note

The source README says packages are listed in `requirements.txt`, but the recursively enumerated 24-file tree contains no `requirements.txt`, and the visible three-commit history does not add one. Dependency reconstruction must therefore come from notebook/script imports rather than a source requirements file.

## History audit

Only branch `main` exists. Three commits are visible; the data/code appear in commit `558ffddc9b4ae5b2327fcbc6cf369c3b76631517`, while the latest commit only adds DOI metadata to README. No separate branch or deleted historical TAQ/CBOE payload was found in the visible repository history.

## Binary asset status

The small binary word-coefficient Parquet is now preserved losslessly on this branch as Base64 at:

`data/raw/hacked_earnings_jfe/source_snapshot/Text Analysis/PR_fit_EN_0_5_text_clean_stemmed_400_Count_0_005_0_4_WORDS.parquet.b64`

Its source blob SHA is `72d66171f5eb28cd3ec629f13b0b1d15219cbf96`. The GitHub connector successfully returned the 40 KB Parquet via Base64, so the prior blanket non-UTF-8 limitation no longer applies to this asset. The full 2,393 coefficient rows have not yet been decoded into a tabular derivative in this runtime.

The six yearly press-release ZIP archives remain the only unique source content not copied or unpacked. Each is approximately 26–28 MB; the connected GitHub Contents path returns empty content for these large binary objects, while the UTF-8 fetch path rejects ZIP bytes. Their exact paths, sizes, and source blob SHAs remain preserved in `source_inventory.json`.

All readable UTF-8 source artifacts (README/license, press-release README, both analysis notebooks, both text-analysis scripts, and Wordcloud notebook) are now snapshotted under `data/raw/hacked_earnings_jfe/source_snapshot/`.

### Remaining extraction target

When a raw-binary path is available, download the six ZIPs, verify their hashes against the source inventory, enumerate every member, and extract the press-release corpus. Prioritize matching files to the 174 first-trade events, then preserve the full corpus and derive a searchable event-to-release index.
