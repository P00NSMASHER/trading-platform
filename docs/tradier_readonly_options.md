# Tradier read-only options researcher

**Status: quote-observation software, NOT a proven trading strategy.**

The GitHub Actions workflow .github/workflows/tradier-readonly-options.yml accesses the existing repository-level Actions secret named TRADIER_TOKEN. Do not add your token to source, chat, workflow inputs, issues, logs, or artifacts. Only reviewed protected-main push/manual runs receive it; pull-request CI does not.

- Read-only HTTPS GET exclusively: /markets/quotes, /markets/options/expirations, /markets/options/chains, /markets/history on api.tradier.com.
- No brokerage account reads, order previews, order creation, or account writes. Cross-domain redirects are denied.
- Expirations: **0DTE**, **1DTE**, and **7–21 calendar DTE**, separately.
- Market-clock-gated research across **16 liquid tickers** (SPY, QQQ, IWM, TLT, GLD, XLF, XLE, SMH, AAPL, NVDA, AMD, MSFT, BAC, SOFI, F, PFE), in isolated chunks of five, max 20 validated tickers. Approximately one market-data GET per second, below Tradier's documented 120/minute production market-data limit.
- The protected-main workflow runs via GitHub Actions twice on weekdays at 15:40 and 19:40 UTC, automatically respecting NYSE open/closed state. Market-closed checks emit `MARKET_CLOSED_SKIPPED`, not fake zero-signal conclusions. A GitHub cron trigger can be delayed.
- `/markets/timesales` is used for **1-minute underlying ETF context only** on SPY/QQQ/IWM over the prior 30 minutes; it cannot establish historical executable options quotes or profit.
- Reject missing/stale option bid/ask timestamps, wide spreads, low open interest, alternate option roots, and unknown/nonstandard contract multipliers.
- Normalize explicit Unix **seconds or milliseconds** quote timestamps before enforcing the unchanged 120-second maximum age. Tradier's live examples use 13-digit milliseconds, while earlier examples used seconds; ambiguous units remain ineligible. Aggregate counts by unit are safe to log; raw quotes remain private.
- Illustrative $100 *modeled* loss cap for **two-leg out-of-the-money bear-call and bull-put credit verticals** using natural bid/ask entry and estimated four contract-side fees. Early assignment, slippage, margin, and actual execution losses can exceed this estimate.
- H1 explicitly uses a paired, liquid **near-ATM call and put IV** from the candidate expiration divided by 20-session realized volatility (prior **completed** daily bars only). The short-leg IV/RV is kept only for exploratory skew inspection and is **not** substituted for missing ATM data. Tradier's mid_iv uses decimal units (0.35 = 35%, 2.5 = 250%). To qualify H1, both ATM legs require valid timezone-aware ORATS greeks.updated_at timestamps no older than 90 minutes; stale/missing calculations cannot be inferred fresh from quote timestamps. Tradier publishes first hourly Greeks around 10:15 ET. Neither ratio is an expected-profit or fair-value estimate.

To run: repository **Actions** > **Tradier read-only options research** > **Run workflow** (main). The scheduled protected-main workflow also runs on weekdays; protected-main changes to its source/tests invoke another run. Closed/holiday sessions log a skip. Missing or invalid authentication causes a failing run; it is never reported as success.

Aggregate quote rejection counts (invalid, stale, low open interest, wide spread, not OTM) are logged so zero matches can be interpreted without weakening safeguards. An independent **near-ATM Greek diagnostics funnel** now distinguishes missing IV, missing/malformed ORATS timestamps, >90-minute stale calculations and truly fresh provider Greeks, with parity against the two-sided ATM-IV check. Counts are aggregated only, with no symbol/contract/price exposure.

For every expiry bucket the engine separately counts candidate spreads whose **theoretical best-case maximum credit** remains positive after the assumed $2.60 four-side fees, and after additional $5 or $10 adverse-fill stress. This is a necessary economic feasibility check, **not expected value or evidence of an executable fill**. H1 is pre-registered in `docs/options_edge_validation_protocol.md` and remains unverified.

Raw market data exists only in ephemeral GitHub-runner temporary storage and is deleted, with **no uploaded artifacts or committed quotes**. The repository is public. Logs show sanitized counts only. A successful run establishes API and options-chain access, **not a profitable or executable strategy**. Out-of-market-hours quote staleness may yield zero candidates.

Before risking capital, use licensed historical options data or prospectively collect authorized snapshots in private storage. Measure fill rates, slippage, assignment exposure, full exit costs, tail risk, drawdowns, and independent out-of-sample performance. The workflow never submits orders.

## Diagnostic interpretation (protected-main research)

The sanitized rejection funnel now includes **disjoint age bins**, invalid-market
subtypes and separate counts for 0DTE, 1DTE and 7-21DTE. Quote-age histograms
cover all option rows (including rows rejected first for invalid bid/ask);
the sequential rejection reasons count only each row's **first failure**.
Do not add the age histogram to the sequential rejection count or interpret
postmarket staleness as an untradeable market-hours universe.

An independent pair-level funnel counts OTM, standard, quote-eligible legs
by call and put; then same-expiry strike pairs lost to >$3 width, nonpositive
natural bid/ask credit, credit >= width or the unchanged **$100 modeled maximum
loss** after four illustrative contract-side fees. It asserts exact equality
with production candidate selection and fails closed on a discrepancy.
By-expiration-bucket stage counts distinguish a small-account strike-grid
constraint from a market-data-quality constraint without publishing strikes,
quotes, instruments, underlyings or timestamps.

The 2026-10-27 pre-repair intraday run was invalidated as an opportunity screen
by millisecond/second timestamp handling. The first corrected run occurred
after market close; a subsequent market-clock-gated run skipped closed hours.
**No corrected in-session spread-opportunity inference or profitable edge
has been established.** Underlying bars and IV/HV observations do not
substitute for licensed historical option bid/ask or prospective private
entry/exit measurements.
