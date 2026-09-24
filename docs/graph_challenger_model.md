# Step 13 — Graph-aware challenger model

This step evaluates whether point-in-time graph context from Step 12 adds real surveillance value over the frozen Step-6 champion.

## Non-negotiable separation

- The Step-6 `model_bundle.joblib` is read-only and hash-checked before and after the run.
- The challenger is written to `challenger_model_bundle.joblib` with `active_model=false`.
- No automatic promotion is implemented.
- Synthetic fixtures can exercise the gate but are categorically blocked from promotion eligibility.

## Training inputs

The challenger joins the Step-4 market-surveillance feature allowlist to Step-12 graph features on `(symbol, minute_ts_utc)`. Graph rows must have `visibility_mode=live_surveillance`; `historical_forensics` rows are rejected. The harness never trains on graph identifiers, source hashes, later enforcement outcomes, credential values, private content, expected returns, targets, position sizes, or order instructions.

## Validation

- Development years precede the configured temporal holdout (2015 by default).
- Cross-validation is grouped by treated issuer; each treated event and all of its matched controls travel together.
- The frozen champion, the full graph challenger, and a base-feature-only challenger ablation are scored on the same temporal holdout.
- An unseen-treated-issuer slice is reported separately.

## Promotion gate

A challenger is only *eligible for human promotion review* when all configured gates pass: temporal average-precision gain over champion, graph increment over the base ablation, false-alert guardrail, Brier guardrail, and no degradation on unseen issuers. Even then the harness never overwrites the champion. Synthetic inputs always block eligibility.

## Interpretation

The score is for anomaly prioritization in market-abuse surveillance. It is not a probability that insider trading occurred and is not a trade signal.
