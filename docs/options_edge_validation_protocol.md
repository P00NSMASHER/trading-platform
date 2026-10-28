# Options research preregistration and rejection rules

**Status: hypothesis screening only. Zero verified profitable strategies. No trading.**

## Fixed, testable hypotheses

H1 (primary, prospective): At 7-21 calendar DTE, a conservatively priced, standard-deliverable, out-of-the-money SPY/IWM or other liquid underlying **defined-risk credit vertical** could outperform a matched same-expiry/delta control **after** the entire bid/ask and estimated trading fees, conditional on **same-expiry two-sided near-ATM** (nearest liquid call and put) implied volatility / prior-completed-close 20-day realized volatility >= 1.20. Missing call, put, completed RV, or valid same-day recent ORATS Greek calculations (per-leg provider timestamp no older than 90 minutes) is *unknown*, never H1-positive. Market sessions before Tradier's first roughly 10:15 ET Greek refresh should not be treated as live H1 validation. The short strike's IV/RV is retained separately as exploratory skew metadata, not the primary H1 signal. A high IV/HV ratio is NOT proof of fair-value overpricing. The broker's IV/Greeks can update only hourly.

H2 (secondary exploratory): Lower-price stocks and recent split stocks may have relatively expensive options (see the 2026 peer-reviewed study "Cheap Options Are Expensive", doi:10.1093/rapstu/raag001). That paper concerns delta-hedged option returns, NOT automatically executable 1-point credit spreads. We must not transfer its published return estimate to our strategy without a new test.

H3 (negative control): 0DTE/1DTE quote observations and matched spreads without a pre-registered IV premium should not be called edges based on high win rates or large annualized percentages.

## Fixed entry restrictions

- Market-data GET only. No `/accounts`, `/orders`, order previews, or placements.
- 0DTE, 1DTE, 7-21DTE are separately counted. **Primary assessment uses 7-21DTE only.**
- Compare calls AND puts on the same filters, never switch a losing test to whichever side won retrospectively.
- Standard 100-share deliverables, root matches underlying, unadjusted contract.
- Both legs must have valid bid and ask timestamps no older than **120 seconds**, and both spreads <= **25% of midpoint**.
- Both legs open interest >= 100; strikes out of money; width <= $3; modeled maximum loss <= $100 per one-lot spread, inclusive of $2.60 illustrated full-roundtrip fees. These are safeguards, not a broker-confirmed margin guarantee.
- Short leg sold at BID, long leg bought at ASK. Never assume mid fills for a positive edge. Credit must be strictly positive. Paper exits must use BUY short at ASK, SELL long at BID, plus fees, slippage and early-assignment/dividend risks.
- When the quote is missing, stale, crossed, from a nonstandard contract, or the market is closed, mark **ineligible**, not a $0 profit or a valid losing trade.
- Underlying market-data daily close history is not historical executable option quotes. Do not treat underlying-only replay as an option trade backtest.

## Evaluation plan and acceptance gates

1. Save input constraints and select strategy/benchmark BEFORE observing prospective outcomes. Separate discovery and forward holdout, with no retuning based on holdout performance.
2. Obtain rights-cleared historical option quotes with bid/ask, timestamp, strike, expiry, multiplier and corporate-action adjustment, or collect a prospective PRIVATE snapshot ledger from live Tradier under applicable market-data terms. **Public GitHub logs/artifacts must contain only aggregate counts.** Current workflow deliberately destroys raw quotes and cannot by itself prove future realized P&L.
3. Count signal-bearing **distinct underlying symbols and option expirations**, as well as correlated strike-spread combinations, before making claims about sample size. Many spread combinations on the same chain must NEVER be interpreted as independent trades. Record counterfactual entry, exact as-of, rejection reason, bid/ask, OI, underlying price, position exposure, and exit rules in private storage. Evaluate accepted AND rejected opportunities, delistings, earnings and split events.
4. Reprice at exit/expiration, account for complete commissions/fees and at least one adverse-slippage scenario, compare to simple baselines (random entry, matched expiry/moneyness, long/short controls).
5. Require >= 60 **nonoverlapping** forward trades across >= 3 months as a minimum exploratory screen, independent time-block/bootstrap uncertainty, positive lower 95% confidence bound for **net dollar expectancy** (not simply win rate), a realistic drawdown/tail-loss profile, and robustness under an additional $5/spread fill penalty. This threshold is a pre-registered research gate, not a statistical guarantee.
6. If sample is insufficient, quote execution is uncertain, one exceptional market regime dominates, or lower bound <= 0, the verdict is **UNPROVEN/REJECT**. No output can change status to "profitable" on IV/HV or a third-party model EV alone.

## Evidence and sources

- Live Tradier authorization/17 valid option-chain response: https://github.com/P00NSMASHER/trading-platform/actions/runs/40565091551 . Valid data access, no valid signal established.
- Tradier chain/Greeks docs (decimal IV units, e.g. 0.13835 = 13.835%): https://docs.tradier.com/market-data/get-option-greeks and https://docs.tradier.com/docs/market-data
- Cross-sectional low-price premium: https://academic.oup.com/raps/article-abstract/16/2/283/8428129
- Realized vs implied earnings events and trading frictions: https://www.mdpi.com/1911-8074/16/5/270
- Bid/ask and margin can erase apparent volatility-spread returns: https://doi.org/10.1002/fut.21729
- Free historical EOD backtester candidate (unverified third-party feed; its own documentation flags errors and coverage limits): https://www.onclickmedia.com/backtest/overview

## Private forward outcome validation capability

A separate local-only evaluator at src/options_forward_evaluator.py validates
PRIVATE, independently retained H1 entry/exit paper quote marks: both sides
of both legs at entry and exit, no crossed or wider than 25% markets,
contemporaneous precommitted decision and quote timestamps, a full four-side illustrative commission, $0/$5/$10
adverse-fill stress, 120-second quote freshness, 90-minute Greek freshness,
nonoverlapping underlying exposures, 90 days / 12 entry weeks / 60 marks,
account-level concurrent modeled risk and deterministic entry-week clustered
confidence intervals. See docs/options_forward_evidence.md for the exact
private CSV contract. It cannot verify prospective timestamp attestation or
broker fills: even a positive interval yields only
PAPER_ONLY_PROMISING_NOT_VERIFIED with edge_verdict=UNPROVEN.

This module is not connected to the public GitHub Actions scanner and no
private quote snapshots are uploaded or saved in the public repository.
Matched baselines and untouched out-of-sample outcomes remain required.

**Do not import proprietary raw data into this public repository. No claim of a trading edge until independently audited out-of-sample net results exist.**
