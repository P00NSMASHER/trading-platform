# LSEG G2 repository extraction

This package contains repository-extracted information needed to drive the frozen G2 historical market-data acquisition through LSEG Tick History / DataScope Select.

## Extracted assets

- `data/processed/g2_vendor_requests/lseg_equity_ric_mapping.csv`
  - 146 frozen G2 historical symbols.
  - 112 have an exact-root candidate RIC from the companion research repository.
  - 34 remain unresolved and must be resolved from historical-instrument metadata before counting coverage.
- `data/processed/g2_vendor_requests/lseg_tick_history_contract.json`
  - Time & Sales report type and exact equity/option trade+quote fields extracted from the open-source DataScope client.
- `data/processed/g2_vendor_requests/lseg_option_discovery_recipe.json`
  - Sanitized FuturesAndOptionsSearch and HistoricalChainResolution recipes.
- `src/g2_lseg_request_manifest.py`
  - Converts the frozen G2 requirements into exact equity requests, option-underlying discovery requests, and unresolved rows.
- `tests/test_g2_lseg_request_manifest.py`
  - Locks the extracted plan to the current frozen G2 scope.

## Important distinction

The examined GitHub repositories contain query logic, identifier metadata, parsing rules, and research mappings. They do not contain the licensed 2011-2015 LSEG tick payload itself. Actual G2 coverage changes only after licensed rows are retrieved and pass the repository's existing content validators.

No credentials, passwords, or sample tokens are stored in this package.
