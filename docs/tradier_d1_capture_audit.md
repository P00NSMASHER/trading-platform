# Independent Tradier D1 capture continuity check (candidate only)

## Objective and evidence boundary

The production Cloudflare Worker `options-tradier-paper-poller` has its own every-minute cron and private D1 `collector_runs_v18` ledger. The GitHub `Tradier read-only options research` workflow is a separate diagnostic whose cron may run **after market close**. Its `MARKET_CLOSED_SKIPPED`/`NO_VERIFIED_OPTION_CHAINS` outcome alone does **not** imply the Cloudflare collector lost Tradier access.

Run `scripts/tradier_d1_capture_audit.py` to check the existing private ledger. This new script is **not deployed**, not automatically scheduled, and does not change either existing collector. It uses a single bounded `SELECT` through the Cloudflare D1 HTTP API (which uses an HTTP POST to submit SQL), and never contacts Tradier, places an order, reads broker accounts, writes D1, or returns licensed quote prices. Do not publish the raw D1 response, tokens, or per-contract data.

## Verified baseline (read-only Cloudflare inspection, 2026-11-10 UTC)

- Existing Cloudflare cron: `* * * * *`; bound secret name: `TRADIER_TOKEN`; bound private D1: `DB`. Existing deployment preserved.
- November 10, 2026 normal session (09:30–16:00 New York): **390** `collector_runs_v18` records, **390** `complete_verified_option_snapshot` rows, no noncapture states; last observed minute 20:59 UTC.
- November 9 normal session: **390** records, **388** complete; two did not satisfy full-completeness criteria. That is a partial-data condition, not proof that the API connection failed.
- Independently, the protected-main GitHub diagnostic failed after market close on November 9 and 10. Its failure is not used to classify D1 capture continuity.

The above observations describe historical capture receipts, **not** a guarantee of future uptime, the ability to open brokerage orders, or a profitable strategy.

## Use

Use an independently granted **Cloudflare D1 read-only token**, held only in a private environment, when an operator wants an up-to-date check. No GitHub Actions or production secret is configured by this PR.

```sh
export CLOUDFLARE_ACCOUNT_ID='<private account id>'
export CLOUDFLARE_API_TOKEN='<private D1 query token>'
python scripts/tradier_d1_capture_audit.py --session-date 2026-11-10 --github-diagnostic delayed_postmarket
```

The D1 database ID is read from the repository's existing `workers/wrangler.tradier.json` and can be overridden with `TRADIER_D1_DATABASE_ID`. The tool uses New York timezone and the lesser of market close and the current time minus two minutes. On a completed regular weekday session, it expects 390 one-minute receipts. **Exchange holidays and early closes are not covered by its regular-session assumption**; interpret missing data on those days as unverified rather than an outage.

For an offline diagnostic regression, use `--fixture-json <private D1-shaped JSON file> --as-of 2026-11-10T21:04:00Z`. A local fixture is never claimed to be live evidence. No broker credentials are used.

## Status and release gates

- `COMPLETE_CAPTURE_OBSERVED`: all expected minute rows exist and have internally consistent full-coverage counts.
- `INCOMPLETE_CAPTURE_OBSERVED`: some minutes or option data are missing; cause remains unverified.
- `NO_CAPTURE_RECORDS`: no records in the bounded window; this is not proof of provider outage.
- `INVALID_EVIDENCE`, `SESSION_NOT_DUE`, `UNVERIFIED`: fail closed, with sanitized output; no false-success classification.
- `github_diagnostic` is an **independent input**. GitHub delayed/failed runs never override the D1 evidence result.

The command exits 0 on complete observed capture, 2 on incomplete/not-yet-due, 3 on query/error conditions. A complete historical session is not proof of **current** Tradier market access; `provider_connectivity_now` always remains `UNVERIFIED`. This is a read-only candidate only. Before enabling automated monitoring, separately authorize the identity, credential, schedule, receiver, cost budget, independent trust-root check, and direct production readback. Never weaken existing option quote freshness or safe-trading gates to make the check green.
