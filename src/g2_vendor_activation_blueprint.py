from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VENDOR_DIR = Path("data/processed/g2_vendor_requests")
DEFAULT_BLUEPRINT = Path(
    "data/processed/real_data_release_sprint/production_source_contract_blueprint.json"
)

ROUTES = {
    "candidate_tickdata_equity_trades": {
        "vendor": "Tick Data",
        "request_file": "tickdata_equity_trades.csv",
        "source_family": "generic_authorized_market_data",
        "record_kind": "equity_trade",
    },
    "candidate_tickdata_equity_nbbo_quotes": {
        "vendor": "Tick Data",
        "request_file": "tickdata_equity_nbbo_quotes.csv",
        "source_family": "generic_authorized_market_data",
        "record_kind": "equity_quote",
    },
    "candidate_databento_opra_trades": {
        "vendor": "Databento",
        "request_file": "databento_opra_trades.csv",
        "source_family": "generic_authorized_market_data",
        "record_kind": "option_trade",
    },
    "candidate_cboe_option_trades": {
        "vendor": "Cboe DataShop",
        "request_file": "cboe_option_trades.csv",
        "source_family": "cboe_option_trades",
        "record_kind": "option_trade",
    },
    "candidate_lseg_opra_tick_history": {
        "vendor": "LSEG Tick History",
        "request_file": "lseg_opra_tick_history.csv",
        "source_family": "generic_authorized_market_data",
        "record_kind": "option_trade",
    },
}


def _manifest_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_blueprint(vendor_dir: Path, source_blueprint: Path) -> dict:
    canonical = _read_json(source_blueprint)
    source_types = canonical["source_types"]
    profiles = []

    total_rows = 0
    total_pairs = 0
    for route, cfg in ROUTES.items():
        request_path = vendor_dir / cfg["request_file"]
        rows = _read_csv(request_path)
        if not rows:
            raise ValueError(f"{request_path}: empty vendor request manifest")
        if {row["route"] for row in rows} != {route}:
            raise ValueError(f"{request_path}: route mismatch")
        if {row["record_kind"] for row in rows} != {cfg["record_kind"]}:
            raise ValueError(f"{request_path}: record_kind mismatch")

        pair_count = sum(int(row["symbol_date_pair_count"]) for row in rows)
        source_date_rows = len(rows)
        total_rows += source_date_rows
        total_pairs += pair_count

        required_fields = source_types[cfg["record_kind"]]["required_canonical_fields"]
        profiles.append(
            {
                "route": route,
                "vendor": cfg["vendor"],
                "request_file": _manifest_path(request_path),
                "record_kind": cfg["record_kind"],
                "source_family": cfg["source_family"],
                "source_date_rows": source_date_rows,
                "symbol_date_pair_count": pair_count,
                "required_canonical_fields": required_fields,
                "delivery": {
                    "path": "",
                    "license_reference": "",
                    "format_version": "",
                    "delimiter": "",
                    "encoding": "utf-8",
                    "timezone": "America/New_York",
                },
                "entitlement_template": {
                    "sha256": "",
                    "authorized": False,
                    "license_reference": "",
                    "source_family": cfg["source_family"],
                    "record_kind": cfg["record_kind"],
                    "trade_date": "",
                    "delimiter": "",
                    "encoding": "utf-8",
                    "timezone": "America/New_York",
                    "format_version": "",
                },
                "activation_status": "PENDING_DELIVERY_LICENSE_SCHEMA_REVIEW",
                "activation_rules": {
                    "exact_sha256_binding_required": True,
                    "authorized_must_be_explicitly_true_after_review": True,
                    "license_reference_required": True,
                    "intake_schema_must_match_entitlement": True,
                    "file_existence_alone_never_counts_as_coverage": True,
                },
            }
        )

    profiles.sort(key=lambda profile: profile["route"])

    return {
        "schema_version": "1",
        "purpose": (
            "Fail-closed activation blueprint for G2_CHAMPION_MINIMUM vendor deliveries. "
            "This artifact is planning-only and cannot authorize, activate, or count coverage."
        ),
        "champion_minimum_source_date_rows": total_rows,
        "total_record_kind_symbol_date_pairs": total_pairs,
        "profiles": profiles,
        "global_policy": {
            "authorized_defaults_false": True,
            "blank_delivery_path_required_until_file_exists": True,
            "blank_license_reference_required_until_entitlement_is_known": True,
            "credentials_prohibited": True,
            "local_entitlement_manifest_not_committed_when_populated": True,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build fail-closed activation blueprint for G2 vendor deliveries."
    )
    parser.add_argument("--vendor-dir", type=Path, default=DEFAULT_VENDOR_DIR)
    parser.add_argument("--source-blueprint", type=Path, default=DEFAULT_BLUEPRINT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    payload = build_blueprint(args.vendor_dir, args.source_blueprint)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
