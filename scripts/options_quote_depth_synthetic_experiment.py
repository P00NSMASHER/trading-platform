"""Reproducible negative-control experiment; synthetic books only."""
from collections import Counter
from datetime import datetime, timedelta, timezone
import json

from options_quote_depth_gate import audit_quote_depth

UTC = timezone.utc
START = datetime(2026, 10, 27, 15, tzinfo=UTC)
SIDE_PRICES = {"short_bid": "1.25", "short_ask": "1.27", "long_bid": "0.78", "long_ask": "0.80"}


def make_case(i):
    decision = START + timedelta(minutes=3 * i)
    entry = decision + timedelta(seconds=15)
    entry_quote = decision - timedelta(seconds=5)
    exit_time = entry + timedelta(hours=23)
    exit_quote = exit_time - timedelta(seconds=5)
    paper = {"trade_id": f"SYNTHETIC_{i}",
             "decision_utc": decision.isoformat(), "entry_utc": entry.isoformat(),
             "entry_quote_utc": entry_quote.isoformat(),
             "exit_utc": exit_time.isoformat(), "exit_quote_utc": exit_quote.isoformat()}
    depth = {"trade_id": paper["trade_id"]}
    for event, instant in (("entry", entry_quote), ("exit", exit_quote)):
        for side, price in SIDE_PRICES.items():
            key = f"{event}_{side}"
            paper[key] = price
            depth[key + "_px"] = price
            depth[key + "_size"] = "1"
            depth[key + "_utc"] = (instant - timedelta(seconds=2)).isoformat()
    return paper, depth


def run():
    papers, books = [], []
    for i in range(100):
        p, b = make_case(i)
        if 40 <= i < 50:
            # Previously passed: fabricated crossed short-leg bid > ask.
            p["entry_short_bid"] = b["entry_short_bid_px"] = "2.00"
        elif 50 <= i < 70:
            b["entry_short_bid_size"] = "0"
        elif 70 <= i < 80:
            b["entry_short_bid_utc"] = (START - timedelta(hours=1)).isoformat()
        elif 80 <= i < 90:
            b["entry_short_bid_utc"] = (datetime.fromisoformat(p["entry_quote_utc"])
                                          + timedelta(seconds=1)).isoformat()
        elif 90 <= i < 100:
            b["exit_long_bid_px"] = "0.01"
        papers.append(p)
        books.append(b)
    return audit_quote_depth(papers, books, asof="2026-10-30T04:00:00Z")


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
