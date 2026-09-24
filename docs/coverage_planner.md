# Step 16 — Historical Coverage Planner and Ingestion Readiness Audit

This step computes the exact historical market-data footprint required to move the private surveillance prototype from synthetic fixtures to an authorized, non-synthetic reconstruction of the 174 SEC-complaint-derived first-trade events.

It **does not fetch, purchase, scrape, or authenticate to any data source**. It produces a plan only.

## Default research window

For each documented first trade, the planner requests a regular-session panel from **30 minutes before through 30 minutes after** the first-trade minute, clipped to the XNYS regular session. A five-minute quote extension is separately planned for post-hoc realized-spread / price-impact research.

For same-minute normalization, each event minute requires **21 prior eligible XNYS sessions**. Shortened sessions are automatically skipped when they do not contain the event's local clock-time window. This is important for late-afternoon events around early-close sessions.

## Outputs

- `event_coverage_plan.csv` — exact event clock, event panel, eligible baseline dates, and unresolved per-event requirements.
- `symbol_date_requirements.csv` — deduplicated symbol/date coverage with merged intraday intervals.
- `source_date_requirements.csv` — date-level source requirements for TAQ, Cboe options, and conditional Nasdaq ITCH.
- `announcement_timestamp_requirements.csv` — exact-release-time join requirements for all events.
- `unresolved_gates.csv` — blockers to a genuine non-synthetic model comparison.
- `coverage_summary.json` — aggregate counts, calendar version, current contract coverage, and readiness state.
- `acquisition_import_plan.json` — machine-readable import profile; it intentionally contains no credentials.

## Source profiles

### Core equity surveillance

Required:

- authorized historical equity trades;
- authorized historical equity quotes / NBBO-equivalent data.

### Full research replication

Adds:

- historical option trades by underlying/date;
- historical option quotes by underlying/date.

### Order-flow extension

Decoded Nasdaq TotalView-ITCH is **conditional**. It should only be acquired/imported for symbol-dates whose point-in-time primary listing is confirmed as Nasdaq. Step 16 therefore refuses to pretend it knows the ITCH requirement before historical listing-exchange metadata is supplied.

## Additional blockers

Market files alone are not sufficient. Before the real champion/challenger comparison can be unlocked, the prototype also requires:

1. exact public announcement timestamps for all historical events;
2. point-in-time primary listing exchange metadata to resolve ITCH coverage;
3. effective-dated shares outstanding for turnover normalization;
4. a same-day candidate/control universe and pre-event matching covariates for every distinct event date;
5. authorized non-synthetic source paths and license references in the Step-15 source contract.

The readiness audit treats synthetic fixtures as **zero real coverage**.

## Safety and research boundary

The planner is surveillance/research-only. It contains no trade direction, expected return, target price, position size, order, or execution instruction. It never stores data-source credentials and it never attempts an external data acquisition.
