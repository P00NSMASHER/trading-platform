# G1 source readiness — 2026-10-05

Current main remains 123/174 exact with 51 unresolved.

No usable I/B/E/S or RavenPack historical rows were found in the GitHub-visible sources inspected in this run. Public repositories found contained client code, schema examples, or synthetic fixtures only.

Two readiness gaps were confirmed on current main:

1. `src/g1_ibes_timestamp_adapter.py` does not handle SAS numeric date/time values. Its date parser accepts formatted calendar strings, and its time parser accepts `HH:MM[:SS]` or compact `HHMM[SS]`, but not SAS days-since-1960 or seconds-since-midnight. A raw time value such as `57600` (16:00:00) would therefore fail. Add numeric SAS parsing and focused regression tests while preserving existing ambiguity and chronology checks.

2. Current main has no G1 RavenPack timestamp normalizer comparable to the I/B/E/S adapter. Prepare a fail-closed adapter for timestamp, entity mapping, earnings classification, relevance, and source/story identity so a future lawful source drop can be evaluated immediately.

Next action: repair those ingestion-readiness gaps and continue public exact-clock discovery in parallel.
