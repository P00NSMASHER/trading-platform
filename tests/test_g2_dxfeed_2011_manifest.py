from pathlib import Path

import g2_dxfeed_2011_manifest as manifest


ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = (
    ROOT / "data/processed/real_data_release_sprint/g2_option_source_date_requirements.csv"
)


def test_dxfeed_2011_manifest_matches_frozen_residual():
    payload = manifest.build_manifest(manifest._read(REQUIREMENTS))

    assert payload["source_date_count"] == 105
    assert payload["underlying_date_pair_count"] == 464
    assert payload["date_floor"] == "2011-03-21"
    assert payload["date_ceiling"] == "2011-12-30"
    assert payload["required_record_kinds"] == ["option_trade", "option_quote"]
    assert payload["validated_coverage_change"] == 0

    tasks = payload["tasks"]
    assert len(tasks) == 464
    assert len({(row["trade_date"], row["historical_symbol"]) for row in tasks}) == 464
    assert tasks[0]["trade_date"] == "2011-03-21"
    assert tasks[0]["historical_symbol"] == "JNPR"
    assert tasks[1]["trade_date"] == "2011-03-21"
    assert tasks[1]["historical_symbol"] == "VMW"
    assert all(row["authorization_required"] is True for row in tasks)
    assert all(row["retention_rights_required"] is True for row in tasks)
    assert all(row["validated_coverage"] is False for row in tasks)


def test_dxfeed_2011_manifest_fails_closed_on_trade_quote_symbol_mismatch():
    rows = manifest._read(REQUIREMENTS)
    altered = [dict(row) for row in rows]

    for row in altered:
        if row["record_kind"] == "option_quote" and row["trade_date"] == "2011-03-21":
            row["historical_symbols"] = "JNPR"
            row["unique_symbol_count"] = "1"
            row["symbol_date_pair_count"] = "1"
            break

    try:
        manifest.build_manifest(altered)
    except ValueError as exc:
        assert "symbol sets differ" in str(exc)
    else:
        raise AssertionError("trade/quote mismatch must fail closed")


def test_dxfeed_2011_manifest_writes_deterministic_vendor_files(tmp_path):
    payload = manifest.build_manifest(manifest._read(REQUIREMENTS))
    manifest.write_manifest(payload, tmp_path)

    csv_path = tmp_path / "dxfeed_2011_option_tasks.csv"
    summary_path = tmp_path / "dxfeed_2011_option_summary.json"

    assert csv_path.exists()
    assert summary_path.exists()

    csv_text = csv_path.read_text(encoding="utf-8")
    summary_text = summary_path.read_text(encoding="utf-8")

    assert "2011-03-21,JNPR,option_trade;option_quote" in csv_text
    assert '"source_date_count": 105' in summary_text
    assert '"underlying_date_pair_count": 464' in summary_text
    assert '"validated_coverage_change": 0' in summary_text
