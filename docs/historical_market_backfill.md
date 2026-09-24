# Step 15 — Authorized historical market-data backfill

`src/historical_market_backfill.py` is the production import-contract layer between lawfully obtained historical market files and the existing point-in-time surveillance pipeline.

## Scope

The layer is intentionally vendor-format tolerant but **not schema-guessing**. Each source requires an explicit JSON contract specifying its authorization status, data classification, product family, file path, timezone, delimiter, format/specification version, and canonical column mapping.

Supported source families:

- `nyse_daily_taq` — consolidated/historical equity trades or quotes supplied under an authorized NYSE TAQ entitlement.
- `nasdaq_itch_5_0_decoded` — decoded TotalView-ITCH 5.0 order events. Raw binary must first be decoded by an authorized decoder; the format version must be recorded.
- `cboe_option_trades` — authorized historical option trade records.
- `cboe_option_quotes` — authorized historical option quote records/intervals when mapped to the canonical quote contract.
- `generic_authorized_market_data` — another lawful source explicitly mapped to the canonical schema.
- `synthetic_fixture` — tests only; never unlocks a real model comparison.

No credentials or tokens belong in the contract.

## Contract example

```json
{
  "schema_version": "1",
  "sources": [
    {
      "source_id": "taq_trades_20150217",
      "source_family": "nyse_daily_taq",
      "record_kind": "equity_trade",
      "path": "/private/licensed/taq/trades_20150217.csv.gz",
      "authorized": true,
      "data_classification": "authorized_historical_market_data",
      "license_reference": "INTERNAL-DATA-ENTITLEMENT-REFERENCE",
      "trade_date": "2015-02-17",
      "timezone": "America/New_York",
      "delimiter": "|",
      "encoding": "utf-8",
      "format_version": "Daily TAQ applicable historical specification",
      "column_map": {
        "time": "Time",
        "symbol": "Symbol",
        "price": "Trade Price",
        "size": "Trade Volume",
        "exchange": "Exchange",
        "conditions": "Sale Condition"
      }
    }
  ]
}
```

## ITCH order-flow policy

For decoded ITCH, the importer reconstructs displayed order state from add/cancel/delete/replace messages and signs `E`/`C` executions from the resting order side. A resting sell order being executed is classified as buyer-aggressor volume; a resting buy order being executed is seller-aggressor volume. Executions whose referenced add order is missing are skipped rather than guessed. Cross/non-displayed trade messages are not given an aggressor sign by this layer.

This produces `order_flow_minutes.csv` with signed executed shares and absolute imbalance. It does **not** claim to identify a person, account, or actual MNPI trader.

## TAQ microstructure reconstruction

For consolidated equity trades, the layer uses the prevailing prior quote to infer trade sign from trade price versus midpoint, with a tick-rule fallback for midpoint prints. This is a public-market inference, not ground truth about trader identity.

It creates:

- inferred absolute order imbalance;
- point-in-time effective spread;
- quoted spread;
- 5-minute realized spread and price impact for retrospective research only.

The two 5-minute measures are explicitly tagged as using future market data and are forbidden from live model features.

## Historical event alignment

Every historical event gets a minute panel around `first_documented_illicit_trade_ts`, defaulting to -30 through +30 minutes. Exact public-announcement alignment remains disabled until the authorized release-time join is populated.

`event_minute_panel.csv` includes the Step-2 research variables where data are available:

- share volume and `log(1 + share volume)`;
- point-in-time share turnover if a point-in-time shares-outstanding file is supplied;
- option volume and `log(1 + option volume)`;
- quoted/effective spreads;
- ITCH order imbalance when available, otherwise TAQ-inferred imbalance;
- post-hoc realized spread and price impact (research only).

## Readiness gate

Synthetic fixtures can exercise all plumbing but cannot unlock the real champion/challenger comparison. The manifest records whether any non-synthetic authorized source exists and whether event-aligned equity/options/ITCH coverage is present. Performance testing remains a separate locked step.

## Commands

Validate a contract:

```bash
python src/historical_market_backfill.py validate-contract \
  --contract config/historical_market_sources.example.json
```

Build a backfill:

```bash
python src/historical_market_backfill.py backfill \
  --contract /private/contracts/market_sources.json \
  --events data/processed/historical_events.csv \
  --output-dir data/processed/historical_market_backfill
```

Optional point-in-time shares file:

```csv
symbol,effective_at,shares_outstanding
HON,2012-01-01T00:00:00Z,1000000000
```

## Safety boundary

The layer is for historical surveillance research only. Source contracts must assert authorization; live stolen/private corporate information, leaked credentials, accidental private disclosures, future earnings information, and enforcement outcomes are not accepted as trade inputs. The output schema contains no BUY/SELL, target-price, expected-return, position-size, or order fields.

## Vendor-reference basis

The contract model is grounded in the public technical/product descriptions for:

- NYSE Daily TAQ, which includes consolidated trades, quotes, NBBO and administrative data for U.S. equities: https://www.nyse.com/data-products/catalog/daily-taq
- Nasdaq TotalView-ITCH 5.0, whose order/execution messages use nanoseconds-since-midnight timestamps, order reference numbers and match numbers: https://nasdaqtrader.com/content/technicalsupport/specifications/dataproducts/NQTVITCHSpecification.pdf
- Cboe Option Trades, which includes option trade price/size, execution exchange and NBBO context: https://datashop.cboe.com/option-trades
- Cboe Option Quotes, which provides one-minute/custom interval option NBBO, sizes, OHLC and trade volume: https://datashop.cboe.com/option-quote-intervals

The public documentation defines product shapes, not the user's entitlement. The source contract separately requires the local operator to assert authorization and retain an internal license/entitlement reference for non-synthetic data.
