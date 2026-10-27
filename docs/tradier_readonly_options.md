# Tradier read-only options researcher

**Status: quote-observation software, NOT a proven trading strategy.**

The GitHub Actions workflow .github/workflows/tradier-readonly-options.yml accesses the existing repository-level Actions secret named TRADIER_TOKEN. Do not add your token to source, chat, workflow inputs, issues, logs, or artifacts. Only reviewed protected-main push/manual runs receive it; pull-request CI does not.

- Read-only HTTPS GET exclusively: /markets/quotes, /markets/options/expirations, /markets/options/chains, /markets/history on api.tradier.com.
- No brokerage account reads, order previews, order creation, or account writes. Cross-domain redirects are denied.
- Expirations: **0DTE**, **1DTE**, and **7–21 calendar DTE**, separately.
- Fixed research universe: SPY, F, SOFI, BAC, PFE. Five symbols maximum; approximately one GET per second.
- Reject missing/stale option bid/ask timestamps, wide spreads, low open interest, alternate option roots, and unknown/nonstandard contract multipliers.
- Illustrative $100 *modeled* loss cap for **two-leg out-of-the-money bear-call and bull-put credit verticals** using natural bid/ask entry and estimated four contract-side fees. Early assignment, slippage, margin, and actual execution losses can exceed this estimate.
- IV / 20-session realized-volatility ratio is a hypothesis-screening statistic, **not** an expected-profit or fair-value estimate. Option Greeks may update hourly.

To run: repository **Actions** > **Tradier read-only options research** > **Run workflow** (main). A protected-main push changing the workflow or its source/tests also triggers verification. Missing or invalid authentication causes a failing run; it is never reported as success.

Aggregate quote rejection counts (invalid, stale, low open interest, wide spread, not OTM) are logged so zero matches can be interpreted without weakening safeguards. H1 is pre-registered in `docs/options_edge_validation_protocol.md` and remains unverified.

Raw market data exists only in ephemeral GitHub-runner temporary storage and is deleted, with **no uploaded artifacts or committed quotes**. The repository is public. Logs show sanitized counts only. A successful run establishes API and options-chain access, **not a profitable or executable strategy**. Out-of-market-hours quote staleness may yield zero candidates.

Before risking capital, use licensed historical options data or prospectively collect authorized snapshots in private storage. Measure fill rates, slippage, assignment exposure, full exit costs, tail risk, drawdowns, and independent out-of-sample performance. The workflow never submits orders.
