# Exhaustive audit: vgreg/hacked_earnings_jfe

Audit date: 2026-10-06

## Pinned source

- Repository: `vgreg/hacked_earnings_jfe`
- Exact source commit: `c23c7d79d067a79d70cf20e31b072d3703497eae`
- Source tree: `2ef2bcd078227f19cae56344eccc8bf7a3eaec79`
- Final audit implementation head: `8430e5a08878b64677ba6686b9d0c44d0801529e`
- Successful final workflow run: `37417646444`
- Final artifact: `hacked-earnings-jfe-exhaustive-audit`
- Final artifact id: `11392221993`
- Final artifact digest: `sha256:bd80268e79a3da8a51b25fd9266677d4ef9e6072b5144d4a480cdf825dc908e8`

## Coverage contract

This audit deliberately goes beyond listing files or CRC-checking ZIPs.

- 24 current tracked files were read byte-for-byte.
- 172,469,455 current tracked bytes were read and independently hashed.
- The complete reachable Git graph was enumerated: 3 commits, 35 reachable objects, 25 unique blobs.
- Every reachable Git object byte was read and its Git object hash was independently recomputed.
- 12 reachable text blobs, including the superseded README version, were semantically scanned.
- There are no historical-only/deleted paths in the reachable history.
- All six press-release ZIP archives were opened.
- Every ZIP member was explicitly decompressed and read, not merely CRC-tested.
- 36,756 ZIP members were read: 36,750 release texts plus six README files.
- 615,195,162 decompressed bytes/characters were scanned.
- Full decoded archive corpus SHA-256: `4d1831ca2ca9c54218fd14b04a6f3ea16fc1267d687f0341a0a960fd7087e407`.
- CSV, Stata, Parquet, and XLSX copies of both published tabular datasets were decoded and compared cell-by-cell after canonical date normalization.
- Both XLSX workbooks were inspected internally, including their XML package members, hidden-sheet state, formulas, comments, hyperlinks, defined names, and external links.
- Both Stata files were decoded and their data labels, variable labels, value labels, and file timestamps were inspected.
- All Parquet rows, columns, cells, schemas, row groups, and key/value metadata were decoded.
- All three notebooks were parsed as JSON, including source, markdown, metadata, text/HTML outputs, and embedded binary outputs.
- Nine embedded PNG notebook outputs were decoded, hashed, preserved as audit evidence, and visually inspected.
- The single GitHub release (`v1.0`, "Initial release") was checked; it has no attached release assets.
- All four public forks found during the audit point their main branch to the same exact source commit.

## Structured-data result

After canonical timestamp/date normalization, the alternate formats contain no extra data:

| Dataset | DTA vs CSV mismatched cells | Parquet vs CSV | XLSX vs CSV |
|---|---:|---:|---:|
| SampleFirms | 0 | 0 | 0 |
| TimeOfFirstTrade | 0 | 0 | 0 |

Additional format checks:

- `SampleFirms.xlsx`: one visible sheet, zero formulas, comments, hyperlinks, defined names, hidden sheets, or external links.
- `TimeOfFirstTrade.xlsx`: one visible sheet, zero formulas, comments, hyperlinks, defined names, hidden sheets, or external links.
- Both Stata files have empty data labels/value labels/variable labels; their file timestamp is `14 Dec 2021 22:11`.
- The coefficient Parquet has 2,393 rows and three stored fields: `word`, `coef`, and the pandas index field `__index_level_0__`. No additional research variable is hidden in that file.

## Press-release corpus

Archive release counts:

- 2010: 6,507
- 2011: 6,484
- 2012: 6,018
- 2013: 6,175
- 2014: 5,755
- 2015: 5,811
- Total release texts: 36,750
- Plus one README per yearly archive: 6

Every release filename parses under the repository's documented PERMNO/date/internal-id convention. There are 36,750 unique PERMNO-date pairs and no empty release texts.

Exact-content duplicate audit:

- 39 duplicate-content groups
- 78 release files involved
- none of the 160 event-matched releases is in an exact-content duplicate group

For the 174 documented first-trade events:

- 160 have exactly one matching archived press release
- 14 have none
- zero events have multiple matching release candidates

The 14 without archived release members are: MXIM, ECOL, P, CAMP, ROL, MAT, RES, KOPN, GDI, ROVI, AMSG, JNPR (2013-07-23 event), STMP, and VDSI.

Critically, the entire 615 MB decompressed press-release corpus contains:

- zero clock-time tokens matching the audit's broad clock-time grammar
- zero SEC `ACCEPTANCE-DATETIME` tokens
- zero such timing tokens in the 160 event-matched releases

Therefore the release archive cannot supply the missing exact announcement/filing timestamps for G1/G2. The archive is useful for text/content features, not as a hidden timestamp source.

## Notebook/code findings

The repository explicitly references proprietary inputs that are not present:

- `../Proprietary Data (cannot be shared)/MainPanel.h5` / `MainPanel.hdf`
- `../Proprietary Data (cannot be shared)/BSI_Summaries_EA_merged.h5`

The README also says a `requirements.txt` is supplied, but no such tracked file exists in the current tree or reachable history.

The committed `Text Analysis/pr sentiment.py` is not directly runnable as-is: its top-level load references `text_col` before definition and the demonstrated call passes `text_col` as a list while the function treats it as a column selector. The published coefficient artifact should therefore be treated as authoritative evidence, not a guarantee that the script reproduces it without repair.

The supplied text model contains 2,393 coefficients. Previously decoded extremes remain:

- most negative: `disappoint` = -0.027960599263064642
- most positive: `rais` = 0.006815500110691692

Visual inspection of the two word-cloud outputs is consistent with those extremes.

The seven embedded analytical figures in `Main Analysis.ipynb` contain graphical versions of the notebook's descriptive and quantile analyses; no additional hidden table/data payload was found in those images.

## Source boundary

The public repository does **not** contain raw licensed TAQ trades/quotes, Nasdaq order data, CBOE option transactions, I/B/E/S raw files, RavenPack raw files, Markit, OptionMetrics, or 13-F raw payloads. It contains code, labels, first-trade timestamps, SEC press-release text, published outputs, and the text-model coefficients.

This is a source-boundary finding, not an unexamined gap.

## External leads discovered from repository text

These are linked dependencies, not files inside `hacked_earnings_jfe`:

1. `vgreg/earnings_news_jar` is explicitly identified as the I/B/E/S + RavenPack processing codebase. A quick trace confirms it also contains public TRTH quote/trade extraction and trade-classification scripts. It was not already indexed by the current trading-platform code search and merits its own hunter audit.
2. The README says TAQ processing used the Holden/Jacobsen sample SAS code plus custom Compute Canada Python scripts. The sample-code reference is public; the custom Python scripts are not included here.

## Reproducible implementation

The audit implementation lives on branch `audit/hacked-earnings-jfe-every-byte-20261006`:

- `scripts/audit_hacked_earnings_jfe_exhaustive.py`
- `.github/workflows/hacked-earnings-exhaustive-audit.yml`

The final workflow preserves manifests for source files, Git history, structured-format inspection, all archive members, the 160 event-linked release scans, and extracted notebook PNG outputs.
