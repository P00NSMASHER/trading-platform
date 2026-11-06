from datetime import timedelta
from golden_goose_candidates import PaperOutcome,evaluate_edge
from golden_goose_data import utc
from golden_goose_simulator import simulate_paper_paths


def outcomes(pnl):
    first=utc('2026-01-05T15:00:00Z')
    return [PaperOutcome(f't{i}',first+timedelta(days=i),pnl,True,True,True,False,100)
            for i in range(105)]


def test_no_probability_numbers_without_positive_complete_edge():
    rows=outcomes(-10);r=simulate_paper_paths(rows,evaluate_edge(rows))
    assert r.status=='BLOCKED_NO_VERIFIED_PROSPECTIVE_EDGE'
    assert r.chance_double_at_end is None and r.chance_touch_half is None


def test_synthetic_positive_probability_is_labeled_hypothetical():
    rows=outcomes(50)
    r=simulate_paper_paths(rows,evaluate_edge(rows),paths=150,trades_per_month=12)
    assert r.status=='HYPOTHETICAL_PAPER_SCENARIOS_NOT_REAL_WORLD_FORECAST'
    assert 0<=r.chance_double_at_end<=1 and 0<=r.chance_touch_half<=1
    assert r.chance_touch_half==0
