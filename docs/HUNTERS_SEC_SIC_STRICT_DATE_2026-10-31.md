# Hunter A | point-in-time SEC SIC date integrity | 2026-10-31

## Source-pinned defect
- Baseline protected main `d28c9e38d6040972fc98271ea783dd785231cf1e`, module `src/g5_sec_sic_classification.py` original blob `704cfc937992daca3fc70238aff2bf2b92fba0cb`.
- Original `_parse_date` called `date.fromisoformat(str(value).strip()[:10])`. This **silently accepted** `2015-01-05T23:59:59Z`, `2015-01-05UNVERIFIED`, `2015-01-051` as `2015-01-05`. `20150105` was also accepted by Python's permissive ISO parser.
- Both `_load_targets` and historical CIK interval ingestion use this same parser. Incorrectly normalized source dates can contaminate point-in-time industry classifications.
- Fix is an exact `YYYY-MM-DD` ASCII-digit shape check before stdlib date validation, keeping legal leap dates and existing whitespace trim; invalid days remain rejected. No trades, quotes, account state, prices or research classifications were altered.

## External alternatives reviewed; not imported
- [dateutil/dateutil](https://github.com/dateutil/dateutil) at `71d92da6f0318101653039ab3f051aef5d7e0438`: [Apache-2.0 LICENSE](https://github.com/dateutil/dateutil/blob/master/LICENSE), license blob `1e65815cf0b3132689485874a93034ede7206bf4`. Extensive flexible date parsing is actively counterproductive to a strict schema date.
- [scrapinghub/dateparser](https://github.com/scrapinghub/dateparser) at `b1a87f9f9c76e612e68a0137521ed3e2e1114702` (2026-10-30): [BSD-3-Clause LICENSE](https://github.com/scrapinghub/dateparser/blob/master/LICENSE), license blob `72ff1c05c3af58cac3cf871042a65714b7a90340`. Natural-language/date parser is unnecessary and permissive.
- Decision: reuse the already-imported stdlib `re` and `datetime.date` at zero dependency/lockfile/NOTICE/telemetry cost. Maintainer/license evidence checked; no comprehensive vulnerability/dependency audit of rejected packages claimed.

## Verification and next gate
- Local isolated Python reproduction: four malformed suffix/format inputs were previously accepted; patched exact-parser controls, valid leap day and whitespace controls passed.
- Added two persistent pytest functions covering malformed dates and both real CSV ingestion paths. They must pass along with the repository's genuine exact-head CI; do not equate an isolated parser check with full CI.
- Conservative hypothetical time saved: 0.5–1.5 engineer-hours for incident diagnosis/test design, assuming defect otherwise manifested. This is not measured savings.
- Rollback: revert the one focused PR. No data migration. Do not merge until all protected checks and release governance permit it.
- Separately owned active [PR #519](https://github.com/P00NSMASHER/trading-platform/pull/519) fixes a different SEC Companyfacts nonfinite-shares problem; its files, trades and workflows were not changed. Portfolio Brain observation untouched.
