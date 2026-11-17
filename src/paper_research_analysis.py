"""Private, offline analysis of bounded D1 extracts. Never fetches data or orders.

Quote costs are indicative, not execution evidence. Holdout returns are embargoed
until all frozen minima pass. A first evaluation is locked to an immutable file.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import hashlib
import json
import math
import os
import re
import tempfile
import numpy as np

ET = ZoneInfo("America/New_York")
UTC = timezone.utc


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def at(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Ambiguous timestamp")
    return dt.astimezone(UTC)


def private_write(path: Path, data: bytes, *, immutable=False):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if immutable and path.exists():
        if path.read_bytes() != data:
            raise ValueError("Conflicting immutable artifact")
        return
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".paper-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        if immutable:
            try:
                os.link(tmp, path)
            except FileExistsError:
                if path.read_bytes() != data:
                    raise ValueError("Conflicting immutable artifact")
            os.unlink(tmp)
        else:
            os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def seal_archive(directory: str | Path) -> dict:
    """Incremental checkpoints: existing day hashes cannot be changed on refresh."""
    folder = Path(directory)
    manifest_path = folder / "manifest.json"
    old = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"chunks": {}}
    chunks = dict(old["chunks"])
    for p in sorted(folder.glob("20??-??-??.json")):
        raw = p.read_bytes()
        digest = sha(raw)
        if p.name in chunks:
            if chunks[p.name]["sha256"] != digest:
                raise ValueError("Previously verified archive changed")
            continue
        part = json.loads(raw)
        if part["evidence_mode"] != "historical_research" or part["day"] != p.stem:
            raise ValueError("Archive provenance mismatch")
        rows_read = rows = 0
        for extract in part["extracts"]:
            result = extract["result"]
            if not result["success"] or not result["result"]:
                raise ValueError("Failed extract")
            for q in result["result"]:
                meta = q["meta"]
                if not q["success"] or meta["rows_written"] != 0 or meta["rows_read"] > 2500:
                    raise ValueError("Unbounded or mutating extract")
                rows_read += meta["rows_read"]
                rows += len(q["results"])
        chunks[p.name] = {"sha256": digest, "bytes": len(raw), "rows": rows,
                          "rows_read": rows_read,
                          "queries_sha256": sha(canonical([x["query"] for x in part["extracts"]]))}
        os.chmod(p, 0o600)
    if any(not (folder / name).is_file() for name in chunks):
        raise ValueError("Verified archive chunk missing")
    manifest = {"version": 1, "evidence_mode": "historical_research", "chunks": chunks}
    private_write(manifest_path, canonical(manifest))
    return manifest


def load_archive(directory: str | Path):
    folder = Path(directory)
    manifest = json.loads((folder / "manifest.json").read_text())
    indexed = {}
    for name, item in manifest["chunks"].items():
        raw = (folder / name).read_bytes()
        if sha(raw) != item["sha256"]:
            raise ValueError("Archive hash mismatch")
        for extract in json.loads(raw)["extracts"]:
            for query in extract["result"]["result"]:
                for row in query["results"]:
                    key = (row["observed_minute"], row["symbol"])
                    if key in indexed and indexed[key] != row:
                        raise ValueError("Conflicting quote identity")
                    indexed[key] = row
    return list(indexed.values()), manifest


def valid_quote(row: dict) -> str | None:
    try:
        if not row["source"].startswith("tradier_") or "synthetic" in row["source"].lower():
            return "unverified_provenance"
        bid, ask = row["bid"], row["ask"]
        if not all(isinstance(x, (float, int)) and math.isfinite(x) and x > 0 for x in (bid, ask)) or ask < bid:
            return "invalid_prices"
        capture, minute, bt, ast = (at(row[k]) for k in ("captured_at", "observed_minute", "bid_quote_at", "ask_quote_at"))
        if not 0 <= (capture-minute).total_seconds() < 60:
            return "capture_minute_mismatch"
        if not all(0 <= (capture-t).total_seconds() <= 60 for t in (bt, ast)) or abs((bt-ast).total_seconds()) > 45:
            return "stale_future_or_skewed_sides"
        if row["kind"] != "underlying":
            match = re.fullmatch(r"([A-Z]+)(\d{6})([CP])(\d{8})", row["symbol"])
            if not match or (match[1], match[3], int(match[4])/1000) != (row["underlying"], row["right"], row["strike"]):
                return "contract_identity"
            expiry = datetime.strptime(match[2], "%y%m%d").date()
            if str(expiry) != row["expiration"] or expiry < capture.astimezone(ET).date():
                return "expiration"
        return None
    except (KeyError, TypeError, ValueError, OverflowError):
        return "malformed"


def cluster_interval(rows: list[tuple[str, float]], seed=261117, draws=4000):
    """Resample whole entry weeks, preserving unequal cluster sizes and dependence."""
    groups = defaultdict(list)
    for timestamp, value in rows:
        iso = at(timestamp).astimezone(ET).isocalendar()
        groups[(iso.year, iso.week)].append(float(value))
    if len(groups) < 2:
        return {"weeks": len(groups), "lower": None, "upper": None}
    totals = np.array([sum(g) for g in groups.values()])
    counts = np.array([len(g) for g in groups.values()])
    rng = np.random.default_rng(seed)
    sample = rng.integers(0, len(groups), size=(draws, len(groups)))
    means = totals[sample].sum(axis=1)/counts[sample].sum(axis=1)
    return {"weeks": len(groups), "lower": round(float(np.quantile(means, .025)), 4),
            "upper": round(float(np.quantile(means, .975)), 4), "method": "whole_entry_week_cluster_bootstrap", "draws": draws}


def summarize_costs(rows: list[dict]) -> dict:
    good, bad = [], Counter()
    for r in rows:
        reason = valid_quote(r)
        if reason:
            bad[reason] += 1
        else:
            good.append(r)
    stock = defaultdict(list)
    for r in good:
        if r["kind"] == "underlying":
            stock[(r["symbol"], at(r["captured_at"]).astimezone(ET).date())].append(r)
    records = []
    for r in good:
        if r["kind"] == "underlying":
            continue
        t = at(r["captured_at"]).astimezone(ET)
        history = stock[(r["underlying"], t.date())]
        opening = [x for x in history if (9, 30) <= (at(x["captured_at"]).astimezone(ET).hour, at(x["captured_at"]).astimezone(ET).minute) < (10, 0)]
        prior = [x for x in history if at(x["captured_at"]) < at(r["captured_at"])]
        regime = "opening" if t.hour < 10 else "missing_opening_history"
        if t.hour >= 10 and len(opening) == 30 and prior:
            mids = [(x["bid"]+x["ask"])/2 for x in opening]
            latest = max(prior, key=lambda x:x["captured_at"])
            mid = (latest["bid"]+latest["ask"])/2
            regime = "above_range" if mid > max(mids) else "below_range" if mid < min(mids) else "inside_range"
        dte = (datetime.fromisoformat(r["expiration"]).date()-t.date()).days
        bucket = "0-1" if dte <= 1 else "2-6" if dte <= 6 else "7-14" if dte <= 14 else "15-21" if dte <= 21 else "22+"
        spread = (r["ask"]-r["bid"])*100
        cost = spread + 2*.65 + 4
        records.append({"symbol":r["underlying"], "dte":bucket, "time":t.strftime("%H:%M"), "condition":regime,
                        "spread_usd":spread, "cost_usd":cost, "stress_cost_usd":cost+10,
                        "premium_usd":(r["bid"]+r["ask"])*50, "date":str(t.date())})
    def group(keys):
        grouped = defaultdict(list)
        for r in records:
            grouped[tuple(r[k] for k in keys)].append(r)
        out = []
        for key, rs in sorted(grouped.items()):
            costs = [r["cost_usd"] for r in rs]
            out.append({**dict(zip(keys, key)), "quotes":len(rs), "sessions":len({r["date"] for r in rs}),
                "median_spread_usd":round(float(np.median([r["spread_usd"] for r in rs])), 2),
                "median_cost_usd":round(float(np.median(costs)), 2), "p90_cost_usd":round(float(np.quantile(costs,.9)), 2),
                "median_stress_cost_usd":round(float(np.median(costs))+10, 2),
                "share_cost_above_10pct_premium":round(sum(r["cost_usd"]>.1*r["premium_usd"] for r in rs)/len(rs),4),
                "share_cost_above_25pct_premium":round(sum(r["cost_usd"]>.25*r["premium_usd"] for r in rs)/len(rs),4),
                "hypothetical_10usd_gross_expected_net_per_attempt":{str(p):round(p*(10-float(np.mean(costs))),2) for p in (1,.75,.5)}})
        return out
    # Coverage of adjacent defined-risk verticals in the observed sample, without inventing a chain.
    sets = defaultdict(set)
    for r in good:
        if r["kind"] != "underlying":
            sets[(r["observed_minute"], r["underlying"], r["expiration"], r["right"])].add(r["strike"])
    adjacent = sum(sum(k+1 in strikes for k in strikes) for strikes in sets.values())
    widths = [b-a for strikes in sets.values() for a,b in zip(sorted(strikes),sorted(strikes)[1:])]
    return {"valid_rows":len(good), "excluded_by_reason":dict(bad), "option_quotes":len(records),
            "observed_adjacent_1usd_vertical_pairs":adjacent,
            "median_observed_neighbor_strike_gap":float(np.median(widths)) if widths else None,
            "by_symbol_expiration":group(["symbol","dte"]), "by_time":group(["time"]),
            "by_condition":group(["condition"]), "cross_groups":group(["symbol","dte","time","condition"]),
            "assumptions":{"position":"one long standard 100-share option", "fees_round_trip":1.3,
               "adverse_round_trip":4, "stress_extra":10, "zero_price_move_cost":"ask entry minus bid exit plus costs",
               "no_fill_probabilities":"illustrative, not empirical", "premia_gain_scenarios":"10% and 25%, not forecasts"}}


def validate_entry_receipt(decision, entry, config):
    """Missing exits retain an independently checked entry and maximum-loss bound."""
    contracts=json.loads(decision['contracts_json']);quotes=json.loads(entry['quotes_json'])
    if sha(entry['quotes_json'].encode())!=entry['quote_sha256']:
        raise ValueError('Quote digest mismatch')
    if not 0<=(at(entry['received_at'])-at(decision['decision_at'])).total_seconds()<=120:
        raise ValueError('Entry capture window mismatch')
    if len(contracts)!=4 or len(quotes)!=4 or len({c['symbol'] for c in contracts})!=4 or {q['symbol'] for q in quotes}!={c['symbol'] for c in contracts}:
        raise ValueError('Changed contracts')
    times=[]
    for c in contracts:
        q=next(q for q in quotes if q['symbol']==c['symbol'])
        identity=c['root']+at(c['expiry']+'T12:00:00Z').strftime('%y%m%d')+c['right']+f"{round(c['strike']*1000):08d}"
        if c['symbol']!=identity or any(q[k]!=c[k] for k in ('root','expiry','right','strike','role','leg')) or c['expiry']<str(at(entry['received_at']).astimezone(ET).date()):
            raise ValueError('Changed contract metadata')
        if q['captured_at']!=entry['received_at'] or not q['source'].startswith('tradier_') or 'synthetic' in q['source']:
            raise ValueError('Unverified receipt')
        if not all(isinstance(q[k],(int,float)) and math.isfinite(q[k]) and q[k]>0 for k in ('bid','ask')) or q['ask']<q['bid']:
            raise ValueError('Malformed quote receipt')
        if not all(0<=(at(q['captured_at'])-at(q[k])).total_seconds()<=60 for k in ('bid_at','ask_at')):
            raise ValueError('Stale entry receipt')
        times.extend(at(q[k]) for k in ('bid_at','ask_at'))
    if (max(times)-min(times)).total_seconds()>45:
        raise ValueError('Entry cross-leg clock skew')
    fee=4*config['fee_per_contract_side_usd']+config['adverse_round_trip_usd']
    for role in ('target','control'):
        pair=[q for q in quotes if q['role']==role]
        if len(pair)!=2 or {q['leg'] for q in pair}!={'buy','sell'} or len({(q['root'],q['expiry'],q['right']) for q in pair})!=1:
            raise ValueError('Incomplete frozen contracts')
        buy=next(q for q in pair if q['leg']=='buy');sell=next(q for q in pair if q['leg']=='sell')
        if (sell['strike']-buy['strike'])*(1 if buy['right']=='C' else -1)!=config['width']:
            raise ValueError('Invalid defined risk width')
        debit=round((buy['ask']-sell['bid'])*100,2)
        if not 0<debit<100*config['width'] or debit+fee>config['max_risk_usd'] or abs(entry[role+'_debit']-debit)>.011 or abs(entry[role+'_risk']-debit-fee)>.011:
            raise ValueError('Entry arithmetic mismatch')


def validate_receipts(decision, entry, outcome, marks, config):
    """Recompute a completed quote model from the frozen identities and raw marks."""
    contracts=json.loads(decision['contracts_json'])
    ids={c['symbol'] for c in contracts}
    if len(ids)!=4 or {(c['role'],c['leg']) for c in contracts}!={(r,l) for r in ('target','control') for l in ('buy','sell')}:
        raise ValueError('Incomplete frozen contracts')
    candidates=[m for m in marks if m['decision_id']==decision['id'] and m['received_at']==outcome['received_at'] and m['state']=='QUOTE_MARK']
    if len(candidates)!=1:
        raise ValueError('Missing unique exit receipt')
    last=candidates[0]
    if not 0 <= (at(last['received_at'])-at(decision['exit_at'])).total_seconds() <= 60:
        raise ValueError('Exit window mismatch')
    groups=[]
    for receipt in (entry,last):
        if sha(receipt['quotes_json'].encode())!=receipt['quote_sha256']:
            raise ValueError('Quote digest mismatch')
        quotes=json.loads(receipt['quotes_json'])
        if len(quotes)!=4 or {q['symbol'] for q in quotes}!=ids:
            raise ValueError('Changed contracts')
        for c in contracts:
            q=next(q for q in quotes if q['symbol']==c['symbol'])
            if any(q[k]!=c[k] for k in ('root','expiry','right','strike','role','leg')):
                raise ValueError('Changed contract metadata')
            captured=at(q['captured_at'])
            if captured!=at(receipt['received_at']) or not all(0<q[k] and math.isfinite(q[k]) for k in ('bid','ask')) or q['ask']<q['bid']:
                raise ValueError('Malformed quote receipt')
            if not all(0<=(captured-at(q[k])).total_seconds()<=60 for k in ('bid_at','ask_at')) or not q['source'].startswith('tradier_') or 'synthetic' in q['source']:
                raise ValueError('Unverified receipt')
        groups.append(quotes)
    fee=4*config['fee_per_contract_side_usd']+config['adverse_round_trip_usd']
    nets={}
    for role in ('target','control'):
        buy0=next(q for q in groups[0] if q['role']==role and q['leg']=='buy')
        sell0=next(q for q in groups[0] if q['role']==role and q['leg']=='sell')
        buy1=next(q for q in groups[1] if q['role']==role and q['leg']=='buy')
        sell1=next(q for q in groups[1] if q['role']==role and q['leg']=='sell')
        debit=round(100*(buy0['ask']-sell0['bid']),2);credit=round(100*(buy1['bid']-sell1['ask']),2)
        if not 0<debit<100*config['width'] or debit+fee>config['max_risk_usd'] or not 0<=credit<=100*config['width']:
            raise ValueError('Invalid vertical value')
        if abs(entry[role+'_debit']-debit)>.011 or abs(entry[role+'_risk']-debit-fee)>.011:
            raise ValueError('Entry arithmetic mismatch')
        nets[role]=round(credit-debit-fee,2)
        if abs(outcome[role+'_net']-nets[role])>.011:
            raise ValueError('Net arithmetic mismatch')
    expected=nets['target']-nets['control']*entry['target_risk']/entry['control_risk']
    if abs(outcome['excess_net']-expected)>.011 or abs(outcome['stress_net']-(nets['target']-config['stress_extra_usd']))>.011:
        raise ValueError('Comparison arithmetic mismatch')


def prospective_scorecard(design: dict, decisions: list[dict], entries: list[dict], outcomes: list[dict], *, now: str, lock_path: Path | None=None, marks: list[dict] | None=None):
    """Fail closed on provenance/overlap; first holdout analysis is immutable.

    Routine report shows only forward development returns. Thresholds count
    complete prospective intervals, not quote rows or overlapping legs.
    """
    config = json.loads(design["config_json"])
    if sha(design["config_json"].encode()) != design["config_sha256"]:
        raise ValueError("Design digest mismatch")
    if not at(design["registered_at"]) < at(design["forward_start"]) < at(design["holdout_start"]):
        raise ValueError("Retroactive design")
    if (at(design["holdout_start"])-at(design["forward_start"])).total_seconds() != config["holdout_after_calendar_days"]*86400:
        raise ValueError("Holdout boundary changed")
    entry = {e["decision_id"]:e for e in entries}
    outcome = {o["decision_id"]:o for o in outcomes}
    if len(entry)!=len(entries) or len(outcome)!=len(outcomes) or len({d['id'] for d in decisions})!=len(decisions):
        raise ValueError("Duplicate identities")
    chosen = sorted([d for d in decisions if d["selected"]], key=lambda d:at(d["decision_at"]))
    end = None
    for d in chosen:
        if d["evidence_mode"]!='prospective' or d["config_sha256"]!=design["config_sha256"] or d["design_id"]!=config["id"] or at(d["decision_at"])<at(design["forward_start"]):
            raise ValueError("Nonprospective or changed design")
        e = entry.get(d["id"])
        if e and e["state"]=='QUOTE_MODEL':
            if end and at(d["decision_at"])<end:
                raise ValueError("Overlapping outcomes")
            end = at(d["exit_at"])
    for d in chosen:
        o=outcome.get(d['id'])
        if o and (o['evidence_mode']!='prospective' or at(o['received_at'])>at(now)):
            raise ValueError('Nonprospective or future outcome')
        if entry.get(d['id'],{}).get('state')=='QUOTE_MODEL' and o:
            validate_entry_receipt(d,entry[d['id']],config)
        if o and o['state']=='COMPLETE_QUOTE_MODEL':
            validate_receipts(d,entry[d['id']],o,marks or [],config)
    report = {"as_of":now,"design_sha256":design["config_sha256"],"holdout_start":design["holdout_start"],"strategies":[]}
    all_ready = True
    independent=config.get("evaluation_policy")=="independent_strategy_locked_evaluation_no_holdout_tuning"
    for strategy in config["strategies"]:
        ds = [d for d in chosen if d["strategy"]==strategy]
        filled = [d for d in ds if entry.get(d["id"],{}).get("state")=="QUOTE_MODEL"]
        complete = [d for d in filled if outcome.get(d["id"],{}).get("state")=="COMPLETE_QUOTE_MODEL"]
        hold = [d for d in complete if at(d["decision_at"])>=at(design["holdout_start"])]
        dev = [d for d in complete if at(d["decision_at"])<at(design["holdout_start"])]
        times = [at(d["decision_at"]) for d in complete]
        span = (max(times)-min(times)).days if times else 0
        weeks = len({t.astimezone(ET).strftime('%G-%V') for t in times})
        ready = len(complete)>=max(100,config["min_outcomes"]) and span>=max(90,config["min_calendar_span_days"]) and weeks>=max(12,config["min_entry_weeks"]) and len(hold)>=max(30,config["min_holdout_outcomes"]) and (len(complete)/len(filled) if filled else 0)>=config.get("min_completion_rate",1) and all(d["id"] in outcome for d in ds)
        all_ready &= ready
        expired=(at(now)-at(design['forward_start'])).total_seconds()>=config.get('max_collection_calendar_days',float('inf'))*86400
        mean = lambda key: round(float(np.mean([outcome[d['id']][key] for d in dev])),4) if dev else None
        equity = peak = dd = 0
        for d in dev:
            equity += outcome[d["id"]]["target_net"]
            peak = max(peak,equity);dd=max(dd,peak-equity)
        report["strategies"].append({"strategy":strategy,"selected":len(ds),"quote_model_entries":len(filled),"complete":len(complete),"incomplete":len(filled)-len(complete),
            "no_fills":sum(outcome.get(d['id'],{}).get('state')=='NO_FILL' for d in ds),"completion_rate":len(complete)/len(filled) if filled else None,
            "calendar_span_days":span,"entry_weeks":weeks,"untouched_holdout_complete":len(hold),"minima_pass":ready,"operating_state":"PAUSED_READY_FOR_LOCKED_REVIEW" if ready else "PAUSED_TIME_LIMIT" if expired else "COLLECTING",
            "development_mean_net":mean('target_net'),"development_mean_excess":mean('excess_net'),"development_mean_stress_net":mean('stress_net'),
            "development_drawdown":round(dd,2) if dev else None,"holdout_returns":"EMBARGOED","verdict":"continue collecting"})
    if independent:
        for row in report['strategies']:
            # One immutable result per strategy: a rare signal cannot stall the other.
            name=sha((design['config_sha256']+':'+row['strategy']).encode())[:20]
            path=lock_path.with_name(lock_path.stem+'-'+name+lock_path.suffix) if lock_path else None
            if path and path.exists():
                locked=json.loads(path.read_text())
                if locked.get('design_sha256')!=design['config_sha256'] or locked.get('strategy')!=row['strategy']:
                    raise ValueError('Evaluation lock mismatch')
                row.update(locked['result']);continue
            if not row['minima_pass']:
                if row['operating_state']=='PAUSED_TIME_LIMIT':
                    row['verdict']='reject'
                    row['interpretation']='Insufficient evidence within the frozen window; not a finding of negative profitability.'
                row['next_action']='REVIEW_OR_RETIRE_PROTOCOL_BEFORE_RESTART' if row['operating_state']=='PAUSED_TIME_LIMIT' else 'CONTINUE_OR_REPAIR_COLLECTION'
                continue
            row['next_action']='RUN_ONE_LOCKED_PRIVATE_HOLDOUT_REVIEW'
            if path is None:
                continue
            held=[d for d in chosen if d['strategy']==row['strategy'] and at(d['decision_at'])>=at(design['holdout_start'])]
            samples={k:[] for k in ('target_net','excess_net','stress_net')}
            missing=0
            for d in held:
                o=outcome[d['id']];e=entry.get(d['id'],{})
                if o['state']=='COMPLETE_QUOTE_MODEL':
                    values={k:o[k] for k in samples}
                elif o['state']=='MISSING_EXIT' and e.get('state')=='QUOTE_MODEL':
                    # Sensitivity bound only, explicitly NOT an observed/fabricated outcome.
                    target=-e['target_risk'];control_best=100*config['width']-e['control_risk']
                    values={'target_net':target,'excess_net':target-control_best*e['target_risk']/e['control_risk'],'stress_net':target-config['stress_extra_usd']}
                    missing+=1
                elif o['state']=='NO_FILL':
                    values={k:0. for k in samples}
                else:
                    raise ValueError('Unresolved holdout outcome')
                for k in samples:samples[k].append((d['decision_at'],values[k]))
            intervals={k:cluster_interval(v) for k,v in samples.items()}
            row.update(holdout_returns=intervals,missing_exit_sensitivity_count=missing,
                sensitivity_policy='missing target maximum loss; control maximum gain; no-fill zero',
                verdict='qualified for further paper validation' if all(x['weeks']>=4 and x['lower'] is not None and x['lower']>0 for x in intervals.values()) else 'reject',
                evaluation='FIRST_LOCKED_STRATEGY_EVALUATION',next_action='KEEP_REAL_MONEY_DISABLED_REVIEW_LOCKED_RESULT',
                interpretation='Quoted prices and minimum evidence do not prove profitability or execution.')
            locked={'design_sha256':design['config_sha256'],'strategy':row['strategy'],'evaluated_at':now,'result':row,
                'input_sha256':sha(canonical({'design':design,'decisions':decisions,'entries':entries,'outcomes':outcomes,'marks':marks}))}
            private_write(path,canonical(locked),immutable=True)
        report['evaluation']='INDEPENDENT_STRATEGY_LOCKS_HOLDOUT_EMBARGOED_UNTIL_READY'
        return report

    if not all_ready:
        return report
    if lock_path is None:
        report["evaluation"]="MINIMA_MET_REQUIRES_ONE_LOCKED_EVALUATION"
        return report
    if lock_path.exists():
        locked=json.loads(lock_path.read_text())
        if locked["design_sha256"]!=design["config_sha256"]:
            raise ValueError("Evaluation lock mismatch")
        return locked
    for row in report["strategies"]:
        selected=[d for d in chosen if d['strategy']==row['strategy'] and outcome.get(d['id'],{}).get('state')=='COMPLETE_QUOTE_MODEL']
        held=[d for d in selected if at(d['decision_at'])>=at(design['holdout_start'])]
        intervals={key:cluster_interval([(d['decision_at'],outcome[d['id']][key]) for d in held]) for key in ['target_net','excess_net','stress_net']}
        row['holdout_returns']=intervals
        row['verdict']='qualified for further paper validation' if all(x['weeks']>=4 and x['lower'] is not None and x['lower']>0 for x in intervals.values()) else 'reject'
        row['interpretation']='Minimum evidence and a quote model do not prove profitability or execution.'
    report['input_sha256']=sha(canonical({'design':design,'decisions':decisions,'entries':entries,'outcomes':outcomes}))
    report['evaluation']='FIRST_LOCKED_HOLDOUT_EVALUATION'
    private_write(lock_path,canonical(report),immutable=True)
    return report


def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('archive');a.add_argument('directory',type=Path)
    e=sub.add_parser('scorecard');e.add_argument('ledger',type=Path);e.add_argument('output',type=Path);e.add_argument('--evaluation-lock',type=Path)
    args=p.parse_args()
    if args.command=='archive':
        manifest=seal_archive(args.directory);rows,_=load_archive(args.directory)
        private_write(args.directory/'liquidity_analysis.json',canonical(summarize_costs(rows)))
        private_write(args.directory/'screen_input.json',canonical({'rows':[r for r in rows if r['kind']=='underlying']}))
        print(json.dumps({'verified_chunks':len(manifest['chunks']),'unique_rows':len(rows),'additional_database_queries':0,'manifest_sha256':sha(canonical(manifest))}))
    else:
        ledger=json.loads(args.ledger.read_text())
        result=prospective_scorecard(ledger['design'],ledger['decisions'],ledger['entries'],ledger['outcomes'],marks=ledger.get('marks',[]),now=datetime.now(UTC).isoformat(),lock_path=args.evaluation_lock)
        private_write(args.output,canonical(result))
        print(json.dumps({'strategies':[{'strategy':s['strategy'],'verdict':s['verdict']} for s in result['strategies']]}))


if __name__=='__main__':
    main()
