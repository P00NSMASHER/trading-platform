# Step 11 — Cross-Event Intelligence Graph

`src/cross_event_graph.py` adds a private, append-only relationship graph for historical market-surveillance research.

## Purpose

The graph connects historical cases and events to issuers, securities, people, advisers and other organizations so the surveillance platform can reason about cross-security relationships without turning those relationships into trade recommendations.

The graph is designed for two separate visibility modes:

- `live_surveillance`: an edge is visible only if its `public_at` timestamp is at or before the scoring time. Later enforcement findings are therefore unavailable to a live historical simulation.
- `historical_forensics`: later-public adjudication records can be used to reconstruct and evaluate historical relationships after the fact.

This separation prevents enforcement outcomes from becoming future-information leakage.

## Source policy

Allowed graph sources are limited to:

- adjudicated public records;
- official public sources;
- public filings;
- properly licensed/authorized data;
- synthetic test fixtures.

Live stolen/private information, leaked credentials, accidental private disclosures, and unverified private material are rejected by the loader.

## Capabilities

- append-only SQLite nodes and edges;
- point-in-time temporal validity (`valid_from`, `valid_to`, `public_at`);
- provenance and adjudication confidence on every edge;
- multi-hop related-security expansion for surveillance coverage;
- case-level contamination blocklists for matched-control exclusion;
- structural case-similarity search;
- integrity/source-policy self-checks;
- input/database SHA-256 provenance.

`path_confidence` is provenance/relationship confidence only. It is not a probability of wrongdoing or a trading signal.

## Synthetic demo

```bash
python src/cross_event_graph.py build \
  --nodes data/examples/cross_event_nodes.csv \
  --edges data/examples/cross_event_edges.csv \
  --db data/processed/graph_demo/cross_event_graph.sqlite \
  --manifest data/processed/graph_demo/graph_manifest.json

python src/cross_event_graph.py expand \
  --db data/processed/graph_demo/cross_event_graph.sqlite \
  --seed-security SEC:SYN-A \
  --as-of 2016-08-18T19:30:00Z \
  --mode live_surveillance \
  --max-hops 2 \
  --output data/processed/graph_demo/related_securities_live.csv

python src/cross_event_graph.py blocklist \
  --db data/processed/graph_demo/cross_event_graph.sqlite \
  --case-id CASE:SYN-CROSS-1 \
  --as-of 2022-01-01T00:00:00Z \
  --mode historical_forensics \
  --output data/processed/graph_demo/case_contamination_blocklist.csv

python src/cross_event_graph.py similar-cases \
  --db data/processed/graph_demo/cross_event_graph.sqlite \
  --case-id CASE:SYN-CROSS-1 \
  --as-of 2022-01-01T00:00:00Z \
  --output data/processed/graph_demo/similar_cases.csv

python src/cross_event_graph.py self-check \
  --db data/processed/graph_demo/cross_event_graph.sqlite
```

The shipped demo is synthetic and exists only to validate graph plumbing.
