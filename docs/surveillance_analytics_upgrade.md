# Surveillance analytics upgrade

This repository remains a **historical market-surveillance research system, not a trading system**. The analytics below adapt mature ideas from event-driven research and factor-analysis ecosystems without copying or vendoring their source code.

## Deterministic point-in-time event tape

`src/event_tape_replay.py` adds an event-tape abstraction inspired by event-driven replay patterns used by mature research engines such as QuantConnect Lean and Zipline.

Each input event carries both an event time and a source-availability time. Replay time is the later of those two timestamps, so an observation cannot enter reconstructed state before it occurred or before its source says it was available. The tape has deterministic ordering, input hashes, prefix checkpoints, a semantic stream hash, and an optional as-of cutoff.

This module has no brokerage, order, expected-return, position-sizing, or execution interfaces.

## Offline feature diagnostics

`src/surveillance_feature_diagnostics.py` adds offline diagnostics inspired by analytical concepts associated with Alphalens, Pyfolio, and ffn:

- feature quantile lift against sealed historical labels;
- temporal stability by year;
- cohort stability by adjudicated case family;
- optional relative-minute signal-decay diagnostics;
- pairwise feature redundancy;
- richer frozen-score diagnostics including ROC AUC, average precision, Brier score, prevalence, flag rate, TPR, FPR, and precision by overall/cohort/year/mechanism.

The diagnostics consume already-scored evaluation rows and point-in-time features. They do not retrain models, tune thresholds, promote challengers, or generate financial-return/trading outputs.

## Third-party code and licensing

No source from Lean, Zipline, Alphalens, Pyfolio, ffn, or other researched repositories is copied or vendored by this upgrade. Their names document architectural/analytical inspiration only. The implementation in this repository is original and stays within the existing surveillance-only mission.
