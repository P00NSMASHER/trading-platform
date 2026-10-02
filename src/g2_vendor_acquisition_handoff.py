from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

DEFAULT_REQUEST_DIR = Path(
    "data/processed/real_data_release_sprint/vendor_requests"
)
DEFAULT_BLUEPRINT = Path(
    "data/processed/real_data_release_sprint/production_source_contract_blueprint.json"
)

ROUTES = {
    "candidate_tickdata_equity_trades": {
        "vendor": "Tick Data",
        "product": "U.S. Equities tick trades",
        "record_kind": "equity_trade",
        "source_family": "generic_authorized_market_data",
        "request_file": "tickdata_equity_trades.csv",
        "fidelity_requirement": "tick-by-tick U.S. equity trades; no aggregate-bar substitution",
    },
    "candidate_tickdata_equity_nbbo_quotes": {
        "vendor": "Tick Data",
        "product": "NBBO for U.S. Equities",
        "record_kind": "equity_quote",
        "source_family": "generic_authorized_market_data",
        "request_file": "tickdata_equity_nbbo_quotes.csv",
        "fidelity_requirement": (
            "tick-by-tick consolidated NBBO quote updates; interval snapshots do not satisfy "
            "the frozen equity-spread semantics"
        ),
    },
    "candidate_databento_opra_trades": {
        "vendor": "Databento",
        "product": "OPRA.PILLAR trades",
        "record_kind": "option_trade",
        "source_family": "generic_authorized_market_data",
        "request_file": "databento_opra_trades.csv",
        "fidelity_requirement": "trade-level OPRA records with exact price and size",
    },
    "candidate_cboe_option_trades": {
        "vendor": "Cboe DataShop",
        "product": "Option Trades",
        "record_kind": "option_trade",
        "source_family": "cboe_option_trades",
        "request_file": "cboe_option_trades.csv",
        "fidelity_requirement": "trade-level option records with exact price and size",
    },
    "candidate_lseg_opra_tick_history": {
        "vendor": "LSEG",
        "product": "OPRA Tick History",
        "record_kind": "option_trade",
        "source_family": "generic_authorized_market_data",
        "request_file": "lseg_opra_tick_history.csv",
        "fidelity_requirement": "full-tick OPRA last-sale records with exact price and size",
    },
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [{str(k): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(handle)]


def build_handoff(request_dir: Path, blueprint_path: Path) -> dict:
    blueprint = json.loads(blueprint_path.read_text(encoding="utf-8"))
    authorization = blueprint["authorization"]
    validation = blueprint["content_validation"]
    source_types = blueprint["source_types"]

    handoffs = {}
    total_rows = 0
    total_pairs = 0
    for route, spec in ROUTES.items():
        rows = _read_csv(request_dir / spec["request_file"])
        if not rows:
            raise ValueError(f"{route}: request file is empty")
        if {row["record_kind"] for row in rows} != {spec["record_kind"]}:
            raise ValueError(f"{route}: unexpected record_kind")
        if {row["route"] for row in rows} != {route}:
            raise ValueError(f"{route}: route column mismatch")

        dates = sorted(row["trade_date"] for row in rows)
        symbols = set()
        for row in rows:
            symbols.update(x for x in row["historical_symbols"].split(";") if x)

        pair_count = sum(int(row["symbol_date_pair_count"]) for row in rows)
        source_schema = source_types[spec["record_kind"]]
        if spec["source_family"] not in source_schema["accepted_families"]:
            raise ValueError(f"{route}: source family is not accepted by production blueprint")

        handoffs[route] = {
            "status": "CANDIDATE_SOURCE_AVAILABLE_NOT_ACQUIRED",
            "vendor": spec["vendor"],
            "product": spec["product"],
            "record_kind": spec["record_kind"],
            "source_family_for_contract": spec["source_family"],
            "request_manifest": spec["request_file"],
            "first_trade_date": dates[0],
            "last_trade_date": dates[-1],
            "source_date_rows": len(rows),
            "symbol_date_pair_count": pair_count,
            "distinct_historical_symbols": len(symbols),
            "required_canonical_fields": source_schema["required_canonical_fields"],
            "fidelity_requirement": spec["fidelity_requirement"],
            "delivery_contract": {
                "authorized": True,
                "data_classification": authorization["non_synthetic_class"],
                "license_reference": "REQUIRED_NONEMPTY",
                "credentials_in_contract": "PROHIBITED",
                "trade_date": "REQUIRED_PER_SOURCE_FILE_OR_SHARD",
                "timezone": "REQUIRED",
                "format_version": "REQUIRED",
                "column_map": "REQUIRED_WHEN_VENDOR_FIELDS_ARE_NOT_CANONICAL",
            },
            "post_activation_content_preflight": {
                "module": "g2_vendor_content_preflight",
                "request_manifest": spec["request_file"],
                "required_result": "ready_for_coverage_audit=true",
                "g2_coverage_counted": False,
            },
            "acceptance_checks": {
                "file_existence_is_not_coverage": validation["file_existence_is_not_coverage"],
                "declared_trade_date_must_match_parsed_rows": validation[
                    "declared_trade_date_must_match_parsed_rows"
                ],
                "all_required_symbols_must_be_observed": validation[
                    "all_required_symbols_must_be_observed"
                ],
                "synthetic_rows_never_satisfy_G2": validation[
                    "synthetic_rows_never_satisfy_G2"
                ],
                "production_parser_must_accept_required_fields": True,
            },
        }
        total_rows += len(rows)
        total_pairs += pair_count

    return {
        "schema_version": "1",
        "purpose": (
            "Vendor handoff contract for acquiring G2_CHAMPION_MINIMUM source files. "
            "Candidate availability is not a coverage claim."
        ),
        "champion_minimum_source_date_rows": total_rows,
        "total_record_kind_symbol_date_pairs": total_pairs,
        "credential_policy": "Credentials must never be stored in request manifests or source contracts.",
        "coverage_policy": (
            "A delivered file counts only after authorization/license evidence and production "
            "date/symbol/schema/content validation pass."
        ),
        "operator_sequence": [
            {
                "step": 1,
                "module": "licensed_data_intake",
                "required_result": "delivery inventoried and schema-classified; authorization still false",
            },
            {
                "step": 2,
                "module": "g2_vendor_delivery_preflight",
                "required_result": "ready_for_entitlement_review=true",
            },
            {
                "step": 3,
                "module": "licensed_data_drop_processor",
                "required_result": "exact SHA-256 entitlement binding + nonblank license reference",
            },
            {
                "step": 4,
                "module": "g2_vendor_content_preflight",
                "required_result": "ready_for_coverage_audit=true with every required symbol observed",
            },
            {
                "step": 5,
                "module": "historical_market_backfill / real_data_replay",
                "required_result": "canonical coverage/replay gates evaluate activated sources; no preflight itself counts coverage",
            },
        ],
        "handoffs": handoffs,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build vendor handoff contracts for G2_CHAMPION_MINIMUM."
    )
    parser.add_argument("--request-dir", type=Path, default=DEFAULT_REQUEST_DIR)
    parser.add_argument("--blueprint", type=Path, default=DEFAULT_BLUEPRINT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    payload = build_handoff(args.request_dir, args.blueprint)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
