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


def _q(ts, seq, venue, bid, ask, bs=1, az=1):
    return {"timestamp": ts, "sequence": seq, "venue": venue, "Bid": bid, "Ask": ask, "Bidsiz": bs, "Asksiz": az}


def test_nbbo_orders_timestamp_then_sequence_and_transitions_best_sides():
    rows = [
        _q("2015-02-12T17:00:01", 3, "N", 10, 12),
        _q("2015-02-12T17:00:00", 2, "Q", 11, 13),
        _q("2015-02-12T17:00:00", 1, "N", 9, 14),
    ]
    out = taq.construct_strict_nbbo(rows)
    assert [x["sequence"] for x in out] == [1, 2, 3]
    assert str(out[-1]["nbbo"]["best_bid"]) == "11"
    assert str(out[-1]["nbbo"]["best_ask"]) == "12"


def test_nbbo_withdrawal_reappearance_and_raw_tick_fidelity():
    rows = [
        _q("2015-02-12T17:00:00", 1, "N", "10.00", "11.00", "2", "3"),
        _q("2015-02-12T17:00:01", 2, "Q", "10.50", "11.50"),
        _q("2015-02-12T17:00:02", 3, "N", ".", "11.00", ".", "3"),
        _q("2015-02-12T17:00:03", 4, "N", "10.75", "11.00", "4", "3"),
    ]
    out = taq.construct_strict_nbbo(rows)
    assert out[2]["nbbo"]["best_bid_venue"] == "Q"
    assert out[2]["taq_replication_flags"]["withdrawn_bid"] is True
    assert out[3]["nbbo"]["best_bid_raw"] == "10.75"
    assert out[3]["raw_update"] == rows[3]


def test_crossed_and_incomplete_intermediate_states_are_retained_fail_closed():
    rows = [
        _q("2015-02-12T17:00:00", 1, "N", 11, 10),
        _q("2015-02-12T17:00:01", 2, "N", 0, 10, 0, 1),
        _q("2015-02-12T17:00:02", 3, "N", 9, 10),
    ]
    out = taq.construct_strict_nbbo(rows)
    assert out[0]["nbbo"] is None and out[0]["nbbo_rejection_reason"] == "strict_nbbo_crossed"
    assert out[1]["nbbo"] is None and out[1]["nbbo_rejection_reason"] == "strict_nbbo_incomplete"
    assert out[0]["raw_update"] == rows[0]
    assert out[2]["nbbo"] is not None
    assert all(x["g2_coverage_claim"] is False for x in out)


def test_strict_nbbo_fails_closed_without_unambiguous_ordering_or_two_sides():
    assert taq.strict_nbbo_established([{"timestamp":"2015-02-12T17:00:00","venue":"N","Bid":10,"Ask":11,"Bidsiz":1,"Asksiz":1}]) is False
    rows = [
        _q("2015-02-12T17:00:00", 1, "N", 10, 11),
        _q("2015-02-12T17:00:00", 1, "Q", 10.1, 11.1),
    ]
    assert taq.strict_nbbo_established(rows) is False


def test_wide_spread_can_be_strict_nbbo_without_deleting_raw_evidence():
    row = _q("2015-02-12T17:00:00", 1, "N", 10, 20)
    out = taq.construct_strict_nbbo([row])
    assert out[0]["taq_replication_flags"]["wide_spread_over_5"] is True
    assert out[0]["nbbo"] is not None
