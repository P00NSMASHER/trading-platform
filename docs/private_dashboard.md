# Step 9 — Private local dashboard

`src/private_dashboard.py` is a dependency-light localhost-only case-review interface over the Step-8 SQLite case database.

## Privacy and safety properties

- Refuses non-loopback bind addresses (`0.0.0.0` and external interfaces are rejected).
- Rejects non-loopback `Host` headers.
- Uses a per-launch CSRF token for every state-changing form.
- Sends restrictive CSP, no-cache, frame-denial, no-referrer, and browser-permission headers.
- Reads case/evidence snapshots only; it does not load raw licensed market feeds.
- Human review remains append-only through Step 8's hash-chained review history.
- Evidence exports use Step 8 and do not embed raw licensed/proprietary sources.
- No BUY/SELL, expected-return, target-price, position-size, or order outputs exist.

## Run

```bash
python src/private_dashboard.py \
  --db data/processed/case_demo/cases.sqlite \
  --host 127.0.0.1 \
  --port 8765 \
  --open-browser
```

The server prints the local URL and remains available only on the loopback interface. Press Ctrl-C to stop.

## Views

The index supports case/symbol/event search, flagged-state filtering, and disposition filtering. Case pages show:

- surveillance score and frozen threshold;
- current human-review disposition;
- integrity checks;
- complete model-input feature snapshots;
- matched controls and their scores where available;
- evidence timeline;
- source artifact names and SHA-256 hashes;
- append-only review history;
- a constrained form for appending review entries;
- local evidence-bundle generation.

A surveillance case is explicitly not a determination that any person committed insider trading, MNPI misuse, or another violation.
