# G1 issuer-platform routing handoff

Base main: `8014585b043217da5d5774382eb79e6a8b0972cc`

Ledger: `data/public/metadata/g1_issuer_platform_ledger_20261005T0200EDT.csv`

This pass mapped 15 unresolved events to surviving issuer or legacy investor-relations hosts, archive pages, and public feed resources. It is routing metadata only; no publication clock is promoted from crawler, update, or normalized search timestamps.

## Highest-priority routes

- **GNTX — HEJFE-BD3F577ADD90D512 — Worker 0**: current Gentex IR archive remains live at `ir.gentex.com/news-and-media/press-releases`; exact SEC release corroboration is linked in the ledger. This is one of the two current unresolved events not matched by the new GX8002 bulk court map. Route to Court/SEC and Legacy Mirror.
- **PNRA — HEJFE-CCC7747CFBDE893E — Worker 4**: legacy Panera investor host from the exact release was `panerabread.com/investor`; contemporaneous distribution was Marketwired. This is the other current unresolved event not matched by GX8002. Route to Wire Mirror and Legacy Mirror.
- **CGNX — two unresolved events**: Cognex current IR links an official News Release RSS endpoint at `investor.cognex.com/rss/pressrelease.aspx`. Route both to Issuer Feed Miner.
- **CACI — HEJFE-B9C8B3D0EF3DCB5E — Worker 1**: current official news archive at `investor.caci.com/news` visibly includes time-of-day on modern earnings-release listings. The 2015 detail URL was not recovered in this pass, but the platform is a strong historical timestamp candidate. Route to Issuer Feed Miner.
- **TW — HEJFE-5D222F0F8E0C77D0 — Worker 0**: current WTW archive has a 2015 year selector and an official RSS resources page at `investors.wtwco.com/ir-resources/rss-feeds`. Route to Issuer Feed Miner.
- **ILMN — HEJFE-45559DD90D876D39 — Worker 0**: exact official historical target page survives on Illumina's corporate site; visible page shows only date. Route to Issuer Feed Miner for structured metadata.
- **VEEV — HEJFE-EBC49B9A024181AD — Worker 1**: exact official historical target page survives on Veeva's site; visible page shows only date. Route to Issuer Feed Miner.
- **POWI / CRL / ALNY**: current issuer archives remain live and are mapped in the CSV for focused feed/metadata passes.
- **ACO / ROG / MIC / PAY**: legacy/acquired-company paths are mapped for Wire Mirror and Legacy Mirror recovery.

## Guardrails

Do not treat search-engine `Published` values, crawler/import/update times, call schedules, or inferred post-close times as release timestamps. The ledger only reduces rediscovery time and routes each event to the most promising downstream lane.
