import json
import urllib.parse
from pathlib import Path

import g2_cboe_trial_bulk_runner as runner


ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "data/processed/real_data_release_sprint/g2_option_source_date_requirements.csv"


def test_trial_task_plan_covers_full_vendor_confirmed_2012_2015_scope():
    tasks = runner.build_trial_tasks(runner._read_requirements(REQ))
    manifest = runner.build_dry_run_manifest(tasks)

    assert len(tasks) == 3364
    assert manifest["eligible_dates"] == 309
    assert manifest["underlying_date_tasks"] == 3364
    assert manifest["first_date"] == "2012-01-03"
    assert manifest["last_date"] == "2015-05-20"
    assert manifest["source_date_rows_targeted"] == {
        "option_trade": 309,
        "option_quote": 309,
    }
    assert manifest["page_limit"] == 10000
    assert manifest["coverage_claimed"] is False
    assert manifest["runtime_safety"]["execute_requires_explicit_ack"] == "--ack-trial-active"
    assert (
        manifest["runtime_safety"]["execute_requires_retention_ack"]
        == "--ack-retention-authorized"
    )
    assert manifest["runtime_safety"]["retention_authority"] == {
        "required": True,
        "state": "PENDING_WRITTEN_VENDOR_CONFIRMATION",
        "definition": (
            "Written Cboe Order Form or vendor permission allowing retained "
            "internal research use after trial termination."
        ),
    }
    assert manifest["runtime_safety"]["no_coverage_promotion"] is True


def test_osi_symbol_generation_matches_cboe_compact_format():
    assert (
        runner.osi_symbol("AAPL", "2021-03-05", "C", "70")
        == "AAPL210305C00070000"
    )
    assert (
        runner.osi_symbol("AF", "2012-01-21", "P", "10.5")
        == "AF120121P00010500"
    )


def test_urls_are_historical_bounded_and_do_not_contain_credentials():
    task = runner.TrialTask("2012-01-03", "AF")
    trade_url = runner._option_trades_url(task, 123)
    quote_url = runner._option_quotes_url(task, "AF120121C00010000", 456)
    ref_url = runner._reference_options_url(task)

    trade = urllib.parse.parse_qs(urllib.parse.urlparse(trade_url).query, keep_blank_values=True)
    quote = urllib.parse.parse_qs(urllib.parse.urlparse(quote_url).query, keep_blank_values=True)
    ref = urllib.parse.parse_qs(urllib.parse.urlparse(ref_url).query, keep_blank_values=True)

    assert trade["date"] == ["2012-01-03"]
    assert trade["symbol"] == ["AF"]
    assert trade["seq_no"] == ["123"]
    assert trade["limit"] == ["10000"]
    assert trade["min_time"] == ["00:00:00.000"]
    assert trade["max_time"] == ["23:59:59.999"]

    assert quote["date"] == ["2012-01-03"]
    assert quote["symbol"] == ["AF120121C00010000"]
    assert quote["start_sequence_number"] == ["456"]
    assert quote["limit"] == ["10000"]

    assert ref == {"date": ["2012-01-03"], "symbol": ["AF"]}
    for url in (trade_url, quote_url, ref_url):
        assert "client" not in url.lower()
        assert "secret" not in url.lower()
        assert "token" not in url.lower()


def test_reference_options_enumerates_contracts_not_only_traded_contracts():
    payload = [
        {"root": "AF", "expiry": "2012-01-21", "strike": 10, "type": "C"},
        {"root": "AF", "expiry": "2012-01-21", "strike": 10, "type": "P"},
        {"root": "AF", "expiry": "2012-02-18", "strike": 12.5, "type": "C"},
    ]
    contracts = runner._contracts_from_reference(payload)
    assert contracts == [
        "AF120121C00010000",
        "AF120121P00010000",
        "AF120218C00012500",
    ]


def test_pagination_advances_from_max_sequence_and_stops_on_short_page():
    calls = []

    def url_for_cursor(cursor):
        return f"https://example.test?cursor={cursor}"

    first = [
        {"seq_no": i, "x": i}
        for i in range(100, 103)
    ]
    second = [{"seq_no": 200, "x": 200}]

    def getter(url):
        calls.append(url)
        if "cursor=0" in url:
            return first
        if "cursor=103" in url:
            return second
        raise AssertionError(url)

    rows, pages = runner.collect_paginated(
        url_for_cursor,
        getter,
        limit=3,
        max_pages=3,
    )
    assert pages == 2
    assert rows == first + second
    assert calls == [
        "https://example.test?cursor=0",
        "https://example.test?cursor=103",
    ]


def test_pagination_fails_closed_when_full_page_has_no_sequence():
    def getter(_url):
        return [{"timestamp": "x"}, {"timestamp": "y"}]

    try:
        runner.collect_paginated(
            lambda cursor: f"https://example.test?cursor={cursor}",
            getter,
            limit=2,
            max_pages=2,
        )
    except ValueError as exc:
        assert "missing seq_no" in str(exc)
    else:
        raise AssertionError("expected fail-closed pagination error")


def test_valid_receipt_is_resumable_and_hash_sensitive(tmp_path: Path):
    task = runner.TrialTask("2012-01-03", "AF")
    task_dir = tmp_path / task.trade_date / task.historical_symbol
    task_dir.mkdir(parents=True)

    runner._write_json(
        task_dir / "contracts.json",
        {"contracts": ["AF120121C00010000"]},
    )
    runner._write_jsonl_gz(
        task_dir / "option_trades.jsonl.gz",
        [{"seq_no": 1, "security": "AF120121C00010000"}],
    )
    runner._write_jsonl_gz(
        task_dir / "option_quotes.jsonl.gz",
        [{"seq_no": 2, "security": "AF120121C00010000"}],
    )

    files = {}
    for name in ("contracts.json", "option_trades.jsonl.gz", "option_quotes.jsonl.gz"):
        path = task_dir / name
        files[name] = {
            "sha256": runner._sha256_file(path),
            "size_bytes": path.stat().st_size,
        }

    runner._write_json(
        task_dir / "receipt.json",
        {
            "status": "downloaded_pending_content_validation",
            "trade_date": task.trade_date,
            "historical_symbol": task.historical_symbol,
            "files": files,
            "g2_coverage_change": 0,
        },
    )

    assert runner._receipt_valid(task_dir, task) is True

    with gzip_open_append(task_dir / "option_quotes.jsonl.gz") as handle:
        handle.write(b"tamper")

    assert runner._receipt_valid(task_dir, task) is False


class gzip_open_append:
    def __init__(self, path):
        self.path = path
        self.handle = None

    def __enter__(self):
        self.handle = self.path.open("ab")
        return self.handle

    def __exit__(self, exc_type, exc, tb):
        self.handle.close()


def test_execute_slice_is_bounded_and_never_promotes_coverage(monkeypatch, tmp_path: Path):
    tasks = [
        runner.TrialTask("2012-01-03", "AF"),
        runner.TrialTask("2012-01-04", "AF"),
        runner.TrialTask("2012-01-05", "AF"),
    ]
    seen = []

    def fake_download(client, task, output_root):
        seen.append((task.trade_date, task.historical_symbol))
        return {
            "status": "fake",
            "trade_date": task.trade_date,
            "historical_symbol": task.historical_symbol,
            "g2_coverage_change": 0,
        }

    monkeypatch.setattr(runner, "download_task", fake_download)
    result = runner.execute_slice(
        object(),
        tasks,
        tmp_path,
        start=1,
        limit=1,
    )

    assert seen == [("2012-01-04", "AF")]
    assert result["tasks_selected"] == 1
    assert result["tasks_total"] == 3
    assert result["validation_promoted"] is False
    assert result["g2_coverage_change"] == 0


def test_dry_run_output_contains_no_credentials():
    tasks = runner.build_trial_tasks(runner._read_requirements(REQ))
    rendered = json.dumps(runner.build_dry_run_manifest(tasks))
    assert "CBOE_CLIENT_SECRET" in rendered
    assert "access_token" not in rendered
    assert "client-secret" not in rendered
