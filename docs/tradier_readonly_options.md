# Tradier read-only options researcher

**Status: quote-observation software, NOT a proven trading strategy.**

The GitHub Actions workflow .github/workflows/tradier-readonly-options.yml accesses the existing repository-level Actions secret named TRADIER_TOKEN. Do not add your token to source, chat, workflow inputs, issues, logs, or artifacts. Only reviewed protected-main push/manual runs receive it; pull-request CI does not.

- Read-only HTTPS GET exclusively: /markets/quotes, /markets/options/expirations, /markets/options/chains, /markets/options/greeks, /markets/history, /markets/clock and /markets/timesales on api.tradier.com. The direct Greek endpoint is used for a separate bounded diagnostic, never for orders.
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

The 2026-10-28 post-release market-hours run identified 975 near-ATM
legs with IV values and live quoted markets whose ORATS updated_at field
was present but lacked a timezone. Such **naive timestamps remain invalid**
for H1; they are not silently assumed to be Eastern or UTC. The research
engine now reports only integer comparison counts for *what their age
would be* if interpreted as UTC versus America/New_York, plus parseable
but neither-recent cases. These diagnostics do not alter the existing
90-minute Greek freshness rule, signal counts, trade eligibility, risk
caps, or any brokerage API endpoint. The documented Greek response
example includes an explicit Z (UTC); it does not establish the timezone
of an actual response that omits an offset. Only corroborated provider
semantics should justify a future parser change. The separate Greek cross-endpoint
probe now checks up to **four** eligible 7–21 DTE SPY expirations, nearest 14
DTE first, to avoid a thinly traded single chain suppressing the diagnostic.
It retains the same 100-contract open-interest floor, at most nine sanitized
market-data GETs, and no promotion to H1 signal status.

**2026-10-28 access blocker:** The direct `/markets/options/greeks` request
returned HTTP 403 for the currently configured production token, after the
16-symbol option-chain scan completed successfully. This is not evidence that
option chains or their quoted markets are unavailable; it is a separate
permission/access denial with an unverified reason. The two-sided Greek
corroboration step is now **manual opt-in only** through the `run_greeks_crosscheck`
workflow dispatch input (default false). Scheduled and push scans do not
repeatedly invoke an endpoint known to be denied. An explicitly requested
manual diagnostic still fails on access errors; no hidden pass or fallback UTC
assumption is permitted. [Evidence: live run 40736968570](https://github.com/P00NSMASHER/trading-platform/actions/runs/40736968570).

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
Corrected market-hours scans on October 28 examined 91 option chains
per run and identified hundreds of **theoretical** affordable spread combinations;
the ORATS Greek timestamps remained timezone-naive, so the strict H1 screen
still reported zero verified signal chains. **No realized profitable edge has
been established.** Underlying bars and IV/HV observations do not
substitute for licensed historical option bid/ask or prospective private
entry/exit measurements.
