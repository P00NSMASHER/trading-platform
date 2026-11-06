from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pytest
from golden_goose_signals import Bar, Catalyst, evaluate_post_catalyst, chronological_split, SignalRejected
ET=ZoneInfo('America/New_York')
D=datetime(2026,11,5,10,5,tzinfo=ET)


def bars():
    base=datetime(2026,11,5,9,30,tzinfo=ET)
    a=[Bar(base+timedelta(minutes=i),100.0,100.20,99.85,100.10,1000) for i in range(30)]
    a.extend([
        Bar(base+timedelta(minutes=30),100.2,100.45,100.18,100.30,2000),
        Bar(base+timedelta(minutes=31),100.3,100.65,100.25,100.4,1800),
        Bar(base+timedelta(minutes=33),100.4,100.5,100.19,100.23,1800),
        Bar(base+timedelta(minutes=35),100.3,101.1,100.22,100.98,1700),
    ])
    return a


def cat(verified=True,at=None):
    return Catalyst('verified_cpi',at or datetime(2026,11,5,9,15,tzinfo=ET),verified,'macro')


def test_past_only_breakout_retest_and_prior_20_day_baseline():
    s=evaluate_post_catalyst(bars(),[1000]*20,cat(),D,1,1)
    assert s.state=='RESEARCH_SIGNAL' and s.side=='C'
    assert s.relative_volume==pytest.approx(1.7)


def test_incomplete_baseline_and_disagreement_fail():
    assert evaluate_post_catalyst(bars(),[1000]*19,cat(),D,1,1).reason=='MISSING_PRIOR_COMPLETED_SESSION_BASELINE'
    assert evaluate_post_catalyst(bars(),[1000]*20,cat(),D,-1,1).reason=='DIRECTION_NOT_CONFIRMED'


def test_unverified_or_future_catalysts_fail():
    assert evaluate_post_catalyst(bars(),[1000]*20,cat(verified=False),D,1,1).reason=='CATALYST_UNVERIFIED'
    assert evaluate_post_catalyst(bars(),[1000]*20,cat(at=D+timedelta(seconds=1)),D,1,1).reason=='CATALYST_NOT_KNOWN_AS_OF_DECISION'


def test_missing_retest_rejected():
    a=bars()
    a[-2]=Bar(a[-2].at,100.8,100.9,100.6,100.7,1700)
    a[30]=Bar(a[30].at,100.5,100.6,100.4,100.5,1800)
    a[31]=Bar(a[31].at,100.6,100.7,100.4,100.6,1800)
    assert evaluate_post_catalyst(a,[1000]*20,cat(),D,1,1).reason=='NO_CONFIRMED_RETEST'


def test_future_bar_and_duplicates_fail():
    a=bars();a.append(Bar(D+timedelta(seconds=1),100,102,99,101,1700))
    with pytest.raises(SignalRejected):evaluate_post_catalyst(a,[1000]*20,cat(),D,1,1)
    a=bars();a.append(a[-1])
    assert evaluate_post_catalyst(a,[1000]*20,cat(),D,1,1).reason=='DUPLICATE_OR_NONMONOTONIC_BARS'


def test_day_split_never_shuffles():
    dates=[datetime(2026,10,1,tzinfo=ET).date()+timedelta(days=i) for i in range(24)]
    train,hold=chronological_split(dates,0.25)
    assert len(train)==18 and len(hold)==6 and max(train)<min(hold)
    with pytest.raises(SignalRejected):chronological_split(dates[:10])
