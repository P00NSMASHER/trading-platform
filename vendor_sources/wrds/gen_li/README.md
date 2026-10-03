# Authorized WRDS TAQ source copies

These files preserve the relevant public extraction logic from `gen-li/Extract_TAQ_from_WRDS_Cloud` for the frozen G2 research workflow.

Current copied slice:
- `WRDS_batch_ticker_ct.sas` — legacy consolidated trades (`taq.ct_YYYYMMDD`), upstream code targets dates before 2013.
- `WRDS_batch_ticker_cq.sas` — legacy consolidated quotes (`taq.cq_YYYYMMDD`), upstream code targets dates before 2013.

The user has confirmed they hold the rights/licenses needed to copy and use the repository information. These archival copies do not include WRDS credentials or licensed market-data rows. Upstream hard-coded user paths are intentionally preserved in the source copy and must not be executed unchanged.

Next adaptation step: generate the exact G2 symbol/date request file from the frozen 2011–2015 manifest, replace hard-coded paths with runtime parameters, and add the 2013+ millisecond TAQ source copies.