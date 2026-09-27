# Software readiness certification

This repository intentionally treats **software readiness** and **real-data validation** as separate state dimensions.

The software can be fully implemented, adversarially tested, and operationally hardened while licensed historical data is still pending. Missing data must never be relabeled as validated merely because the plumbing works.

## Command

```bash
PYTHONPATH=src python src/software_readiness_certification.py \
  --require-software-ready
```

The command runs the hostile regression suite, executes the private-runtime integrity self-check, evaluates the current real-data gates, and writes:

`data/processed/software_readiness/software_readiness_certification.json`

## Possible states

### SOFTWARE_NOT_READY

At least one software, adversarial-test, or runtime-integrity check failed.

### SOFTWARE_READY_REAL_DATA_PENDING

The pipeline is implemented and hardened, but one or more real-evidence gates remain unresolved.

This is the expected state while TAQ/options/ITCH/I/B/E/S or genuine point-in-time control data are not yet present.

### SOFTWARE_READY_REAL_DATA_VALIDATED

This state requires all of the following to be genuinely green:

- G1 exact announcement timing
- G2 real historical market data
- G3 primary listing history
- G4 point-in-time shares
- genuine G5 model-evaluation controls
- G6 metadata quality
- a successful non-synthetic real-data replay
- a fail-closed evaluation release

No reviewed exclusion substitutes for the exact-timing or genuine-control requirements.

## Hostile regression categories

The certification suite covers:

1. temporal and point-in-time integrity;
2. control and metadata integrity;
3. model and release isolation;
4. licensed-data intake and real-data replay fail-closed behavior;
5. control-plane and private-runtime security.

Examples include future-price rejection, future-shares rejection, late control-metadata rejection, ambiguous symbol mapping, holdout/group overlap protection, synthetic-promotion blocking, exclusion leakage checks, release-authority checks, and model/runtime integrity.

## Safety boundary

Certification does not authorize trading or deployment.

Automatic model promotion remains disabled, the active champion remains immutable, and BUY/SELL, expected-return, target-price, position-size, order, and execution-instruction outputs remain prohibited.
