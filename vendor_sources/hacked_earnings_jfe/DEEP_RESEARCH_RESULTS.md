# Hacked earnings: deeper extraction results

## Executive Summary

All six 2010–2015 press-release archives at source commit `c23c7d79d067a79d70cf20e31b072d3703497eae` have now been decoded and source-hash verified. The archives contain 36,750 text documents. Derived features retain all 43,687 sample rows and link source text to 160 of 174 first-trade records.

The published fitted Soft score is arithmetically reconstructable from 404 active word coefficients and a constant intercept. An intercept calibrated on one source row reproduces the other 36,749 scored rows within 1e-12. This is replication of an in-sample fitted score, not an out-of-sample return prediction.

The research package adds 560 auxiliary Actual=1 rows outside the core source-date join, 9,329 same-day control-candidate pairs, prior-text comparisons, and duplicate-content review tables. No canonical G1–G5 completion count, production model, or main-branch file is changed by this research branch.

## Corpus and coverage

| Metric | Verified result |
|---|---:|
| Source assets verified | 9 |
| Annual press-release archives decoded | 6 |
| Archived text documents | 36,750 |
| Unique raw text hashes | 36,711 |
| Sample security/date observations retained | 43,687 |
| Sample observations with text | 36,750 |
| Core first-trade records with text | 160 / 174 |
| Same-security preceding-text comparisons | 33,849 |
| Empty documents | 0 |
| Decoding replacement characters | 0 |

The archive manifests preserve source member names, hashes, text lengths, cleaned token counts, and fitted-word contributions. No competing appendices were observed for a security/date. Six nontext members are annual README files.

Each prior-text comparison uses the preceding archived date for the same PERMNO. Jaccard distance measures change in the set of the first 400 cleaned/stemmed words. This is descriptive language-change research, not an established financial signal. Archive dates do not prove exact public availability.

## Reconstructing the source model

`reconstructed_source_Soft = 0.0066078727193060755 + sum(stem_count * published_coefficient)`

The source vocabulary has 2,393 entries: 404 nonzero coefficients, comprising 183 positive and 221 negative, plus 1,989 zeros. The recipe lowercases text, extracts alphabetic tokens, removes the recorded English stopwords, applies Porter stemming, retains the first 400 resulting words, and counts vocabulary terms. Single-character terms do not contribute.

The intercept was calibrated on MERX, PERMNO 80553, January 4, 2010. The remaining 36,749 scored rows were checked separately. All 36,750 scores reconstruct within 1e-12; maximum absolute discrepancy is `9.71445146547012e-17`.

`recovered_soft_model.json` contains all 404 active coefficients, preprocessing metadata, and the derived intercept. The original per-document contribution column remains explicitly without intercept; it is not an imputed missing Soft score.

The published script fits and scores the same sample. Arithmetic reproduction must not be presented as held-out return validation. The full-sample coefficients and announcement text also must not be treated as preannouncement, point-in-time predictors.

## Duplicate texts need grouped evaluation

There are 39 identical-content pairs covering 78 security/date rows. Thirty-seven pairs share one GVKEY; two span different GVKEYs:

- MBFI / TAYC on July 15, 2013.
- KLAC / LRCX on October 21, 2015.

These are review flags, not proof of corrupted attribution. Shared or joint announcements are possible. Identical text must not be counted as independent material across training and evaluation partitions. The exported review tables mark these groups to stay together.

## Broader retrospective labels and control candidates

The 724 Actual=1 source rows include 164 represented in the 174-record source-date join. The remaining 560 auxiliary rows span 365 PERMNOs; 469 have text. They do not have newly recovered exact first-trade clocks.

Actual is a retrospective source label referring to earnings cited in the SEC complaint. Actual=0 is not proof that no trading occurred. Hacked and Actual are research-group labels, not real-time features.

All 174 core records have at least one same-day candidate with a different PERMNO and source Hacked=0/Actual=0. The screen yields 9,329 event/candidate pairs, 3,568 distinct candidate security/dates, and 1,678 candidate securities. Median pool size is 41, with a range of 1–203; two events have fewer than three candidates.

These are candidate pools, not accepted G5 matches. They have not passed size, liquidity, sector, earnings-time, historical-behavior, or point-in-time identity matching. Soft and current release text are not used to select the candidates.

## Initial descriptive comparison

| Source group | Rows | Scored rows | Mean Soft | Mean absolute Soft |
|---|---:|---:|---:|---:|
| Hacked=0 / Actual=0 | 34,707 | 29,311 | 0.000828 | 0.008987 |
| Hacked=1 / Actual=0 | 8,256 | 6,820 | 0.001078 | 0.008844 |
| Hacked=1 / Actual=1 | 724 | 619 | 0.001566 | 0.008809 |

The documented-trading group is more positive in average fitted Soft, but not larger in average absolute Soft. This unadjusted cut does not establish an extreme-score detection rule. It does not estimate a causal effect, excess return, unseen-sample accuracy, or trading profitability. Year composition, repeated issuers, missingness, and full-sample fitting remain important limitations.

## Boundaries and next work

All 6,937 missing Soft values coincide with missing archived text. None of the 14 missing-text core events was closed. The ten source-label exceptions remain unchanged. Another authorized public source is needed for those documents.

The first-trade-to-earnings link is the earliest same-PERMNO source date zero to three calendar days after first trade. It remains a source-date heuristic and does not replace canonical G1 announcement timestamps or identity evidence.

No raw TAQ, OPRA, ITCH, proprietary return panel, or market-data coverage was recovered. Recommended next work is to join verified publication clocks and genuine realized outcomes, use earlier-only training with grouped validation, route control candidates through existing G5 acceptance rules, and use the auxiliary labels only for explicitly retrospective robustness checks.

## Reproducibility and execution evidence

- Extraction script: `scripts/hacked_earnings_deep_research.py`.
- Supplemental validation: `scripts/hacked_earnings_deep_analysis.py`.
- Tables/model/findings: `data/processed/hacked_earnings_deep/`.
- Source: `vgreg/hacked_earnings_jfe@c23c7d79d067a79d70cf20e31b072d3703497eae`.
- Extraction and validation workflow run `37411005904` succeeded on code commit `d59e529fbd1729c77f13c3964cad2d460a7a979f`.
- Eight parser/research safeguard tests passed; thirteen upstream output hashes verified before supplemental analysis.
- These checks validate this isolated research pipeline, not the entire production release test suite. Main integration and release registration are not claimed.

## Source license notice

MIT License

Copyright (c) 2021 Vincent Grégoire

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
