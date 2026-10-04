from datetime import datetime

import g2_taq_afterhours_replication as taq


def test_trade_condition_exclusions_match_companion_readme():
    for code in ("L", "P", "U", "Z", "4"):
        row = {"tr_scon": code}
        assert taq.keep_trade_for_replication(row) is False
        assert taq.trade_rejection_reason(row) == f"excluded_tr_scon:{code}"


def test_after_hours_T_is_identified_but_not_excluded():
    row = {"tr_scon": "T"}
    assert taq.is_after_hours_trade(row) is True
    assert taq.keep_trade_for_replication(row) is True


def test_compact_and_delimited_trade_conditions_are_equivalent():
    assert taq.condition_codes("T;Z") == {"T", "Z"}
    assert taq.condition_codes("TZ") == {"T", "Z"}
    assert taq.keep_trade_for_replication({"tr_scon": "T;Z"}) is False


def test_quote_closing_condition_C_is_recognized():
    flags = taq.quote_replication_flags(
        {"qu_cond": "C", "Bid": 10, "Ask": 10.2, "Bidsiz": 5, "Asksiz": 6}
    )
    assert flags["closing_condition"] is True


def test_empty_quotes_are_retained_in_after_hours_replication():
    row = {"qu_cond": "", "Bid": 0, "Ask": 0, "Bidsiz": 0, "Asksiz": 0}
    flags = taq.quote_replication_flags(row)
    assert flags["empty_quote"] is True
    assert taq.keep_quote_for_replication(row) is True


def test_crossed_quotes_are_retained():
    row = {"Bid": 10.5, "Ask": 10.0, "Bidsiz": 5, "Asksiz": 5}
    flags = taq.quote_replication_flags(row)
    assert flags["crossed_market"] is True
    assert flags["retain_for_after_hours_replication"] is True


def test_wide_spreads_are_retained():
    row = {"Bid": 10.0, "Ask": 20.0, "Bidsiz": 5, "Asksiz": 5}
    flags = taq.quote_replication_flags(row)
    assert flags["wide_spread_over_5"] is True
    assert flags["retain_for_after_hours_replication"] is True


def test_withdrawn_quotes_are_retained():
    row = {"Bid": ".", "Ask": 10.2, "Bidsiz": ".", "Asksiz": 5}
    flags = taq.quote_replication_flags(row)
    assert flags["withdrawn_bid"] is True
    assert flags["withdrawn_ask"] is False
    assert taq.keep_quote_for_replication(row) is True


def test_extended_hours_window_matches_trth_replication_envelope():
    assert taq.in_research_extended_hours("2015-02-12T04:00:00") is True
    assert taq.in_research_extended_hours("2015-02-12T20:00:00") is True
    assert taq.in_research_extended_hours("2015-02-12T03:59:59") is False
    assert taq.in_research_extended_hours("2015-02-12T20:00:01") is False


def test_filter_trade_rows_can_limit_to_extended_hours_and_marks_T():
    rows = [
        {"timestamp": "2015-02-12T03:00:00", "tr_scon": "T", "id": 1},
        {"timestamp": "2015-02-12T16:00:00", "tr_scon": "T", "id": 2},
        {"timestamp": "2015-02-12T17:00:00", "tr_scon": "Z", "id": 3},
    ]
    out = taq.filter_trade_rows(rows, extended_hours_only=True)
    assert [row["id"] for row in out] == [2]
    assert out[0]["after_hours_condition_T"] is True


def test_quote_annotation_never_claims_g2_coverage():
    rows = [{"timestamp": "2015-02-12T17:00:00", "Bid": 10, "Ask": 9, "Bidsiz": 1, "Asksiz": 1}]
    out = taq.annotate_quote_rows(rows)
    assert out[0]["taq_replication_retained"] is True
    assert out[0]["taq_replication_flags"]["crossed_market"] is True
    assert out[0]["g2_coverage_claim"] is False


def test_policy_summary_remains_fail_closed_for_nbbo():
    summary = taq.replication_policy_summary()
    assert summary["trade_excluded_tr_scon"] == ["4", "L", "P", "U", "Z"]
    assert summary["after_hours_trade_condition"] == "T"
    assert summary["quote_valid_condition_addition"] == "C"
    assert summary["nbbo_required_before_g2_quote_coverage"] is True
    assert summary["g2_coverage_claim"] is False
