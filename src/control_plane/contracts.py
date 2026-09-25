from __future__ import annotations

SCHEMA_VERSION = "1"

INFORMATION_STATES = {
    "RECEIVED",
    "HOLDING",
    "ADMITTED_STRUCTURED",
    "REVIEW_REQUIRED",
    "QUARANTINED",
    "IMPORT_FAILED",
}

DECISIONS = {"ADMIT_STRUCTURED", "REVIEW_REQUIRED", "QUARANTINE"}

STRUCTURED_ALLOWED_CLASSIFICATIONS = {
    "authorized_reference_data",
    "public_official_data",
    "public_research_replication",
    "authorized_historical_market_data",
    "synthetic_fixture",
}

PROHIBITED_CLASSIFICATIONS = {
    "live_stolen_information",
    "leaked_credentials",
    "accidental_private_disclosure",
    "unauthorized_private_data",
}
