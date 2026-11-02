# G2 WRDS TAQ research-only request plan

This folder intentionally **does not contain or execute SAS extraction templates, any licensed WRDS rows, or copied upstream source code**. The publicly viewable reference [gen-li/Extract_TAQ_from_WRDS_Cloud](https://github.com/gen-li/Extract_TAQ_from_WRDS_Cloud) had no declared LICENSE file or GitHub-recognized license at the 2026-11-02 review. Public visibility alone does not grant redistribution rights. The original unmerged PR history preserves the research trail, but the current integration tree excludes those external copies.

## Safe local planning command

```sh
python src/g2_wrds_taq_request_manifest.py --output-dir data/private/g2_wrds_requests
```

This produces only `legacy_symbol_dates.csv`, `millisecond_symbol_dates.csv`, and `summary.json` from already-frozen local G2 requirement manifests. The expected, test-locked scope is **414 dates, 146 historical symbols, 3,828 symbol/date pairs** (836 legacy, 2,992 millisecond). The generated symbol/date requests are **not** market-data observations, order authority, validated NBBO, entitlements, or actual data coverage.

WRDS Support ticket #157666 (2026-10-05) states individual subscriptions are unavailable; no current personal WRDS authorization is established. Future extraction requires independently approved current institutional/entity access and the applicable TAQ dataset entitlement. Consolidated quotes require genuine NBBO construction/validation before they could ever count as G2 coverage. This PR does **not** log in, contact WRDS, download data, place an order, change a trading rule, or make a purchase.

Release policy: keep original upstream code out of the tree unless redistribution terms are verifiably established. Do not bypass authentication, share institutional credentials, use an unverified mirror, or treat the planning manifest as licensed data.
