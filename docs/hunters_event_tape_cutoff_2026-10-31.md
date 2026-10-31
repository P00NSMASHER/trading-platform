# Hunter A | explicitly empty as-of cutoff integrity | 2026-10-31

## Reproduced defect and scope
Canonical repo `P00NSMASHER/trading-platform`, source `src/event_tape_replay.py` on default `main`; branch `hunters/event-tape-explicit-cutoff-20261031`. Trading/Tradier research PRs #518, #520 and #511/#512 were inspected and left untouched. Portfolio Brain is under separate observation/recovery ownership; **no Portfolio Brain files or observation clocks were changed**. Paper-only historical research, not trading execution.

Before: `build_event_tape(as_of_utc="")` evaluated `if as_of_utc` as false and silently omitted the point-in-time cutoff, yielding `as_of_filter_applied=false`. Non-string falsey cutoff values did the same. This can convert a caller's attempted cutoff into an unfiltered replay. **No observed real-data occurrence is claimed.**

After: `None` alone means omitted filter; explicit blank/whitespace values and non-strings reject with `ValueError` before any source file is read or output written. Valid timezone-aware UTC cutoffs still defer events based on both event and source availability. Synthetic controls cover six invalid forms, a valid control and a no-cutoff control.

## Upstream alternatives, provenance and security
1. [dateutil/dateutil](https://github.com/dateutil/dateutil) @ `71d92da6f0318101653039ab3f051aef5d7e0438` (examined 2026-10-31), license file `LICENSE` includes Apache License 2.0 terms; active, upstream pushed 2026-10-25. Full ISO/date parser is larger than the required explicit-None contract check.
2. [arrow-py/arrow](https://github.com/arrow-py/arrow) @ `2224255c4acc594d734cef0bbc83360452a67983` (examined 2026-10-31), `LICENSE` Apache-2.0, upstream pushed 2026-06-22. Additional runtime parsing capabilities do not justify new dependencies for this one guard.

Chosen: independent, standard-Python type/presence validation; **no upstream code copied or vendored**, no new third-party runtime, license/NOTICE, telemetry, lockfile or transitive security surface. A full dependency-advisory audit was not performed for the rejected candidates.

## Regression / economics / rollback
Run `pytest -q tests/test_event_tape_explicit_cutoff.py tests/test_event_tape_replay.py`, then exact-head hosted CI for remaining tests. Eight synthetic local scenarios are defined: six disallowed cutoff values plus positive control and early validation. Actual CI and platform-wide pass counts must come from GitHub, not from writing these tests.

Estimated engineering effort avoided if an invalid-cutoff replay would otherwise require manual evidence investigation: **0.5–2 hours, low-confidence counterfactual**, not measured engineer-hours or proven market edge. No trading edge, market prices, orders, customer results, or broker credentials involved.

Rollback: revert this one branch/PR, no migration. Next priority: audit other optional as-of gates for truthiness-based cutoff bypass while respecting existing PR ownership and no-live-trading authority.
