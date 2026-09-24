# Step 14 — Real Historical Graph Reconstruction

## Purpose

Reconstruct the Cross-Event Intelligence Graph for the real historical hacked-newswire event corpus while preserving point-in-time information boundaries.

This step is surveillance/research-only. It does not generate trade directions, expected returns, target prices, position sizes, orders, or execution instructions.

## Real corpus

Input: `data/processed/historical_events.csv`, produced from the public `vgreg/hacked_earnings_jfe` first-trade file.

Measured corpus shape:

- 174 SEC-complaint-derived first-trade events
- 146 unique historical PERMNOs
- 146 unique GVKEYs
- 146 unique historical ticker symbols

The source repository says `TimeOfFirstTrade` contains the time of the first trade by the hackers according to SEC complaint documentation. The SEC publicly announced the hacked-newswire enforcement action on August 11, 2015; the complaint had been filed under seal on August 10 and was unsealed on August 11.

## Graph construction

Nodes:

- 1 case node: `CASE:SEC-DUBOVOY-2015`
- 174 event nodes
- 146 issuer nodes keyed by GVKEY
- 146 security nodes keyed by PERMNO

Edges:

- 174 `case_contains_event`
- 174 `event_concerns_issuer`
- 174 `event_observed_in_security`
- 146 `issuer_has_security`

Total: 467 nodes and 668 edges.

## Timestamp policy

The original first-trade timestamps are interpreted as New York market-local timestamps and converted to UTC with `zoneinfo`, including historical daylight-saving rules.

The enforcement edges use:

`public_at = 2015-08-11T23:59:59Z`

This is intentionally conservative. The official SEC material establishes the public date but the reconstruction does not invent an intraday release time.

Issuer/security identity edges are made visible no earlier than the earliest event timestamp present in the public research corpus. That is conservative and avoids inventing historical listing dates.

## Visibility behavior

At each original 2011–May 2015 event timestamp:

- `live_surveillance`: the later SEC enforcement relationship is invisible.
- `historical_forensics`: later-public enforcement information can explain events whose underlying `observed_at` has already occurred.

Measured audit:

- 174/174 live rows: enforcement case invisible
- 0/174 live rows: related securities via the later case graph
- 174/174 forensic rows: case visible for explanation
- 173/174 forensic rows: at least one prior/same-case related security is reachable
- maximum forensic related-security count: 145

After the public enforcement date, a live probe on August 12, 2015 can traverse the now-public case graph and reaches the other 145 historical securities from the sample seed.

## Non-synthetic model-comparison gate

Step 14 does **not** claim a real champion/challenger result.

The bundled Step-6/Step-13 market features and matched controls are synthetic fixtures. The public hacked-earnings repository does not ship the proprietary merged TAQ/ITCH/CBOE minute-level panel used in the academic analysis.

The readiness gate therefore returns:

- `comparison_executed = false`
- `eligible_for_non_synthetic_champion_challenger_comparison = false`

until all three are available:

1. lawfully obtained point-in-time historical equity/options market features;
2. matched controls generated from that same real feature universe;
3. Step-12 `live_surveillance` graph vectors for those exact timestamps.

No synthetic dataset may be relabeled as non-synthetic performance evidence.

## Source policy

Allowed in this reconstruction:

- official public enforcement material;
- adjudicated/public enforcement records;
- public research corpora derived from those records;
- separately licensed/authorized data.

Explicitly rejected from live inputs:

- live stolen information;
- active or leaked credentials;
- accidental private disclosures;
- unverified private information.

## Outputs

`data/processed/historical_graph_real/`

- `historical_graph_nodes.csv`
- `historical_graph_edges.csv`
- `historical_cross_event_graph.sqlite`
- `historical_graph_manifest.json`
- `historical_graph_context.csv`
- `non_synthetic_comparison_readiness.json`
- `historical_graph_reconstruction_self_check.json`

## External references

- SEC Press Release 2015-163: hacked news releases enforcement action, August 11, 2015.
- SEC Litigation Release 23319: SEC v. Dubovoy et al.
- `vgreg/hacked_earnings_jfe`: public research code/data for *Price Revelation from Insider Trading: Evidence from Hacked Earnings News*.
