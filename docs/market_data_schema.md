# Market-data adapter schema (Step 2)

The adapter accepts **lawfully obtained historical market data** only. It normalizes four input lanes:

- `equity_trade`
- `equity_quote`
- `option_trade`
- `option_quote`

## Required input columns

### Equity trade
`timestamp,symbol,price,size`

### Equity quote
`timestamp,symbol,bid,ask,bid_size,ask_size`

### Option trade
`timestamp,symbol,underlying_symbol,option_symbol,expiration,strike,option_type,price,size`

### Option quote
`timestamp,symbol,underlying_symbol,option_symbol,expiration,strike,option_type,bid,ask,bid_size,ask_size`

Optional fields include `exchange` and `conditions`.

## Timestamp rules

- Offset-aware ISO-8601 timestamps are converted directly to UTC.
- Naive timestamps are accepted only with an explicitly supplied source timezone (default CLI setting: `America/New_York`).
- Timezone-naive local timestamps in a daylight-saving **gap** (a wall time that never happened) or **fold** (a wall time with two possible UTC instants) are rejected with the source row number. Supply an offset-aware ISO-8601 timestamp to disambiguate instead. The adapter never silently guesses an instant.
- Unambiguous naive timestamps retain their previous UTC normalization. Explicit offsets are authoritative even when the unrelated default source timezone is invalid.
- Normalized output timestamps are UTC ISO-8601 ending in `Z`.

## Validation rules

- Trades require strictly positive price and size.
- Quotes require `bid >= 0`, `ask > 0`, `bid <= ask`, and nonnegative sizes.
- Option rows require a positive strike and an option type of call/put.
- Inputs are hashed into the generated manifest for provenance.

## Minute outputs

`equity_minutes.csv` contains trade OHLC/VWAP/volume plus quote-derived mid/spread summaries.

`option_minutes.csv` aggregates by underlying and minute and contains contract volume, economic option dollar volume using the standard 100-share multiplier, call/put volume, unique contracts, and quote-spread summaries.

These outputs deliberately do **not** include directional trading signals, expected returns, target prices, or order instructions.
