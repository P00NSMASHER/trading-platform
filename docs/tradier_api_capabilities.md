# Tradier API capabilities and evidence boundaries (2026-10-27)

## Confirmed production capabilities, and what the research workflow uses

| Market-data resource | Official API | Scope in this research | State |
|---|---|---|---|
| Exchange clock | GET /v1/markets/clock | Require an open market before accepting live opportunity observations; holidays and after-hours produce MARKET_CLOSED_SKIPPED | ACTIVE |
| Option expiration discovery | GET /v1/markets/options/expirations | Discover listed dates, then sample 0DTE, 1DTE and 7–21 DTE | ACTIVE |
| Option chains / hourly Greeks | GET /v1/markets/options/chains | Call and put spreads, standard 100-share contracts, OTM, natural bid/ask pricing, at most $100 *modeled* max loss, IV/RV metadata | ACTIVE |
| Separate Greek cross-endpoint verification | GET /v1/markets/options/greeks | At most four 7–21DTE SPY expirations to identify liquid near-ATM call/put pairs, then compare identical contract IDs and updated_at timestamps; diagnostic only, never a timezone assumption | **HTTP 403 on live 2026-10-28; opt-in manual only** |
| Option-specific quote/Greek corroboration | GET /v1/markets/quotes?symbols=<OCC>&greeks=true | Same permissioned GET quotes endpoint used for underlying quotes; bounded SPY near-ATM contract identity, IV and timezone-aware timestamp comparison, diagnostic only | **ACTIVE bounded diagnostic; timezone/result not yet verified** |
| Equity/ETF quotes | GET /v1/markets/quotes | Spot price and spread validation for each of 16 symbols | ACTIVE |
| Historical daily prices | GET /v1/markets/history | 20-day realized volatility using **completed prior closes only** | ACTIVE |
| Underlying one-minute bars | GET /v1/markets/timesales | Three liquid ETF contexts (SPY, QQQ, IWM), 30-minute window, 1-minute bars; aggregate valid bar counts only, **never option fills** | ACTIVE |
| Streaming quote/trade/timesale | Market streaming WebSocket or HTTP | More efficient for a continuous **private** collector. One market stream permitted at a time. Not suitable for short-lived public GitHub-runner research | NOT ACTIVATED |
| Historical option OHLC for **unexpired** OCC contracts | GET /v1/markets/history with OCC symbol | Possible OHLC context, **not historical option bid/ask execution prices**. Expired-contract history unavailable | NOT USED |
| Account/order/trading endpoints | /accounts, /orders, preview/place trade | Explicitly **forbidden** to the observer; secret only in reviewed main GitHub Actions and seven GET-only allowlisted endpoints | DENIED |

**Live limitation (2026-10-28):** [Protected-main verification run 40736968570](https://github.com/P00NSMASHER/trading-platform/actions/runs/40736968570) successfully retrieved option chains, but the separate `/markets/options/greeks` endpoint returned `HTTP 403` for this token. The endpoint is therefore not part of normal scheduled/push scanning. It can only be retried through an explicit manual workflow input, without hiding a 403 failure. This does **not** establish the cause of the denial, confer access rights, justify purchasing a plan, or establish the timezone of a chain's offset-free ORATS timestamp. H1 stays unverified.

## Capacity and scheduling

Tradier documents **120 market-data requests per token per 1-minute window** in production. A maximum of 20 symbols, five-symbol batches, and roughly one request/second provides conservative room under that limit. GitHub Actions schedule (UTC): 15:40 and 19:40 Monday through Friday; the exchange clock handles daylight-saving, holidays, early closes, and delayed workflow starts. GitHub scheduling itself can be delayed. The workflow never purchases anything, accesses accounts, or trades.

A production rate-limit breach may return HTTP 400 rather than 429, containing a "Quota Violation" message. The runner deliberately sanitizes HTTP errors and fails closed, without exposing tokens or provider raw responses.

## Research integrity

The program publishes only **aggregate counts** in GitHub Actions logs, deletes temporary CSVs, and never uploads licensed raw market data to its **public** repository. Thus successful runs show connectivity, quote quality and screen candidates, not realized returns. A long-running, private and licensed snapshot system with matching future exit prices and independently held-out results is still needed to prove an edge.

**Not claimed:** option IV superiority as profit, win rate as expectancy, theoretical POP as realized fill probability, or historical option execution with underlying-only bars. No automated buying or selling.

## Official source references

- https://docs.tradier.com/
- https://docs.tradier.com/docs/market-data
- https://docs.tradier.com/market-data/get-market-clock
- https://docs.tradier.com/market-data/get-options-expirations
- https://docs.tradier.com/market-data/get-options-chains
- https://docs.tradier.com/market-data/get-option-greeks
- https://docs.tradier.com/market-data/get-quotes
- https://docs.tradier.com/market-data/get-time-and-sales
- https://docs.tradier.com/overview/rate-limits
- https://docs.tradier.com/docs/streaming-data
- https://docs.tradier.com/docs/historical-data
