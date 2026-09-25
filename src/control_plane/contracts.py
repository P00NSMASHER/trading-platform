from __future__ import annotations

SCHEMA_VERSION = "1"

INFORMATION_STATES = {
    "RECEIVED",
    "HOLDING",
    "ADMITTED_STRUCTURED",
    "PUBLICITY_PENDING",
    "PUBLICITY_CLEARED",
    "REVIEW_REQUIRED",
    "QUARANTINED",
    "IMPORT_FAILED",
}

DECISIONS = {"ADMIT_STRUCTURED", "PUBLICITY_PENDING", "REVIEW_REQUIRED", "QUARANTINE"}

STRUCTURED_ALLOWED_CLASSIFICATIONS = {
    "authorized_reference_data",
    "public_official_data",
    "public_research_replication",
    "authorized_historical_market_data",
    "synthetic_fixture",
}

UNSTRUCTURED_PUBLICITY_CANDIDATE_CLASSIFICATIONS = {
    "authorized_reference_data",
    "public_official_data",
    "public_research_replication",
    "synthetic_fixture",
}

UNSTRUCTURED_HOLDING_EXIT_STATES = {
    "PUBLICITY_PENDING",
    "REVIEW_REQUIRED",
    "QUARANTINED",
}

PUBLICITY_CLEARANCE_REQUIRED_DETAIL_KEYS = {
    "clearance_sha256",
    "signer_identity",
    "allowed_signers_sha256",
    "public_release_evidence_sha256",
    "preclearance_event_head",
    "signature_namespace",
}

PROHIBITED_CLASSIFICATIONS = {
    "live_stolen_information",
    "leaked_credentials",
    "accidental_private_disclosure",
    "unauthorized_private_data",
}
