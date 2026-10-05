from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SCHEMA_VERSION = "1"
NY = ZoneInfo("America/New_York")


class G5MatchQualityGateError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file():
        raise G5MatchQualityGateError(f"missing file: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = [
            {str(key): str(value or "").strip() for key, value in row.items()}
            for row in reader
        ]
    return fields, rows


def _float(value: str, *, label: str) -> float:
    try:
        out = float(str(value or "").strip())
    except ValueError as exc:
        raise G5MatchQualityGateError(f"{label} must be numeric") from exc
    if not math.isfinite(out):
        raise G5MatchQualityGateError(f"{label} must be finite")
    return out


def _int(value: str, *, label: str) -> int:
    raw = str(value or "").strip()
    try:
        out = int(raw)
    except ValueError as exc:
        raise G5MatchQualityGateError(f"{label} must be an integer") from exc
    return out


def _event_ts(value: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise G5MatchQualityGateError("event timestamp is blank")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise G5MatchQualityGateError(f"invalid event timestamp: {raw}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=NY)
    return parsed.astimezone(timezone.utc)


def _load_events(path: Path) -> tuple[dict[str, dict[str, str]], dict[str, set[str]]]:
    fields, rows = _read_csv(path)
    required = {
        "event_id",
        "historical_symbol",
        "first_documented_illicit_trade_ts",
        "research_use_only",
    }
    missing = required.difference(fields)
    if missing:
        raise G5MatchQualityGateError(
            f"historical events missing columns: {sorted(missing)}"
        )
    if not rows:
        raise G5MatchQualityGateError("historical events are empty")

    events: dict[str, dict[str, str]] = {}
    positives_by_date: dict[str, set[str]] = defaultdict(set)
    for row_no, row in enumerate(rows, 2):
        event_id = row["event_id"]
        symbol = row["historical_symbol"].upper()
        if not event_id or event_id in events or not symbol:
            raise G5MatchQualityGateError(
                f"event row {row_no}: event_id must be unique and symbol nonblank"
            )
        if row["research_use_only"] != "1":
            raise G5MatchQualityGateError(
                f"event row {row_no}: research_use_only must equal 1"
            )
        local = _event_ts(row["first_documented_illicit_trade_ts"]).astimezone(NY)
        context = {
            "event_id": event_id,
            "treated_symbol": symbol,
            "local_date": local.date().isoformat(),
            "local_minute": local.strftime("%H:%M"),
        }
        events[event_id] = context
        positives_by_date[context["local_date"]].add(symbol)
    return events, dict(positives_by_date)


def _load_manifest(path: Path) -> tuple[dict, int, int, float, list[str]]:
    if not path.is_file():
        raise G5MatchQualityGateError(f"missing file: {path}")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise G5MatchQualityGateError("match manifest is invalid JSON") from exc
    if not isinstance(manifest, dict):
        raise G5MatchQualityGateError("match manifest root must be an object")

    policy = manifest.get("matching_policy") or {}
    balance = manifest.get("balance_policy") or {}
    controls_per_event = int(policy.get("controls_per_event", 0) or 0)
    minimum_controls = int(policy.get("minimum_controls", 0) or 0)
    if controls_per_event < 1 or minimum_controls != controls_per_event:
        raise G5MatchQualityGateError(
            "release-quality matching requires minimum_controls == controls_per_event"
        )
    if not bool(policy.get("known_positive_event_controls_excluded")):
        raise G5MatchQualityGateError(
            "match manifest does not require known-positive control exclusion"
        )
    covariates = [str(x).strip() for x in policy.get("numeric_covariates", []) if str(x).strip()]
    if not covariates or len(covariates) != len(set(covariates)):
        raise G5MatchQualityGateError(
            "match manifest numeric_covariates must be nonempty and unique"
        )
    hard_smd = float(balance.get("maximum_abs_smd", 0) or 0)
    if not math.isfinite(hard_smd) or hard_smd <= 0:
        raise G5MatchQualityGateError("match manifest maximum_abs_smd must be positive")
    max_component_z = float(policy.get("max_standardized_component_distance", 0) or 0)
    if not math.isfinite(max_component_z) or max_component_z <= 0:
        raise G5MatchQualityGateError(
            "match manifest max standardized component distance must be positive"
        )
    return manifest, controls_per_event, minimum_controls, max_component_z, covariates


def build(
    *,
    historical_events_path: Path,
    matched_controls_path: Path,
    match_events_path: Path,
    match_balance_path: Path,
    match_manifest_path: Path,
    output_path: Path,
) -> dict:
    events, positives_by_date = _load_events(historical_events_path)
    manifest, controls_per_event, _minimum_controls, max_component_z, covariates = (
        _load_manifest(match_manifest_path)
    )
    hard_smd = float((manifest.get("balance_policy") or {})["maximum_abs_smd"])

    event_fields, event_rows = _read_csv(match_events_path)
    required_event_fields = {
        "event_id",
        "treated_symbol",
        "local_date",
        "local_minute",
        "candidate_pool_size",
        "matched_control_count",
        "event_status",
        "research_use_only",
    }
    missing = required_event_fields.difference(event_fields)
    if missing:
        raise G5MatchQualityGateError(
            f"match-events file missing columns: {sorted(missing)}"
        )

    summaries: dict[str, dict[str, str]] = {}
    for row_no, row in enumerate(event_rows, 2):
        event_id = row["event_id"]
        if not event_id or event_id in summaries:
            raise G5MatchQualityGateError(
                f"match-events row {row_no}: event_id must be unique and nonblank"
            )
        if event_id not in events:
            raise G5MatchQualityGateError(
                f"match-events row {row_no}: unknown event_id {event_id}"
            )
        if row["research_use_only"] != "1":
            raise G5MatchQualityGateError(
                f"match-events row {row_no}: research_use_only must equal 1"
            )
        expected = events[event_id]
        if (
            row["treated_symbol"].upper() != expected["treated_symbol"]
            or row["local_date"] != expected["local_date"]
            or row["local_minute"] != expected["local_minute"]
        ):
            raise G5MatchQualityGateError(
                f"match-events row {row_no}: treated event identity/time mismatch"
            )
        if row["event_status"] != "matched":
            raise G5MatchQualityGateError(
                f"event {event_id} is not fully matched: {row['event_status']}"
            )
        if _int(row["matched_control_count"], label=f"event {event_id} matched_control_count") != controls_per_event:
            raise G5MatchQualityGateError(
                f"event {event_id} does not have exactly {controls_per_event} matched controls"
            )
        if _int(row["candidate_pool_size"], label=f"event {event_id} candidate_pool_size") < controls_per_event:
            raise G5MatchQualityGateError(
                f"event {event_id} candidate pool is smaller than required controls"
            )
        summaries[event_id] = row

    if set(summaries) != set(events):
        missing_events = sorted(set(events) - set(summaries))
        extra_events = sorted(set(summaries) - set(events))
        raise G5MatchQualityGateError(
            f"match-event scope mismatch: missing={missing_events[:5]} extra={extra_events[:5]}"
        )

    control_fields, control_rows = _read_csv(matched_controls_path)
    required_control_fields = {
        "event_id",
        "treated_symbol",
        "control_rank",
        "control_symbol",
        "local_date",
        "local_minute",
        "numeric_covariates_used",
        "max_component_z",
        "treated_feature_status",
        "control_feature_status",
        "research_use_only",
    }
    missing = required_control_fields.difference(control_fields)
    if missing:
        raise G5MatchQualityGateError(
            f"matched-controls file missing columns: {sorted(missing)}"
        )

    by_event: dict[str, list[dict[str, str]]] = defaultdict(list)
    weak_match_count = 0
    for row_no, row in enumerate(control_rows, 2):
        event_id = row["event_id"]
        event = events.get(event_id)
        if event is None:
            raise G5MatchQualityGateError(
                f"matched-controls row {row_no}: unknown event_id {event_id}"
            )
        if row["research_use_only"] != "1":
            raise G5MatchQualityGateError(
                f"matched-controls row {row_no}: research_use_only must equal 1"
            )
        treated = row["treated_symbol"].upper()
        control = row["control_symbol"].upper()
        if treated != event["treated_symbol"] or not control or control == treated:
            raise G5MatchQualityGateError(
                f"matched-controls row {row_no}: treated/control identity mismatch"
            )
        if (
            row["local_date"] != event["local_date"]
            or row["local_minute"] != event["local_minute"]
        ):
            raise G5MatchQualityGateError(
                f"matched-controls row {row_no}: date/minute mismatch"
            )
        if control in positives_by_date.get(event["local_date"], set()):
            raise G5MatchQualityGateError(
                f"matched-controls row {row_no}: known positive {control} used as control"
            )
        if _int(
            row["numeric_covariates_used"],
            label=f"matched-controls row {row_no} numeric_covariates_used",
        ) != len(covariates):
            raise G5MatchQualityGateError(
                f"matched-controls row {row_no}: incomplete numeric covariate distance"
            )
        component_z = _float(
            row["max_component_z"],
            label=f"matched-controls row {row_no} max_component_z",
        )
        if component_z > max_component_z + 1e-12:
            raise G5MatchQualityGateError(
                f"matched-controls row {row_no}: component distance exceeds manifest maximum"
            )
        if row["treated_feature_status"] == "insufficient" or row["control_feature_status"] == "insufficient":
            raise G5MatchQualityGateError(
                f"matched-controls row {row_no}: insufficient feature history"
            )
        weak_match_count += int(row.get("match_quality", "") == "weak")
        by_event[event_id].append(row)

    expected_control_rows = len(events) * controls_per_event
    if len(control_rows) != expected_control_rows:
        raise G5MatchQualityGateError(
            f"matched-control row count {len(control_rows)} != expected {expected_control_rows}"
        )

    for event_id in sorted(events):
        rows = by_event.get(event_id, [])
        if len(rows) != controls_per_event:
            raise G5MatchQualityGateError(
                f"event {event_id}: expected {controls_per_event} controls, found {len(rows)}"
            )
        ranks = sorted(
            _int(row["control_rank"], label=f"event {event_id} control_rank")
            for row in rows
        )
        if ranks != list(range(1, controls_per_event + 1)):
            raise G5MatchQualityGateError(
                f"event {event_id}: control ranks are not exactly 1..{controls_per_event}"
            )
        symbols = [row["control_symbol"].upper() for row in rows]
        if len(symbols) != len(set(symbols)):
            raise G5MatchQualityGateError(
                f"event {event_id}: duplicate control symbols"
            )

    balance_fields, balance_rows = _read_csv(match_balance_path)
    required_balance_fields = {
        "covariate",
        "treated_n",
        "candidate_n",
        "matched_n",
        "smd_before",
        "smd_after",
        "maximum_abs_smd",
        "research_use_only",
    }
    missing = required_balance_fields.difference(balance_fields)
    if missing:
        raise G5MatchQualityGateError(
            f"match-balance file missing columns: {sorted(missing)}"
        )

    balances: dict[str, dict[str, str]] = {}
    hard_violations: list[dict[str, object]] = []
    preferred_violations: list[str] = []
    preferred_smd = float((manifest.get("balance_policy") or {}).get("preferred_abs_smd_max", hard_smd))
    for row_no, row in enumerate(balance_rows, 2):
        covariate = row["covariate"]
        if not covariate or covariate in balances:
            raise G5MatchQualityGateError(
                f"match-balance row {row_no}: covariate must be unique and nonblank"
            )
        if row["research_use_only"] != "1":
            raise G5MatchQualityGateError(
                f"match-balance row {row_no}: research_use_only must equal 1"
            )
        if abs(_float(row["maximum_abs_smd"], label=f"balance {covariate} maximum_abs_smd") - hard_smd) > 1e-12:
            raise G5MatchQualityGateError(
                f"balance {covariate}: hard SMD limit disagrees with manifest"
            )
        if _int(row["treated_n"], label=f"balance {covariate} treated_n") != len(events):
            raise G5MatchQualityGateError(
                f"balance {covariate}: treated_n does not cover every event"
            )
        if _int(row["matched_n"], label=f"balance {covariate} matched_n") != expected_control_rows:
            raise G5MatchQualityGateError(
                f"balance {covariate}: matched_n does not cover every matched control"
            )
        if _int(row["candidate_n"], label=f"balance {covariate} candidate_n") < expected_control_rows:
            raise G5MatchQualityGateError(
                f"balance {covariate}: candidate_n is unexpectedly smaller than matched_n"
            )
        _float(row["smd_before"], label=f"balance {covariate} smd_before")
        after = abs(_float(row["smd_after"], label=f"balance {covariate} smd_after"))
        if after > hard_smd + 1e-12:
            hard_violations.append({"covariate": covariate, "abs_smd_after": after})
        if after > preferred_smd + 1e-12:
            preferred_violations.append(covariate)
        balances[covariate] = row

    if set(balances) != set(covariates):
        missing_covariates = sorted(set(covariates) - set(balances))
        extra_covariates = sorted(set(balances) - set(covariates))
        raise G5MatchQualityGateError(
            f"balance covariate scope mismatch: missing={missing_covariates} extra={extra_covariates}"
        )
    if hard_violations:
        raise G5MatchQualityGateError(
            f"post-match balance exceeds hard SMD limit {hard_smd}: {hard_violations}"
        )

    outputs = manifest.get("outputs") or {}
    if int(outputs.get("event_count", -1)) != len(events):
        raise G5MatchQualityGateError("match manifest event_count disagrees with historical events")
    if int(outputs.get("matched_control_rows", -1)) != len(control_rows):
        raise G5MatchQualityGateError("match manifest matched_control_rows disagrees with file")
    if int(outputs.get("balance_rows", -1)) != len(balance_rows):
        raise G5MatchQualityGateError("match manifest balance_rows disagrees with file")
    status_counts = outputs.get("event_status_counts") or {}
    if status_counts != {"matched": len(events)}:
        raise G5MatchQualityGateError(
            f"match manifest event status is not fully matched: {status_counts}"
        )

    result = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Fail-closed G5 matched-control quality gate. It proves complete three-control "
            "event coverage, deterministic rank/identity integrity, same-date/minute alignment, "
            "known-positive contamination exclusion, complete numeric matching covariates, "
            "and post-match standardized-mean-difference balance within the declared hard limit."
        ),
        "research_use_only": True,
        "ready_for_g5_model_evaluation": True,
        "event_count": len(events),
        "controls_per_event": controls_per_event,
        "matched_control_row_count": len(control_rows),
        "expected_matched_control_row_count": expected_control_rows,
        "numeric_covariate_count": len(covariates),
        "numeric_covariates": covariates,
        "hard_abs_smd_max": hard_smd,
        "preferred_abs_smd_max": preferred_smd,
        "preferred_smd_violation_covariates": sorted(preferred_violations),
        "weak_match_count": weak_match_count,
        "known_positive_control_violation_count": 0,
        "hard_balance_violation_count": 0,
        "inputs": {
            "historical_events": {
                "path": str(historical_events_path),
                "sha256": _sha256(historical_events_path),
            },
            "matched_controls": {
                "path": str(matched_controls_path),
                "sha256": _sha256(matched_controls_path),
            },
            "match_events": {
                "path": str(match_events_path),
                "sha256": _sha256(match_events_path),
            },
            "match_balance": {
                "path": str(match_balance_path),
                "sha256": _sha256(match_balance_path),
            },
            "match_manifest": {
                "path": str(match_manifest_path),
                "sha256": _sha256(match_manifest_path),
            },
        },
        "policy": {
            "all_historical_events_must_be_matched": True,
            "exact_controls_per_event_required": True,
            "control_ranks_must_be_unique_and_complete": True,
            "control_symbols_must_be_unique_within_event": True,
            "known_positive_same_day_controls_prohibited": True,
            "all_numeric_matching_covariates_required_per_match": True,
            "post_match_abs_smd_must_not_exceed_hard_limit": True,
            "preferred_smd_limit_is_diagnostic_not_blocking": True,
            "gate_does_not_modify_canonical_g5_readiness": True,
        },
        "canonical_g5_readiness_modified": False,
        "release_claimed": False,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a completed G5 matched-control set before model evaluation."
    )
    parser.add_argument("--historical-events", type=Path, required=True)
    parser.add_argument("--matched-controls", type=Path, required=True)
    parser.add_argument("--match-events", type=Path, required=True)
    parser.add_argument("--match-balance", type=Path, required=True)
    parser.add_argument("--match-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(
        historical_events_path=args.historical_events,
        matched_controls_path=args.matched_controls,
        match_events_path=args.match_events,
        match_balance_path=args.match_balance,
        match_manifest_path=args.match_manifest,
        output_path=args.output,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
