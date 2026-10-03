# LSEG G2 repository extraction

This package contains repository-extracted information needed to drive the frozen G2 historical market-data acquisition through LSEG Tick History / DataScope Select.

## Extracted assets

- `data/processed/g2_vendor_requests/lseg_equity_ric_mapping.csv`
  - 146 frozen G2 historical symbols.
  - 112 exact-root candidate RIC mappings from the exact companion-study repository.
- `data/processed/g2_vendor_requests/lseg_secondary_ric_candidates.csv`
  - 34 additional repository-backed RIC candidates.
  - These require date-specific historical-instrument validation before use as evidence.
- `data/processed/g2_vendor_requests/lseg_tick_history_contract.json`
  - Tick History Time & Sales report type and exact equity/option trade+quote fields extracted from an open-source DataScope client.
- `data/processed/g2_vendor_requests/lseg_option_discovery_recipe.json`
  - Sanitized FuturesAndOptionsSearch and HistoricalChainResolution recipes.
- `src/g2_lseg_request_manifest.py`
  - Converts the frozen G2 requirements into exact equity requests and option-underlying discovery requests.
- `tests/test_g2_lseg_request_manifest.py`
  - Locks the extracted plan to the current frozen G2 scope.

## Current repository-extracted coverage plan

- 146 / 146 G2 historical symbols now have at least one repository-backed RIC candidate.
- 112 are primary exact companion-study matches.
- 34 are secondary repository candidates and must be validated against the historical date before production use.
- The frozen equity lane contains 7,656 symbol-kind/date requests:
  - 5,852 primary candidate requests.
  - 1,804 secondary-candidate requests.
- The option-underlying lane has the same 7,656 split before contract enumeration.

## Important distinction

The examined GitHub repositories contain query logic, identifier metadata, parsing rules, research mappings, and option discovery patterns. They do not contain the licensed 2011-2015 LSEG tick payload itself.

Actual G2 coverage changes only after licensed LSEG rows are retrieved and pass the repository's existing content validators. Secondary RIC candidates must first be confirmed as valid for the relevant historical date.

No credentials, passwords, or sample tokens are stored in this package.
