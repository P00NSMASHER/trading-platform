"""Synthetic-only acceptance and adversarial tests. No vendor calls or orders."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import sqlite3

import pytest

from golden_goose_candidates import DebitSpread, screen_debit_spreads
from golden_goose_data import OptionQuote
from golden_goose_signals import SignalResult
from golden_goose_forward_paper import ForwardPaperBook, EvidenceRejected

ET = ZoneInfo("America/New_York")
SOURCE = "tradier_prod_rest_options_paper_only"
BASE = datetime(2026, 1, 5, 10, 45, tzinfo=ET)


def pair(root, expiry, buy_strike, sell_strike, when, long_bid, long_ask,
         short_bid, short_ask):
    def q(strike, bid, ask):
        contract = f"{root}{expiry:%y%m%d}C{int(strike * 1000):08d}"
        return OptionQuote(root, contract, expiry, strike, "C", when, bid,
                           ask, when, when, 1000, 100, SOURCE)
    return [q(buy_strike, long_bid, long_ask),
            q(sell_strike, short_bid, short_ask)]


def fixture(when=BASE):
    expiry = when.astimezone(ET).date() + timedelta(days=11)
    target_quotes = pair("IWM", expiry, 280, 281, when, .37, .40, .24, .25)
    ctrl_quotes = pair("IWM", expiry, 282, 283, when, .42, .50, .25, .28)
    target = screen_debit_spreads(
        target_quotes, side="C", decision=when, equity_usd=1000
    ).candidates[0]
    control = DebitSpread(
        "IWM", expiry, "C", ctrl_quotes[0].contract, ctrl_quotes[1].contract,
        282, 283, 25, 31.6, 68.4, 68.4 / 31.6
    )
    signal = SignalResult("RESEARCH_SIGNAL", "PREREGISTERED_SCREEN_PASSED",
                          "C", when, 2.0, 281.5, 278.5)
    return target, control, signal, target_quotes, ctrl_quotes


def setup(book, start=BASE):
    return book.preregister(
        strategy_hash="a" * 64, benchmark_rule="predeclared_same_expiry_control_v1",
        holdout_start=start - timedelta(days=1),
        registered_at=start - timedelta(days=5),
    )


def admit(book, did="d1", when=BASE, *, target_quotes=None, control_quotes=None,
          received_at=None, planned_exit_at=None, calendar_receipt="XNYS-source",
          catalyst_receipt="timestamped-public-source"):
    target, control, signal, tq, cq = fixture(when)
    return book.admit(
        decision_id=did, signal=signal, target=target, control=control,
        target_quotes=tq if target_quotes is None else target_quotes,
        control_quotes=cq if control_quotes is None else control_quotes,
        received_at=received_at or when + timedelta(seconds=10),
        planned_exit_at=planned_exit_at or when + timedelta(hours=4),
        equity_usd=1000, calendar_receipt=calendar_receipt,
        catalyst_receipt=catalyst_receipt,
    )


def exits(when=BASE):
    expiry = when.astimezone(ET).date() + timedelta(days=11)
    cutoff = when + timedelta(hours=4)
    tq = pair("IWM", expiry, 280, 281, cutoff, 1.20, 1.30, .05, .10)
    cq = pair("IWM", expiry, 282, 283, cutoff, .20, .24, .10, .13)
    return tq, cq


def test_private_journal_tracks_all_four_frozen_legs_and_replays(tmp_path):
    path = tmp_path / "private.sqlite"
    with ForwardPaperBook(path) as book:
        assert setup(book)
        assert not setup(book)
        assert admit(book)
        assert not admit(book)
        due = book.due_contracts(BASE + timedelta(hours=4))
        assert len(due) == 1 and due[0]["due"]
        assert len(due[0]["contracts"]) == 4
        assert book.report().status == "INSUFFICIENT_PROSPECTIVE_EVIDENCE"
        assert book.report().awaiting_exit == 1
        head = book.head_hash()
    with ForwardPaperBook(path) as reopened:
        assert reopened.head_hash() == head
        assert len(reopened.due_contracts(BASE)) == 1
    assert path.stat().st_mode & 0o077 == 0


def test_exit_conservative_bid_ask_and_frozen_control(tmp_path):
    with ForwardPaperBook(tmp_path / "book.sqlite") as book:
        setup(book)
        admit(book)
        tq, cq = exits()
        assert book.reconcile_exit("d1", target_quotes=tq, control_quotes=cq,
                                   received_at=BASE + timedelta(hours=4, seconds=10))
        assert book.due_contracts(BASE + timedelta(hours=5)) == ()
        row = [ev for _, kind, ev in book.events() if kind == "EXIT"][0]
        assert row["target"]["pnl_usd"] == pytest.approx(87.4)
        assert row["control"]["pnl_usd"] == pytest.approx(-24.6)
        assert row["risk_scaled_control_pnl_usd"] == pytest.approx(-17.59)
        assert row["excess_pnl_usd"] == pytest.approx(104.99)
        assert book.report().completed == 1
        assert not book.reconcile_exit("d1", target_quotes=tq, control_quotes=cq,
                                       received_at=BASE + timedelta(hours=4, seconds=10))


def test_unverified_admission_and_backfill_fail_closed(tmp_path):
    with ForwardPaperBook(tmp_path / "book.sqlite") as book:
        with pytest.raises(EvidenceRejected, match="frozen"):
            admit(book)
        setup(book)
        with pytest.raises(EvidenceRejected, match="source evidence"):
            admit(book, calendar_receipt="")
        with pytest.raises(EvidenceRejected, match="Retroactive"):
            admit(book, received_at=BASE + timedelta(hours=5))
        with pytest.raises(EvidenceRejected, match="future"):
            q = fixture()[3]
            admit(book, target_quotes=[
                OptionQuote(**{**vars(q[0]), "bid_at": BASE + timedelta(minutes=1)}),
                q[1],
            ])


def test_missing_and_late_exits_stay_visible(tmp_path):
    with ForwardPaperBook(tmp_path / "book.sqlite") as book:
        setup(book)
        admit(book)
        assert book.note_missing_exit(
            "d1", received_at=BASE + timedelta(hours=4, seconds=10),
            missing_contracts=[fixture()[3][0].contract]
        )
        r = book.report()
        assert r.missing_exits == 1 and r.awaiting_exit == 1
        tq, cq = exits()
        with pytest.raises(EvidenceRejected, match="Late"):
            book.reconcile_exit(
                "d1", target_quotes=tq, control_quotes=cq,
                received_at=BASE + timedelta(hours=5)
            )
        assert book.report().completed == 0
        assert len(book.due_contracts(BASE + timedelta(days=1))) == 1


def test_stale_or_missing_benchmark_never_prices_selected_only(tmp_path):
    with ForwardPaperBook(tmp_path / "book.sqlite") as book:
        setup(book)
        admit(book)
        tq, cq = exits()
        with pytest.raises(EvidenceRejected, match="Both unique"):
            book.reconcile_exit(
                "d1", target_quotes=tq, control_quotes=cq[:1],
                received_at=BASE + timedelta(hours=4, seconds=10)
            )
        with pytest.raises(EvidenceRejected, match="Future or stale"):
            stale = pair("IWM", fixture()[0].expiry, 280, 281,
                         BASE, 1.2, 1.3, .05, .1)
            book.reconcile_exit(
                "d1", target_quotes=stale, control_quotes=cq,
                received_at=BASE + timedelta(hours=4, seconds=10)
            )
        assert book.report().completed == 0


def test_concurrent_risk_cap_is_enforced(tmp_path):
    with ForwardPaperBook(tmp_path / "book.sqlite") as book:
        setup(book)
        for i in range(4):
            admit(book, did=f"d{i}")
        with pytest.raises(EvidenceRejected, match="eligible"):
            admit(book, did="d4")
        assert book.report().awaiting_exit == 4


def test_duplicate_id_cannot_rewrite_entry_or_exit(tmp_path):
    with ForwardPaperBook(tmp_path / "book.sqlite") as book:
        setup(book)
        admit(book)
        with pytest.raises(EvidenceRejected, match="readmitted"):
            admit(book, received_at=BASE + timedelta(seconds=20))
        assert book.report().selected == 1
        tq, cq = exits()
        book.reconcile_exit("d1", target_quotes=tq, control_quotes=cq,
                            received_at=BASE + timedelta(hours=4, seconds=10))
        with pytest.raises(EvidenceRejected):
            admit(book)
        assert book.report().completed == 1


def test_immutable_events_and_integrity_validation(tmp_path):
    path = tmp_path / "book.sqlite"
    with ForwardPaperBook(path) as book:
        setup(book)
        with pytest.raises(sqlite3.DatabaseError):
            book.db.execute("UPDATE journal SET payload='x' WHERE event_id='design'")
        book.db.execute("DROP TRIGGER journal_no_update")
        book.db.execute("UPDATE journal SET payload='{}' WHERE event_id='design'")
        with pytest.raises(EvidenceRejected, match="integrity"):
            book.events()
    with pytest.raises(EvidenceRejected, match="integrity"):
        ForwardPaperBook(path)


def test_prospective_long_holdout_requires_strategy_and_control_edges(tmp_path):
    with ForwardPaperBook(tmp_path / "book.sqlite") as book:
        setup(book)
        day = BASE.astimezone(ET).date()
        completed = 0
        for i in range(170):
            d = day + timedelta(days=i)
            if d.weekday() > 4:
                continue
            when = datetime(d.year, d.month, d.day, 10, 45, tzinfo=ET)
            did = f"paper{i:03d}"
            admit(book, did=did, when=when)
            tq, cq = exits(when)
            book.reconcile_exit(
                did, target_quotes=tq, control_quotes=cq,
                received_at=when + timedelta(hours=4, seconds=15)
            )
            completed += 1
            if completed == 105:
                break
        r = book.report()
        assert r.held_out == 105 and r.completed == 105
        assert r.status == "PAPER_PROMISING_NOT_LIVE_VALIDATED"
        assert r.mean_strategy_net_usd == pytest.approx(87.4)
        assert r.lower_95_excess_usd > 0
        assert r.benchmark_adjusted_verdict == (
            "PAPER_PROMISING_REQUIRES_INDEPENDENT_FILLED_EXECUTION"
        )


def test_no_backdated_preregistration(tmp_path):
    with ForwardPaperBook(tmp_path / "book.sqlite") as book:
        with pytest.raises(EvidenceRejected, match="before it starts"):
            book.preregister(
                strategy_hash="a" * 64, benchmark_rule="control_v1",
                holdout_start=BASE, registered_at=BASE
            )
        setup(book)
        with pytest.raises(EvidenceRejected, match="Conflicting"):
            book.preregister(
                strategy_hash="b" * 64, benchmark_rule="control_v2",
                holdout_start=BASE - timedelta(days=1),
                registered_at=BASE - timedelta(days=5)
            )
