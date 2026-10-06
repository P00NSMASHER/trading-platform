# Hacked earnings: deeper public-source extraction

## Result

Verified 9 source assets at `c23c7d79d067a79d70cf20e31b072d3703497eae` and processed all six annual archives.
Enumerated 36,750 press-release text members; linked text to 36,750 of 43,687 sample rows and 160 of 174 first-trade records.
Recovered 2,393 fitted coefficients (404 nonzero).
Found text for 0 sample rows with missing published Soft, including 0 first-trade records. Published Soft is left missing.
Isolated 560 additional Actual=1 sample rows outside the 174-event heuristic join.
Generated 9,329 same-day nonexposed candidate pairs across 174 events. These are not accepted G5 matches.

## Interpretation

This package expands the usable text research corpus, makes model weights inspectable, preserves appendix ambiguity, and prepares candidate comparison groups. It does not establish prediction or trading profitability.

## Required safeguards

- Soft is fitted on the training sample in the published recipe; not independently validated prediction.
- Text and original Soft cannot be used before verified public release; availability clocks are not in archive filenames.
- Fitted-word contribution lacks the unpublished intercept and is NOT a recovered or imputed Soft score.
- Original unsorted directory order and first-appendix choice cannot be reproduced; explicit exploratory choice preserves multiplicity.
- Hacked/Actual are retrospective source labels, not live features; exact-time 174 and broader Actual universe remain distinct.
- First-trade-to-earnings joins are source-date heuristics, not new canonical announcement-time or identity evidence.
- Same-day controls are unbalanced research candidates only; no market cap, liquidity, outcome, or execution evidence is manufactured.
- No raw TAQ/OPRA/ITCH or omitted proprietary MainPanel/return targets recovered; no profit/backtest claims.
- Prior-text changes are descriptive and still need independently verified publication clocks and point-in-time training.

## Next empirical work

1. Resolve multiple-appendix identity and obtain verifiable public-release clocks before feature admission.
2. Join authorized realized returns and fit only on earlier dates, with issuer-aware validation and event-window embargoes.
3. Compare text novelty and independently fitted tone across retrospective cohorts; report missingness and issuer/date concentration.
4. Add point-in-time size/liquidity/sector balance to the candidate control table before accepting G5 matches.

No production model, scheduler, protected release configuration, or canonical data gate is modified.
