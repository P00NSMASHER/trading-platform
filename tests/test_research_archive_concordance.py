"""Synthetic adversarial source-concordance tests; no broker or raw prices."""
from dataclasses import replace
from datetime import date, timedelta

import pytest

from research_archive_concordance import Bar, InvalidArchive, compare_archives, git_blob_id, load_bars


def sample():
    ds = [date(2020, 1, d) for d in (2, 3, 6, 7, 8, 9)]
    return [Bar(d, 100, 101, 99, 100) for d in ds]


def test_same_source_zero_disagreements_and_not_profit():
    r = compare_archives(sample(), sample())
    assert r["shared_sessions"] == 6
    assert r["overnight_gap_difference_over_5bps"] == 0
    assert r["signal_conflicts"] == []
    assert "NOT_INDEPENDENT" in r["status"]


def test_constant_price_scaling_changes_levels_not_returns():
    x = sample()
    y = [Bar(b.day, b.open * .8, b.high * .8, b.low * .8, b.close * .8) for b in x]
    result = compare_archives(x, y)
    assert result["raw_close_ratio_first"] == pytest.approx(.8)
    assert result["max_intraday_difference_bps"] == pytest.approx(0, abs=1e-8)
    assert result["max_overnight_gap_difference_bps"] == pytest.approx(0, abs=1e-8)


def test_changed_adjustment_factor_relabels_prior_gap_without_lookahead():
    x = sample()
    # Adjust all prices from 2020-01-06 onward by 1.02.
    # Close/Open stays identical, but Jan 6 overnight source gap rises 200bps.
    y = [replace(b, open=b.open * 1.02, high=b.high * 1.02,
                 low=b.low * 1.02, close=b.close * 1.02) if i >= 2 else b
         for i, b in enumerate(x)]
    result = compare_archives(x, y)
    assert result["overnight_gap_difference_over_5bps"] == 1
    assert result["max_intraday_difference_bps"] == pytest.approx(0, abs=1e-8)
    assert result["signal_conflicts"] == [{"entry_day": "2020-01-07", "signal_day": "2020-01-06",
                                           "side": "long", "primary_gap_bps": 0.0,
                                           "secondary_gap_bps": 200.0}]
    long = result["phases"]["retrospective"]["long"]
    assert long["primary"] == 0 and long["secondary"] == 1
    assert long["secondary_mean_net_20bps"] == -20


def test_missing_session_is_not_silently_forward_filled():
    with pytest.raises(InvalidArchive, match="calendar"):
        compare_archives(sample(), sample()[:3] + sample()[4:])


@pytest.mark.parametrize("kind", ["duplicate", "reverse", "weekend", "nan", "impossible"])
def test_direct_call_bad_source_rejected(kind):
    x = sample()
    if kind == "duplicate":
        x[1] = replace(x[1], day=x[0].day)
    elif kind == "reverse":
        x[1] = replace(x[1], day=date(2020, 1, 1))
    elif kind == "weekend":
        x[1] = replace(x[1], day=date(2020, 1, 4))
    elif kind == "nan":
        x[1] = replace(x[1], close=float("nan"))
    else:
        x[1] = replace(x[1], low=102)
    with pytest.raises(InvalidArchive):
        compare_archives(x, sample())


def test_no_shared_history_fails_closed():
    y = [replace(b, day=b.day + timedelta(days=364)) for b in sample()]
    with pytest.raises(InvalidArchive, match="overlapping"):
        compare_archives(sample(), y)


def test_pinned_csv_rejects_tamper_even_if_csv_is_parseable(tmp_path):
    raw = (b"Date,Open,High,Low,Close\n"
           b"2020-01-02,100,101,99,100\n"
           b"2020-01-03,100,101,99,100\n"
           b"2020-01-06,100,101,99,100\n")
    file = tmp_path / "bars.csv"
    file.write_bytes(raw)
    assert len(load_bars(file, git_blob_id(raw))) == 3
    file.write_bytes(raw.replace(b"101", b"102"))
    with pytest.raises(InvalidArchive, match="pinned"):
        load_bars(file, git_blob_id(raw))


def test_reject_duplicate_headers_and_invalid_sha(tmp_path):
    raw = b"Date,Open,High,Low,Close,Close\n2020-01-02,100,101,99,100,100\n"
    file = tmp_path / "bars.csv"
    file.write_bytes(raw)
    with pytest.raises(InvalidArchive, match="duplicate"):
        load_bars(file, git_blob_id(raw))
    with pytest.raises(InvalidArchive, match="SHA"):
        load_bars(file, "main")


def test_reject_oversized_before_read(tmp_path):
    file = tmp_path / "bars.csv"
    with file.open("wb") as f:
        f.truncate(10_000_001)
    with pytest.raises(InvalidArchive, match="byte limit"):
        load_bars(file, "a" * 40)


def test_phase_has_no_future_date_dependency():
    x = sample()
    y = sample()
    result = compare_archives(x, y)
    assert result["phases"]["train"]["long"]["eligible"] == 0
    assert result["phases"]["retrospective"]["long"]["eligible"] == 4
