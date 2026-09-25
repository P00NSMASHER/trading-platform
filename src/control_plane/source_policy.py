from __future__ import annotations

from dataclasses import dataclass

from .contracts import PROHIBITED_CLASSIFICATIONS, STRUCTURED_ALLOWED_CLASSIFICATIONS


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
