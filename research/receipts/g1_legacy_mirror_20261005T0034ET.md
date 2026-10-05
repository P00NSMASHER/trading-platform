# G1 legacy mirror research receipt — 2026-10-05 00:34 ET

Base main: `8014585b043217da5d5774382eb79e6a8b0972cc`
Canonical state at start: 123/174 exact, 51 unresolved, token UNASSIGNED, no prepared queue.

## New legacy-mirror artifacts / family validation

### HEJFE-54A5D1D8A5B593C8 — NUAN — owner Worker 2
Exact ADVFN mirror:
https://br.advfn.com/bolsa-de-valores/nasdaq/NUAN/share-news/65379940/nuance-announces-first-quarter-fiscal-2015-results

The page reproduces the exact target release title, `Nuance Announces First Quarter Fiscal 2015 Results`, and release content, so it is useful identity/date corroboration. The accessible page did **not** expose an article publication clock/timezone. Its visible `Última atualização: 21:00:00` belongs to current quote data, not the 2015 article; explicitly reject it as G1 timing evidence.

Disposition: NEW_LEGACY_ARTIFACT / no admissible clock. Do not promote.

### MarketScreener / 4-Traders family
Fresh validation shows historical MarketScreener wire pages can preserve explicit source publication clocks and timezone labels (examples found on 2015 Business Wire / GlobeNewswire / PRNewswire items with strings such as `Published ... at ... EST`). A 2015-01-22 historical listing also indexes the exact SWKS target title `Skyworks Solutions : Exceeds Q1 FY15 Revenue and EPS Guidance` with BU / Business Wire provenance.

However, this pass did not recover the direct exact-target SWKS article page with its timestamp. The listing date/source is only a discovery clue, not canonical timing evidence.

Disposition: genuinely useful source-family confirmation; target direct MarketScreener/4-Traders article IDs and legacy URL patterns next.

### CREE secondary alert rejection
A secondary RTTNews item for the 2015-01-20 CREE earnings release exposes 4:19 PM ET. This is a secondary alert timestamp, not first-public release time, and is explicitly rejected under G1 rules.

## No FOUND clock this pass
No event met all requirements: exact release identity + explicit first-public publication time + defensible timezone + post-trade chronology.

Recommended next pass:
1. Resolve direct MarketScreener/4-Traders article IDs for SWKS, CREE, IDTI, ROG, NUAN and CGNX exact releases.
2. Search legacy ADVFN article IDs for exact target releases where current search indexes only the SEC/issuer page.
3. Continue old RSS/Atom/JSON and issuer-CDN mirror paths, accepting only raw publication timestamps tied to the exact release.
