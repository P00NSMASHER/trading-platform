# Earlier-only text score vs G5-quality controls

## Strict result

**BLOCKED:** 0 of 72 event dates are eligible for genuine G5 model-evaluation matching.
All 72 dates are fail-closed reviewed exclusions.

The repository explicitly prohibits treating retrospective SampleFirms rows as live/G5 control evidence. Therefore this run does not fabricate a G5 result.

## Partial falsification

{
  "status": "COMPLETED_NON_G5_RETROSPECTIVE_PARTIAL_MATCH",
  "matched_treated_events": 446,
  "matched_pairs": 1338,
  "matching_exact_fields": [
    "calendar_quarter",
    "Hacked=1",
    "different_issuer",
    "control_Actual=0"
  ],
  "matching_numeric_fields": [
    "prior_issuer_rate",
    "log_text_chars",
    "novelty"
  ],
  "missing_required_g5_dimensions": [
    "sector/index_bucket",
    "market_cap/price",
    "21d volatility",
    "normal volume/turnover/spread",
    "option liquidity",
    "institutional ownership",
    "analyst coverage",
    "borrow cost",
    "pre-event return"
  ],
  "mean_text_score_diff": 0.020929083769628185,
  "median_text_score_diff": 0.013087975630476915,
  "treated_beats_matched_control_rate": 0.742152466367713,
  "mean_text_novelty_score_diff": 0.023041520930799492,
  "treated_beats_matched_control_rate_text_novelty": 0.726457399103139,
  "g5_quality": false
}

This secondary diagnostic matches only on calendar quarter, earlier issuer propensity, and reporting-style measures. It omits the G5 dimensions that are currently unavailable and must not be described as G5-quality.
