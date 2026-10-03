# LSEG Tick History G2 source plan

This directory records the sanitized extraction logic and provenance for the licensed LSEG Tick History route discovered through public GitHub repositories.

## What is extracted into this repository

- Exact-root candidate RIC mappings for the frozen 146-symbol G2 equity universe.
- Tick History Time & Sales fields needed for G2 trades and quotes.
- Historical/inactive-instrument validation requirements.
- Historical option-universe resolution methods.

No usernames, passwords, API tokens, or upstream token-like example values are copied.

The candidate mapping is not itself market-data coverage. Each RIC must still be validated for the requested historical date, and actual returned rows must pass the existing G2 source-contract validation before coverage can move.
