# LSEG G2 repository extraction

This package contains repository-extracted information needed to drive the frozen G2 historical market-data acquisition through LSEG Tick History / DataScope Select.

## Extracted assets

- `data/processed/g2_vendor_requests/lseg_event_permno_ric_mapping.csv`
  - Joins the exact 174-event `TimeOfFirstTrade.csv` to the companion study's PERMNO→RIC mapping.
  - 111 of the 146 historical symbols have direct study-linked RIC candidates by PERMNO.
- `data/processed/g2_vendor_requests/lseg_equity_ric_mapping.csv`
  - Companion-study symbol/root candidates for all 146 frozen G2 symbols.
  - One additional symbol, `MUSA`, has a companion root match but no event-PERMNO link.
- `data/processed/g2_vendor_requests/lseg_secondary_ric_candidates.csv`
  - 34 additional repository-backed RIC candidates.
  - These require date-specific historical-instrument validation before use as evidence.
- `data/processed/g2_vendor_requests/lseg_tick_history_contract.json`
  - Tick History Time & Sales report type and exact equity/option trade+quote fields.
- `data/processed/g2_vendor_requests/lseg_option_discovery_recipe.json`
  - Sanitized FuturesAndOptionsSearch and HistoricalChainResolution recipes.
- `src/g2_lseg_request_manifest.py`
  - Converts the frozen G2 requirements into exact equity requests and option-underlying discovery requests.
- `tests/test_g2_lseg_request_manifest.py`
  - Locks the extracted plan to the current frozen G2 scope.

## Evidence tiers

Across the 146 G2 historical symbols:

- **111** — direct event-PERMNO → companion-study RIC candidates.
- **1** — companion-study root-only candidate: `MUSA`.
- **34** — secondary repository-backed RIC candidates requiring historical-date validation.
- **0** — without a repository-backed candidate.

For each of the equity and option-underlying lanes (7,656 symbol-kind/date requests):

- **5,764** use event-PERMNO-linked candidates.
- **88** use the MUSA root-only candidate.
- **1,804** use secondary repository candidates and require historical identifier validation.
- **0** are unmapped.

## Important distinction

The examined GitHub repositories contain query logic, identifier metadata, parsing rules, research mappings, and option discovery patterns. They do **not** contain the licensed 2011–2015 LSEG tick payload itself.

Actual G2 coverage changes only after licensed LSEG rows are retrieved and pass the repository's existing content validators. Root-only and secondary RIC candidates must first be confirmed as valid for the relevant historical date.

No credentials, passwords, or sample tokens are stored in this package.

## Original research TRTH processing rules

Charles Martineau's public fork of the companion research repository contains the original Python processing scripts used for TRTH trades and quotes. Their reusable rules are extracted into:

- `data/processed/g2_vendor_requests/lseg_original_research_processing_contract.json`

That contract records the raw TAS file structure, MD5 sidecar validation, exact trade/quote fields, historical timestamp reconstruction, trade/quote qualifier handling, relevant 2011–2015 early-close dates, and per-event filtering rules. Machine-specific drive paths and any credentials/token-like values are intentionally excluded.

This strengthens the LSEG route from a generic API plan to the actual processing logic used in the source research workflow. It still does not constitute G2 coverage until licensed rows are retrieved and validated.
