"""Synthetic adversarial tests of source-adjustment sensitivity (no prices)."""
from dataclasses import replace
from datetime import date, timedelta

import pytest

from equity_pair_adjustment_audit import audit_adjustment_sensitivity
from equity_reversal_audit import Bar, InvalidPriceEvidence


def bars(adjusted_q_prior=97.0, raw_q_prior=100.0):
    start = date(2020, 1, 2)
    spy = [Bar(start + timedelta(days=i), 100., 100., 100.) for i in range(8)]
    qqq = [Bar(start + timedelta(days=i), 100., 100., 100.) for i in range(8)]
    qqq[5] = replace(qqq[5], close=raw_q_prior, adjusted_close=adjusted_q_prior)
    return spy, qqq


def test_adjusted_only_selection_and_fixed_costs():
    spy, qqq = bars()
    x = audit_adjustment_sensitivity(spy, qqq)["phases"]["holdout"]
    assert x["eligible_sessions"] == 2
    assert x["adjusted_selected"] == 1 and x["raw_selected"] == 0
    assert x["disagreements"] == 1 and x["adjusted_only"] == 1
    assert x["disagreement_days"] == ["2020-01-08"]
    assert x["mean_net_bps"]["20"] == {"adjusted": -20.0, "raw": None}
    assert x["mean_net_bps"]["10"]["adjusted"] == -10.0
    assert x["mean_net_bps"]["40"]["adjusted"] == -40.0


def test_raw_only_selection_not_promoted_to_alpha():
    spy, qqq = bars(adjusted_q_prior=100., raw_q_prior=97.)
    x = audit_adjustment_sensitivity(spy, qqq)["phases"]["holdout"]
    assert x["raw_selected"] == 1 and x["adjusted_selected"] == 0
    assert x["raw_only"] == 1 and x["adjusted_only"] == 0


def test_future_close_changes_payoff_but_not_prior_close_signal():
    spy, qqq = bars()
    baseline = audit_adjustment_sensitivity(spy, qqq)["phases"]["holdout"]
    altered = qqq.copy()
    altered[6] = replace(altered[6], close=105.)
    later = audit_adjustment_sensitivity(spy, altered)["phases"]["holdout"]
    for field in ("adjusted_selected", "raw_selected", "disagreements", "disagreement_days"):
        assert later[field] == baseline[field]
    assert later["mean_net_bps"]["20"]["adjusted"] == 230.0


@pytest.mark.parametrize("which", ["duplicate", "reversed", "asymmetric_missing", "empty"])
def test_malformed_or_asymmetric_calendar_fails_closed(which):
    spy, qqq = bars()
    if which == "duplicate":
        qqq[4] = replace(qqq[4], day=qqq[3].day)
    elif which == "reversed":
        qqq[3], qqq[4] = qqq[4], qqq[3]
    elif which == "asymmetric_missing":
        qqq.pop(3)
    else:
        qqq = []
    with pytest.raises(InvalidPriceEvidence):
        audit_adjustment_sensitivity(spy, qqq)


@pytest.mark.parametrize("bad", [0., -1., float("nan"), float("inf")])
def test_malformed_prior_raw_close_rejected(bad):
    spy, qqq = bars()
    qqq[0] = replace(qqq[0], close=bad)
    with pytest.raises(InvalidPriceEvidence):
        audit_adjustment_sensitivity(spy, qqq)


def test_phase_empty_selection_not_fabricated():
    spy, qqq = bars(adjusted_q_prior=100., raw_q_prior=100.)
    x = audit_adjustment_sensitivity(spy, qqq)
    assert x["phases"]["train"]["eligible_sessions"] == 0
    assert x["phases"]["validation"]["mean_net_bps"]["20"]["adjusted"] is None
    assert x["phases"]["holdout"]["disagreements"] == 0
