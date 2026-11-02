# Tradier Greek timezone cross-endpoint diagnostic

**Research-only. Never places orders, buys data, changes account settings, or promotes an H1 signal.**

## Measured problem

The protected-main market-hours scan on 2026-10-28 returned **976 near-ATM contracts with fresh bids/asks and non-null IV**, but their chain-level `greeks.updated_at` fields lacked a timezone. Hypothetically interpreting those as UTC made all 976 appear recent, but the model must not assume that interpretation. Tradier's official direct-Greeks example contains a timezone-explicit UTC `Z` suffix; that documentation does not prove every production chain timestamp uses UTC.

Sources:
- https://docs.tradier.com/market-data/get-option-greeks
- https://docs.tradier.com/docs/market-data
- https://github.com/P00NSMASHER/trading-platform/actions/runs/40712002003

## Conservative cross-endpoint investigation

The separate read-only `tradier_greeks_crosscheck.py` job uses at most **six GET requests** to approved Tradier market-data endpoints:
1. Verify the market is **open** with `/markets/clock`; closed market -> skip.
2. Fetch SPY spot and listed expiration dates; select one 7–21DTE expiry nearest 14DTE.
3. Fetch that option chain once with Greeks.
4. Find at most one standard 100-share near-ATM contract **per side** with bid/ask <=120s old, <=25% wide, OI >=100, and fractional IV.
5. Request direct `/markets/options/greeks` once per eligible side (max two calls).
6. Compare the **same exact contract's** direct Greek, not a different strike. Require a timezone-explicit direct timestamp, IV agreement within 0.005 (fractional units), exact UTC wall-clock agreement within 60 seconds, and age no greater than 90 minutes.

The public Actions log publishes only anonymized **integer counters**, including timezone-aware matches and two-side corroboration. It also reports the ordered near-ATM selector's counts (standard root, strict OCC shape, within 3% of spot, valid bid/ask, OI >=100, quote <=120s, non-null IV, timezone-naive ISO Greek time), so a zero-selection run has a reproducible reason without disclosing prices or contracts. No contract IDs, strike prices, option quotes, bid/ask, exact timestamps, or sensitive tokens are published; the existing ephemeral quote CSV remains deleted.

If both sides corroborate, the tool reports **TWO_SIDES_CORROBORATED_DIAGNOSTIC_ONLY**. This *supports investigation* of the hypothesis that the chain timestamp means UTC for those exact contracts at that moment. It is **not** a guarantee for other symbols, other dates, or future API output. This tool does **not** normalize naive timestamps or change H1's existing strict timezone check. If the direct endpoint also omits timezone, a contract cannot be found, a Greek differs, the quote is stale, or the provider returns errors, the result is inconclusive or failed closed.

## Next scientific gate

Only repeated, directly matched, independently time-aligned provider observations across multiple sessions could justify a separately reviewed, scope-limited timestamp interpretation. Historical option quotes and paired executable entry/exit marks remain unavailable here. Consequently **the profitable-edge verdict remains UNPROVEN**, even if the timestamp hypothesis is corroborated.

Do not use the cross-check as a trading signal.

## First live result and bounded follow-up

The initial 2026-10-28 protected-main run succeeded overall, but the SPY direct-Greeks corroboration was **INCONCLUSIVE**: the first sampled expiry had zero contracts passing the strict selector, so no direct-Greeks call was made. This is not proof that either API returns incompatible timestamps. The new anonymous stage counts distinguish whether the issue is strict OCC symbol shape, near-ATM/liquidity constraints, quote age, or the unavailable naive timestamp; no market-data assumption or H1 gate has been relaxed.

Source: https://github.com/P00NSMASHER/trading-platform/actions/runs/40733937715
