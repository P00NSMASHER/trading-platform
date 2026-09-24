# Step 17 — Point-in-time metadata resolver

This step resolves the non-market-data metadata required by the historical surveillance reconstruction while preserving the information set available at each timestamp.

## Gates

### G1 — public announcement timestamp
Accepted as exact only when a source identifies the first public/newswire release timestamp with timezone and grade A/B provenance. SEC EDGAR `<ACCEPTANCE-DATETIME>` may be retained as a public proxy, but it does **not** by itself prove the instant content first became public; therefore it does not close the exact-release gate.

Recommended sources: licensed I/B/E/S announcement timestamps, official newswire archives, issuer IR archives with verified publication timestamps. SEC complete-submission headers are useful corroborating proxies.

### G3 — point-in-time primary exchange
The resolver accepts daily/effective-dated security-master rows and normalizes exchange codes. A historical NYSE Daily TAQ Master file is particularly useful because its documented `Listed Exchange` field identifies the listing exchange on that trading date. Nasdaq ITCH is required for primary-market order-flow reconstruction only when the historical primary listing resolves to Nasdaq.

### G4 — point-in-time shares outstanding
Daily TAQ Master rows can directly supply that day's shares outstanding (documented by NYSE as millions of shares). Effective-dated SEC/XBRL facts can also be used only if the fact was already available by the target date; future-filed facts are rejected. Stale facts beyond the configured tolerance remain unresolved.

### G5 — point-in-time control universe
A date-level research universe such as `SampleFirms` is useful for retrospective candidate enumeration but does not by itself close the live-style matching gate. The gate requires at least three candidates per event date whose membership/metadata were available by the scoring timestamp and whose pre-event matching covariates are complete.

## Supported metadata contract record kinds

- `announcement_timestamp`
- `security_master`
- `shares_outstanding`
- `control_universe`

Allowed source families include I/B/E/S or official newswire timestamps, SEC EDGAR headers/XBRL, NYSE Daily TAQ Master, Nasdaq Daily List, public research replication universes, and explicitly authorized reference data.

The contract rejects credential-like fields and prohibited source classifications such as live stolen information, leaked credentials, accidental private disclosures, or other unauthorized private data.

## Outputs

- `announcement_resolutions.csv`
- `event_exchange_resolutions.csv`
- `shares_outstanding_resolutions.csv`
- `control_universe_readiness.csv`
- `metadata_source_inventory.json`
- `metadata_readiness_summary.json`
- `metadata_unresolved_gates.csv`

All outputs remain research/surveillance-only and contain no trading direction, return forecast, target price, sizing, or order fields.
