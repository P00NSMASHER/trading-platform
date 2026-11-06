from datetime import timedelta
import pytest
from golden_goose_data import (
    utc, normalize_stock, normalize_option, InvalidEvidence,
    PrivateDecisionLedger, PaperDecision, check_minute_coverage,
    compute_incremental_stock_volume, market_session,
)

NOW=utc('2026-11-05T16:18:08Z')
STOCK={'symbol':'IWM','observed_minute':'2026-11-05T16:18:00Z',
 'bid':275.81,'ask':275.84,'bid_at':'2026-11-05T16:18:04Z',
 'ask_at':'2026-11-05T16:18:05Z','volume':1500,
 'source':'tradier_prod_rest_broad_level1_v22_paper_only'}
OPT={'root':'IWM','symbol':'IWM261106C00277500','expiration':'2026-11-06',
 'strike':277.5,'right':'C','observed_minute':'2026-11-05T16:18:00Z',
 'bid':1.50,'ask':1.58,'bid_at':'2026-11-05T16:18:05Z','ask_at':'2026-11-05T16:18:06Z',
 'open_interest':767,'multiplier':100,
 'source':'tradier_prod_rest_broad_options_v23_paper_only'}


def test_utc_offsets_normalized():
    assert utc('2026-11-05T11:18:00-05:00')==utc('2026-11-05T16:18:00Z')
    with pytest.raises(InvalidEvidence): utc('2026-11-05T11:18:00')


def test_stock_price_and_volume():
    q=normalize_stock(STOCK,NOW)
    assert q.mid==pytest.approx(275.825)
    assert q.volume==1500


def test_stock_crossed_stale_and_future_rejected():
    with pytest.raises(InvalidEvidence):normalize_stock({**STOCK,'ask':100},NOW)
    with pytest.raises(InvalidEvidence):normalize_stock(STOCK,NOW+timedelta(minutes=3))
    with pytest.raises(InvalidEvidence):normalize_stock({**STOCK,'bid_at':'2026-11-05T16:19:00Z'},NOW)


def test_option_valid_and_identity_enforced():
    q=normalize_option(OPT,NOW)
    assert q.open_interest==767 and q.multiplier==100
    for bad in [
        {'root':'SPY'}, {'expiration':'2026-11-13'}, {'right':'P'},
        {'strike':278.0}, {'multiplier':10}, {'bid':2.0,'ask':1.0},
        {'symbol':'IWM1261106C00277500'},
    ]:
        with pytest.raises(InvalidEvidence):normalize_option({**OPT,**bad},NOW)


def test_invalid_provenance_rejected():
    with pytest.raises(InvalidEvidence):normalize_option({**OPT,'source':'synthetic_fixture'},NOW)
    with pytest.raises(InvalidEvidence):normalize_stock({**STOCK,'source':'unknown'},NOW)


def test_coverage_and_unknown_opening_volume():
    x=normalize_stock(STOCK,NOW)
    y=normalize_stock({**STOCK,'observed_minute':'2026-11-05T16:20:00Z','bid_at':'2026-11-05T16:20:01Z','ask_at':'2026-11-05T16:20:02Z','volume':1800},NOW+timedelta(minutes=2))
    c=check_minute_coverage([x,y])
    assert c['gaps']==1
    assert compute_incremental_stock_volume([x,y])==((x.observed,None),(y.observed,300))


def test_ledger_never_drops_missing_paper_exits():
    q=normalize_option(OPT,NOW)
    ledger=PrivateDecisionLedger()
    d=PaperDecision('trade_001',NOW,'IWM','bull_call','SELECTED','pass',(q.contract,'IWM261106C00278000'))
    ledger.admit(d)
    assert ledger.summary()['missing_selected_exit']==1
    with pytest.raises(InvalidEvidence):ledger.admit(d)
    with pytest.raises(InvalidEvidence):ledger.record_exit('trade_001',NOW+timedelta(minutes=5),(q,))
    assert ledger.summary()['missing_selected_exit']==1


def test_session_is_only_time_window_not_holiday_calendar():
    assert market_session(utc('2026-11-05T15:00:00Z'))
    assert not market_session(utc('2026-11-05T22:00:00Z'))
