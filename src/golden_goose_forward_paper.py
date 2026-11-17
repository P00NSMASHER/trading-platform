"""Prospective, private, no-order debit-spread evidence ledger.

This is an offline research component. It never contacts a market vendor,
broker, Worker, or D1; all inputs must be obtained through an independently
authorized, point-in-time feed. A positive paper verdict is NOT a trading edge.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from collections import defaultdict
import hashlib
import json
import math
import os
import re
import sqlite3

from golden_goose_candidates import (
    DebitSpread, PaperOutcome, evaluate_edge, screen_debit_spreads,
    MODELED_TOTAL_FEES_SLIPPAGE_USD, MAX_CONCURRENT_LOSS_USD,
)
from golden_goose_data import OptionQuote
from golden_goose_signals import SignalResult

UTC = timezone.utc
ET = ZoneInfo("America/New_York")
HASH = re.compile(r"^[0-9a-f]{64}$")
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,100}$")
COST = MODELED_TOTAL_FEES_SLIPPAGE_USD


class EvidenceRejected(ValueError):
    """A fail-closed, non-sensitive validation failure."""


def _at(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise EvidenceRejected("UTC-aware timestamp required")
    return value.astimezone(UTC)


def _stamp(value: datetime) -> str:
    return _at(value).isoformat(timespec="microseconds")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _money(value: float) -> float:
    if isinstance(value, bool) or not math.isfinite(value):
        raise EvidenceRejected("Invalid finite monetary value")
    return round(float(value), 2)


def _pair(
    quotes: list[OptionQuote], buy: str, sell: str, *, at: datetime,
    root: str, expiry: date, side: str,
) -> tuple[float, float, str]:
    """Return executable-side indicative debit, exit credit, and source digest."""
    if len(quotes) != 2 or buy == sell or {q.contract for q in quotes} != {buy, sell}:
        raise EvidenceRejected("Both unique frozen contracts required")
    qmap = {q.contract: q for q in quotes}
    if len(qmap) != 2:
        raise EvidenceRejected("Duplicate contract quote")
    at = _at(at)
    receipts = []
    for q in quotes:
        if q.root != root or q.expiration != expiry or q.right != side or q.multiplier != 100:
            raise EvidenceRejected("Changed contract identity or deliverable")
        if not q.source.startswith("tradier_") or "synthetic" in q.source.lower():
            raise EvidenceRejected("Unverified market quote provenance")
        if not all(math.isfinite(v) and v > 0 for v in (q.bid, q.ask)):
            raise EvidenceRejected("Missing or invalid two-sided quote")
        if q.bid > q.ask or q.open_interest < 0:
            raise EvidenceRejected("Crossed quote or invalid open interest")
        for ts in (q.observed, q.bid_at, q.ask_at):
            age = (at - _at(ts)).total_seconds()
            if age < 0 or age > 120:
                raise EvidenceRejected("Future or stale option evidence")
        receipts.append([q.contract, _stamp(q.observed), _money(q.bid),
                         _money(q.ask), _stamp(q.bid_at), _stamp(q.ask_at), q.source])
    ordered = sorted(receipts)
    debit = _money((qmap[buy].ask - qmap[sell].bid) * 100)
    credit = _money((qmap[buy].bid - qmap[sell].ask) * 100)
    return debit, credit, _digest(json.dumps(ordered, separators=(",", ":")))


@dataclass(frozen=True)
class PaperComparison:
    status: str
    selected: int
    completed: int
    missing_exits: int
    awaiting_exit: int
    held_out: int
    strategy_verdict: str
    benchmark_adjusted_verdict: str
    mean_strategy_net_usd: float | None
    mean_excess_over_control_usd: float | None
    lower_95_excess_usd: float | None


class ForwardPaperBook:
    """Private, hash-chained, append-only SQLite journal with serialized writes.

    No raw rows, credentials, orders, or market data are ever published.
    Hash-chain integrity detects mutation, but an external hash checkpoint is
    still required for independent tamper evidence.
    """

    def __init__(self, path: str | Path):
        p = Path(path).resolve()
        if not p.parent.exists():
            p.parent.mkdir(parents=True, mode=0o700)
        if p.exists() and (p.stat().st_mode & 0o077):
            raise EvidenceRejected("Private ledger permissions are too broad")
        self.db = sqlite3.connect(str(p), isolation_level=None, timeout=10)
        if os.name == "posix":
            os.chmod(p, 0o600)
        self.db.execute("PRAGMA busy_timeout=10000")
        self.db.execute("CREATE TABLE IF NOT EXISTS journal ("
                        "seq INTEGER PRIMARY KEY, event_id TEXT UNIQUE NOT NULL, "
                        "kind TEXT NOT NULL, payload TEXT NOT NULL, "
                        "previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL)")
        self.db.execute("CREATE TRIGGER IF NOT EXISTS journal_no_update "
                        "BEFORE UPDATE ON journal BEGIN SELECT RAISE(ABORT, 'immutable'); END")
        self.db.execute("CREATE TRIGGER IF NOT EXISTS journal_no_delete "
                        "BEFORE DELETE ON journal BEGIN SELECT RAISE(ABORT, 'immutable'); END")
        self.events()  # fail closed if the private journal has been modified

    def close(self) -> None:
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def events(self) -> list[tuple[str, str, dict]]:
        prior = "0" * 64
        out = []
        for event_id, kind, payload, prev, actual in self.db.execute(
            "SELECT event_id,kind,payload,previous_hash,event_hash FROM journal ORDER BY seq"
        ):
            expected = _digest("\n".join((prior, event_id, kind, payload)))
            if prev != prior or actual != expected:
                raise EvidenceRejected("Private research journal integrity failure")
            out.append((event_id, kind, json.loads(payload)))
            prior = actual
        return out

    def head_hash(self) -> str:
        rows = self.db.execute("SELECT event_hash FROM journal ORDER BY seq DESC LIMIT 1").fetchall()
        return rows[0][0] if rows else "0" * 64

    def _append(self, event_id: str, kind: str, data: dict) -> bool:
        if not ID.fullmatch(event_id):
            raise EvidenceRejected("Invalid journal event identifier")
        payload = json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.events()
            existing = self.db.execute(
                "SELECT kind,payload FROM journal WHERE event_id=?", (event_id,)
            ).fetchone()
            if existing is not None:
                if existing != (kind, payload):
                    raise EvidenceRejected("Conflicting idempotency replay")
                self.db.execute("COMMIT")
                return False
            prior = self.head_hash()
            digest = _digest("\n".join((prior, event_id, kind, payload)))
            self.db.execute(
                "INSERT INTO journal(event_id,kind,payload,previous_hash,event_hash) "
                "VALUES (?,?,?,?,?)", (event_id, kind, payload, prior, digest)
            )
            self.db.execute("COMMIT")
            return True
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def preregister(
        self, *, strategy_hash: str, benchmark_rule: str,
        holdout_start: datetime, registered_at: datetime,
    ) -> bool:
        if not HASH.fullmatch(strategy_hash) or not ID.fullmatch(benchmark_rule):
            raise EvidenceRejected("Frozen design and benchmark rule required")
        if _at(registered_at) >= _at(holdout_start):
            raise EvidenceRejected("Holdout must be predeclared before it starts")
        return self._append("design", "DESIGN", {
            "strategy_hash": strategy_hash,
            "benchmark_rule": benchmark_rule,
            "holdout_start": _stamp(holdout_start),
            "registered_at": _stamp(registered_at),
        })

    def _state(self) -> tuple[dict, dict, dict]:
        designs = {}
        positions = {}
        exits = {}
        for _, kind, row in self.events():
            if kind == "DESIGN":
                designs = row
            elif kind == "ADMIT":
                positions[row["decision_id"]] = row
            elif kind == "EXIT":
                exits[row["decision_id"]] = row
        return designs, positions, exits

    def admit(
        self, *, decision_id: str, signal: SignalResult,
        target: DebitSpread, control: DebitSpread,
        target_quotes: list[OptionQuote], control_quotes: list[OptionQuote],
        received_at: datetime, planned_exit_at: datetime, equity_usd: float,
        calendar_receipt: str, catalyst_receipt: str,
    ) -> bool:
        if not ID.fullmatch(decision_id):
            raise EvidenceRejected("Invalid decision ID")
        design, positions, exits = self._state()
        if not design:
            raise EvidenceRejected("Strategy and benchmark must be frozen first")
        decision = _at(signal.decision_at)
        recv = _at(received_at)
        deadline = _at(planned_exit_at)
        if not 0 <= (recv - decision).total_seconds() <= 120:
            raise EvidenceRejected("Retroactive or future admission prohibited")
        if not (decision + timedelta(seconds=60) <= deadline
                <= datetime.combine(target.expiry, datetime.min.time(), tzinfo=ET)
                   + timedelta(hours=15, minutes=55)):
            raise EvidenceRejected("Exit rule invalid or beyond option expiry")
        if signal.state != "RESEARCH_SIGNAL" or signal.side != target.side:
            raise EvidenceRejected("Signal has not passed predeclared screen")
        if target.status != "RESEARCH_ONLY_NOT_VALIDATED":
            raise EvidenceRejected("Unrecognized research candidate")
        if control.side != target.side or control.expiry != target.expiry:
            raise EvidenceRejected("Benchmark must share side and expiration")
        if {target.buy_contract, target.sell_contract} & {control.buy_contract, control.sell_contract}:
            raise EvidenceRejected("Benchmark must have independent contracts")
        if not calendar_receipt or not catalyst_receipt:
            raise EvidenceRejected("Exchange session and source evidence required")
        if decision < datetime.fromisoformat(design["registered_at"]):
            raise EvidenceRejected("Cannot select an event before preregistration")
        if decision_id in exits:
            raise EvidenceRejected("Closed paper decision cannot be readmitted")
        open_risk = sum(p["risk_usd"] for did, p in positions.items() if did not in exits and did != decision_id)
        if open_risk >= MAX_CONCURRENT_LOSS_USD:
            raise EvidenceRejected("Maximum concurrent paper risk exhausted")
        d, _, entry_hash = _pair(
            target_quotes, target.buy_contract, target.sell_contract,
            at=decision, root=target.root, expiry=target.expiry, side=target.side
        )
        cd, _, control_hash = _pair(
            control_quotes, control.buy_contract, control.sell_contract,
            at=decision, root=control.root, expiry=control.expiry, side=control.side
        )
        if d <= 0 or cd <= 0:
            raise EvidenceRejected("Invalid indicative entry debit")
        allowed = screen_debit_spreads(
            target_quotes, side=target.side, decision=decision,
            equity_usd=equity_usd, existing_open_risk_usd=open_risk
        ).candidates
        if target not in allowed or abs(d - target.quoted_debit_usd) > 0.01:
            raise EvidenceRejected("Candidate is not eligible under current risk budget")
        risk = _money(d + COST)
        control_risk = _money(cd + COST)
        if control_risk <= 0:
            raise EvidenceRejected("Invalid matched-control risk")
        row = {
            "decision_id": decision_id, "decision": _stamp(decision),
            "received": _stamp(recv), "exit_at": _stamp(deadline),
            "holdout": decision >= datetime.fromisoformat(design["holdout_start"]),
            "strategy_hash": design["strategy_hash"],
            "benchmark_rule": design["benchmark_rule"],
            "calendar_receipt_hash": _digest(calendar_receipt),
            "catalyst_receipt_hash": _digest(catalyst_receipt),
            "target": {"root": target.root, "side": target.side,
                       "expiry": target.expiry.isoformat(),
                       "buy": target.buy_contract, "sell": target.sell_contract,
                       "entry_debit_usd": d, "entry_receipt_hash": entry_hash},
            "control": {"root": control.root, "side": control.side,
                        "expiry": control.expiry.isoformat(),
                        "buy": control.buy_contract, "sell": control.sell_contract,
                        "entry_debit_usd": cd, "entry_receipt_hash": control_hash},
            "risk_usd": risk, "control_risk_usd": control_risk,
        }
        if decision_id in positions and positions[decision_id] != row:
            raise EvidenceRejected("Decision cannot be readmitted or rewritten")
        return self._append("admit:" + decision_id, "ADMIT", row)

    def due_contracts(self, now: datetime) -> tuple[dict, ...]:
        """Never silently discard a selected position with missing exit data."""
        now = _at(now)
        _, positions, exits = self._state()
        return tuple({
            "decision_id": did, "planned_exit_at": p["exit_at"],
            "due": now >= datetime.fromisoformat(p["exit_at"]),
            "contracts": tuple(sorted({
                p[role][leg] for role in ("target", "control") for leg in ("buy", "sell")
            })),
        } for did, p in sorted(positions.items()) if did not in exits)

    def note_missing_exit(self, decision_id: str, *, received_at: datetime,
                          missing_contracts: list[str]) -> bool:
        _, positions, exits = self._state()
        if decision_id not in positions or decision_id in exits:
            raise EvidenceRejected("Unknown or closed paper decision")
        p = positions[decision_id]
        expected = {p[role][leg] for role in ("target", "control") for leg in ("buy", "sell")}
        if not missing_contracts or not set(missing_contracts) <= expected:
            raise EvidenceRejected("Missing receipt must identify frozen contracts")
        received = _at(received_at)
        if received < datetime.fromisoformat(p["exit_at"]):
            raise EvidenceRejected("Cannot declare missing exits before scheduled exit")
        return self._append("miss:" + decision_id + ":" + _digest(_stamp(received))[:20],
                            "MISSING", {"decision_id": decision_id,
                                        "missing": sorted(set(missing_contracts)),
                                        "received": _stamp(received)})

    def reconcile_exit(
        self, decision_id: str, *, target_quotes: list[OptionQuote],
        control_quotes: list[OptionQuote], received_at: datetime,
    ) -> bool:
        _, positions, exits = self._state()
        if decision_id not in positions:
            raise EvidenceRejected("Unknown paper position")
        p = positions[decision_id]
        deadline = datetime.fromisoformat(p["exit_at"])
        received = _at(received_at)
        if not 0 <= (received - deadline).total_seconds() <= 120:
            raise EvidenceRejected("Late or preselected exit mark prohibited")
        values = {}
        for role, quotes in (("target", target_quotes), ("control", control_quotes)):
            item = p[role]
            _, credit, qhash = _pair(
                quotes, item["buy"], item["sell"], at=deadline,
                root=item["root"], expiry=date.fromisoformat(item["expiry"]),
                side=item["side"]
            )
            pnl = _money(credit - item["entry_debit_usd"] - COST)
            values[role] = {"pnl_usd": pnl, "exit_credit_usd": credit,
                            "exit_receipt_hash": qhash}
        scaled_control = _money(values["control"]["pnl_usd"]
                                * p["risk_usd"] / p["control_risk_usd"])
        return self._append("exit:" + decision_id, "EXIT", {
            "decision_id": decision_id, "received": _stamp(received),
            "target": values["target"], "control": values["control"],
            "risk_scaled_control_pnl_usd": scaled_control,
            "excess_pnl_usd": _money(values["target"]["pnl_usd"] - scaled_control),
        })

    def report(self) -> PaperComparison:
        design, positions, exits = self._state()
        if not design:
            return PaperComparison("NO_PREREGISTERED_STUDY", 0, 0, 0, 0, 0,
                                   "UNPROVEN_NO_DATA", "UNPROVEN_NO_DATA", None, None, None)
        missing = {row["decision_id"] for _, kind, row in self.events() if kind == "MISSING"}
        target = []
        delta = []
        for did, p in positions.items():
            if not p["holdout"]:
                continue
            done = exits.get(did)
            dt = datetime.fromisoformat(p["decision"])
            target.append(PaperOutcome(
                did, dt, done["target"]["pnl_usd"] if done else None,
                done is not None, True, True, False, p["risk_usd"]
            ))
            delta.append(PaperOutcome(
                did, dt, done["excess_pnl_usd"] if done else None,
                done is not None, True, True, False, p["risk_usd"]
            ))
        a = evaluate_edge(target)
        b = evaluate_edge(delta)
        promising = "PAPER_PROMISING_REQUIRES_INDEPENDENT_FILLED_EXECUTION"
        if a.status == promising and b.status == promising:
            status = "PAPER_PROMISING_NOT_LIVE_VALIDATED"
        elif a.status.startswith("UNPROVEN") or b.status.startswith("UNPROVEN"):
            status = "INSUFFICIENT_PROSPECTIVE_EVIDENCE"
        else:
            status = "NO_POSITIVE_RISK_ADJUSTED_CONTROL_EDGE"
        return PaperComparison(
            status, len(positions), len(exits),
            len(missing - exits.keys()), len(positions) - len(exits),
            len(target), a.status, b.status,
            a.mean_net_usd, b.mean_net_usd, b.lower_95_usd
        )
