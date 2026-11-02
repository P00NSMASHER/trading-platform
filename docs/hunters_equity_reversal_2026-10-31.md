# Hunter B: pre-registered next-day ETF reversal falsification (2026-10-31)

**Research verdict: REJECT as a robust/validated edge.** No live trades, no broker calls, no profitable strategy demonstrated. The signal and costs below were fixed *before* observing the results in this Hunter run. This research is independent from the existing Tradier options H1/H2/H3 studies and does not modify their source, secrets, workflows or previous conclusions.

## Signal and execution (research only)

- Signal at session **T-1 close**: adjusted close-to-close return (T-2 to T-1) <= **-1.00%**.
- Hypothetical action: buy ETF at **T regular-session OPEN**, sell at **T CLOSE**; otherwise hold cash. This is an *idealized* open-print fill. It is **not** an independently executable fill and cannot model actual open slippage.
- Main friction: **10 basis points** per completed entry + exit. Adversarial stress: **30 bps** and **50 bps**. No tax, capital constraints, borrow, dividend entitlements or partial fills modeled.
- Negative control: previous daily adjusted return >= +1%; descriptive comparator: all sessions.
- Fixed chronology: train 2000–2012; validation 2013–2018; untouched chronological test 2019–latest available at source. No threshold tuning based on the holdout.
- Outcome: average net intraday price return **per triggered session**. **Do not interpret as compounded portfolio return, annualized return, executable P&L or independent trials**. Same-day ETF cohorts are correlated, so do not pool significance claims across tickers.

## Immutable external source census

External public GitHub data is **not rehosted here**. Original vendor methodology, split/dividend transformations, legal rights and time-of-publication availability require separate verification. Repositories are archival secondary sources, **not point-in-time vendor attestations**; this is a retrospective falsification study, not a prospective performance test.

| Source | Fixed upstream commit | File | Git blob SHA-1 | Sessions (observed) |
|---|---|---|---|---|
| xjcarter/data | 7d705ada2d3ca483700eb695772e7de9cfc75cbc | SPY.csv | 5a17de0b52ed8941aacc2ba16bdc96d7c1073cff | 5,759 (2000-01-03 to 2022-11-18) |
| same | same | QQQ.csv | 0b60cfa05a0117194440efd686c2df28f656f022 | 5,759 |
| same | same | IWM.csv | 26c8cb4f083715b4811ab5e388729069476fd27d | 5,658 |
| same | same | DIA.csv | a654644945c5a594ded5ffcb40826d612c729cd6 | 5,759 |
| revred/TradeSmart.Tracker | 7d9d769b0f2ddcedf4c1703cc979b865a37b580d | market/us/spy.csv | 38acc25a077e23fdf107102960c3df32f1543a7d | 3,773 (2011-01-05 to 2026-01-06) |
| same | same | market/us/qqq.csv | 410dc48d874ab666b6e22f529f395c0d9ca70060 | 3,773 |

**Provenance anchors:**
- https://github.com/xjcarter/data/commit/7d705ada2d3ca483700eb695772e7de9cfc75cbc
- https://github.com/revred/TradeSmart.Tracker/commit/7d9d769b0f2ddcedf4c1703cc979b865a37b580d

**Source comparability check:** SPY and QQQ have 2,988 overlapping next-session intraday bars, 2011–2022. Median absolute differences between raw intraday price returns were 0.00012 bps (SPY) and 0.00018 bps (QQQ); maximum below 0.0011 bps. This detects obvious source drift; **the two files are not independent economic evidence**. 30,481 total price rows across six files, including overlapping sources. No raw data or API credentials entered the owner's public repository.

## Untouched holdout results (2019 to each source's final bar)

All results: **net bps per selected trade**, fixed cost assumption; parenthetical n is triggered sessions. Do not treat approximate gross mean or win rate as demonstrated net profit.

| ETF / source | n | Net at 10 bps | Net at 30 bps | Net at 50 bps |
|---|---:|---:|---:|---:|
| SPY / xjcarter through 2022-11-18 | 136 | -0.70 | -20.70 | -40.70 |
| QQQ / xjcarter through 2022-11-18 | 191 | +5.32 | -14.68 | -34.68 |
| IWM / xjcarter through 2022-11-18 | 201 | -3.45 | -23.45 | -43.45 |
| DIA / xjcarter through 2022-11-18 | 128 | +5.66 | -14.34 | -34.34 |
| SPY / revred through 2026-01-06 | 219 | +3.09 | -16.91 | -36.91 |
| QQQ / revred through 2026-01-06 | 308 | +7.77 | -12.23 | -32.23 |

**Validation period 2013–2018 (10 bps):** SPY -18.16 bps (123 trades), QQQ -10.65 (169), IWM -17.75 (216), DIA -15.18 (119). The sign-changing weak holdout positives cannot override the earlier uniform validation failure. All six holdout rows turn negative by 30 bps cost. **6/6 holdout ETF-source rows are negative at 30 bps.**

A separate seeded month-cluster bootstrap in the initial research run produced broad 95% intervals: SPY xjcarter [-21.97,+21.55] bps; QQQ xjcarter [-14.35,+25.83]; IWM [-20.03,+14.05]; DIA [-24.08,+37.02]; SPY revred [-16.03,+24.54]; QQQ revred [-7.60,+25.85]. These are **exploratory**, use a different deterministic resampling implementation from the included Python CLI, and must not be mistaken for preregistered confirmatory coverage. No observed lower bound was positive.

## Reproduce without network access or credentials

1. Obtain the six files from the exact upstream **commit paths**, verify repository reuse/market-data rights, store locally (never commit copied vendor data).
2. Independently validate the original file size and Git BLOB SHA from the table. The Python CLI refuses any other byte sequence, including a silently refreshed source.
3. Run, for example:

       PYTHONPATH=src python -m equity_reversal_audit \
         --file /private/research/SPY.csv \
         --git-blob-sha 5a17de0b52ed8941aacc2ba16bdc96d7c1073cff \
         --symbol SPY

4. Run tests:

       PYTHONPATH=src python -m pytest -q tests/test_equity_reversal_audit.py

The CLI does not fetch price data, send orders, print private rows, access Tradier credentials, or select thresholds from outcomes.

## Remaining limitations / ranked next experiment

1. **REJECT** this signal for trading. Even historical best-case market-open fills fail robustness to 30 bps. No optimized entry window or alternate threshold can legitimately rescue the original untouched holdout.
2. Before any new equity hypothesis, obtain authorized **point-in-time-adjustment and market-open executable quote evidence** (bid/ask with timestamps) and independent multiple-market replication; record source rights.
3. Coordinate with the existing Tradier task: its October 31 v3.3 research showed 15 omitted synthetic losing outcomes could fabricate a +$13.85 apparent spread edge. This study deliberately **does not repeat** that experiment or imply expired options price history is available.
4. For future candidates, preregister a genuinely new hypothesis, budget an untouched forward period, and measure conservative actual fill-surrogate friction including spread/open auction effects and cash exposure, with non-event-day negative controls.

**Research result:** One additional candidate falsified, zero verified profitable strategies, zero brokerage changes, zero live orders, no paid data.
