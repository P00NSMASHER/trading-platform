from __future__ import annotations

from dataclasses import dataclass

from .contracts import (
    PROHIBITED_CLASSIFICATIONS,
    STRUCTURED_ALLOWED_CLASSIFICATIONS,
    UNSTRUCTURED_PUBLICITY_CANDIDATE_CLASSIFICATIONS,
)


@dataclass(frozen=True)
class SourcePolicyDecision:
    decision: str
    reason: str


def evaluate(source: dict) -> SourcePolicyDecision:
    classification = str(source.get("data_classification", "")).strip()
    if classification in PROHIBITED_CLASSIFICATIONS:
        return SourcePolicyDecision("QUARANTINE", f"prohibited classification: {classification}")
    if classification not in STRUCTURED_ALLOWED_CLASSIFICATIONS:
        return SourcePolicyDecision("REVIEW_REQUIRED", f"unsupported classification: {classification or '<blank>'}")

    license_reference = str(source.get("license_reference", "")).strip()
    if classification in {"authorized_reference_data", "authorized_historical_market_data"}:
        if not bool(source.get("authorized", False)):
            return SourcePolicyDecision("REVIEW_REQUIRED", "authorized classification requires authorized=true")
        if not license_reference:
            return SourcePolicyDecision("REVIEW_REQUIRED", "authorized classification requires license/reference evidence")
    elif classification in {"public_official_data", "public_research_replication"}:
        if not license_reference:
            return SourcePolicyDecision("REVIEW_REQUIRED", "public source requires a source/license reference")

    return SourcePolicyDecision("ADMIT_STRUCTURED", f"classification admitted: {classification}")


def evaluate_unstructured(source: dict) -> SourcePolicyDecision:
    """Route an unstructured document without making a publicity determination."""
    classification = str(source.get("data_classification", "")).strip()
    if classification in PROHIBITED_CLASSIFICATIONS:
        return SourcePolicyDecision("QUARANTINE", f"prohibited classification: {classification}")
    if classification not in UNSTRUCTURED_PUBLICITY_CANDIDATE_CLASSIFICATIONS:
        return SourcePolicyDecision(
            "REVIEW_REQUIRED",
            f"unsupported unstructured classification: {classification or '<blank>'}",
        )

    reference = str(source.get("license_reference", "") or source.get("source_reference", "")).strip()
    if classification == "authorized_reference_data" and not bool(source.get("authorized", False)):
        return SourcePolicyDecision("REVIEW_REQUIRED", "authorized unstructured source requires authorized=true")
    if classification != "synthetic_fixture" and not reference:
        return SourcePolicyDecision(
            "REVIEW_REQUIRED",
            "unstructured source requires a source/license reference before publicity review",
        )

    return SourcePolicyDecision(
        "PUBLICITY_PENDING",
        "unstructured source requires independent publicity clearance before any downstream use",
    )
