# WRDS TAQ extraction path

This directory preserves and adapts the relevant extraction logic from `gen-li/Extract_TAQ_from_WRDS_Cloud` for the frozen G2 equity workflow.

## Included source references

- `WRDS_batch_ticker_ct.sas` — upstream legacy consolidated trades reference (`taq.ct_YYYYMMDD`).
- `WRDS_batch_ticker_cq.sas` — upstream legacy consolidated quotes reference (`taq.cq_YYYYMMDD`).
- `g2_wrds_taq_legacy.sas` — parameterized legacy extractor with no hard-coded user path.
- `g2_wrds_taq_msec.sas` — parameterized millisecond extractor for `taqmsec.ctm_YYYYMMDD` / `taqmsec.cqm_YYYYMMDD`.

The extraction logic is preserved for reproducibility, but **no personal direct WRDS access is assumed**. WRDS Support ticket #157666 replied on 2026-10-05 that WRDS does not offer individual subscriptions and would not provide information about other platforms. Execution is therefore authorized only when the operator has a current institution/entity WRDS account and the applicable TAQ entitlement. No shared credentials, account bypass, WRDS credentials, or licensed market-data rows are stored here.

The Python request-manifest path is safe to run locally because it only materializes symbol/date requests. The SAS extractors below are dormant reference/execution templates and must not be treated as evidence that WRDS access, TAQ entitlement, a successful query, a download, or G2 coverage exists.

## Frozen G2 request generation

Generate exact symbol/date request files without contacting a vendor or accessing WRDS:

```bash
python src/g2_wrds_taq_request_manifest.py \
  --output-dir data/private/g2_wrds_requests
```

Expected frozen scope:

- 414 source dates
- 146 unique historical symbols
- 3,828 symbol/date pairs
- 836 legacy pairs before 2013-01-01
- 2,992 millisecond pairs on/after 2013-01-01

Generated files:

- `legacy_symbol_dates.csv`
- `millisecond_symbol_dates.csv`
- `summary.json`

The request generator is dry-run only. It does not log in to WRDS, execute queries, download data, or change G2 coverage.

## Quote fidelity

The copied/adapted quote path retrieves consolidated quote inputs. Strict G2 NBBO coverage remains fail-closed until NBBO construction or direct NBBO validation is proven from actual returned rows.

No external outreach is required by this workflow.
