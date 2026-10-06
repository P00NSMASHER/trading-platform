#!/usr/bin/env python3
"""Leakage-resistant out-of-time hacked-earnings text experiment.

Research only. Fits text models strictly on earlier calendar years, evaluates
only events with an exact G1 public-release timestamp, purges test-year issuers
and duplicate text from the primary training set, and uses the next trading
session's open-to-close return minus SPY as the realized outcome.
"""
from __future__ import annotations

import argparse
import collections
import functools
import hashlib
import json
import math
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.linear_model import ElasticNetCV, LinearRegression
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import GroupKFold

from hacked_earnings_deep_research import SOURCE_SHA, clean400, download_sources, member_key

RNG_SEED = 20261006
MARKET_SOURCE = "Yahoo Finance daily OHLC via yfinance 1.7.0"
BENCHMARK = "SPY"
SOURCE_START = "2010-01-01"
SOURCE_END = "2016-01-15"
TEST_YEARS = (2011, 2012, 2013, 2014, 2015)
MAX_SESSION_GAP_DAYS = 7


def load_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"PERMNO": str, "GVKEY": str, "SYMBOL": str})


def safe_float(value):
    try:
        x = float(value)
    except (TypeError, ValueError):
        return np.nan
    return x if math.isfinite(x) else np.nan


def yahoo_symbol(symbol: str) -> str:
    return str(symbol).strip().upper().replace(".", "-").replace("/", "-")


def fetch_yahoo_histories(symbols: list[str], output: Path, batch_size: int = 80):
    import yfinance as yf

    cache_path = output / "yahoo_daily_cache.csv.gz"
    alias_path = output / "yahoo_symbol_aliases.csv"
    aliases = {s: yahoo_symbol(s) for s in symbols}
    if cache_path.exists():
        cached = pd.read_csv(cache_path, parse_dates=["date"])
        histories = {
            sym: g[["date", "open", "close"]].dropna().sort_values("date").reset_index(drop=True)
            for sym, g in cached.groupby("source_symbol", sort=False)
        }
        return histories, {"cache_used": True, "requested_symbols": len(symbols), "returned_symbols": len(histories)}

    unique_aliases = sorted(set(aliases.values()) | {BENCHMARK})
    frames, failures = [], {}

    def normalize_download(data: pd.DataFrame, batch: list[str]):
        if data is None or data.empty:
            for ticker in batch:
                failures.setdefault(ticker, "empty_batch")
            return
        if isinstance(data.columns, pd.MultiIndex):
            level0 = set(map(str, data.columns.get_level_values(0)))
            ticker_first = any(t in level0 for t in batch)
            for ticker in batch:
                try:
                    part = data[ticker] if ticker_first else data.xs(ticker, axis=1, level=1)
                except Exception:
                    failures.setdefault(ticker, "ticker_missing_from_batch")
                    continue
                if part.empty or "Open" not in part or "Close" not in part:
                    failures.setdefault(ticker, "ohlc_missing")
                    continue
                temp = pd.DataFrame({
                    "date": pd.to_datetime(part.index).tz_localize(None),
                    "open": pd.to_numeric(part["Open"], errors="coerce").values,
                    "close": pd.to_numeric(part["Close"], errors="coerce").values,
                    "yahoo_symbol": ticker,
                }).dropna(subset=["date", "open", "close"])
                if not temp.empty:
                    frames.append(temp)
        else:
            ticker = batch[0]
            if "Open" in data and "Close" in data:
                temp = pd.DataFrame({
                    "date": pd.to_datetime(data.index).tz_localize(None),
                    "open": pd.to_numeric(data["Open"], errors="coerce").values,
                    "close": pd.to_numeric(data["Close"], errors="coerce").values,
                    "yahoo_symbol": ticker,
                }).dropna(subset=["date", "open", "close"])
                if not temp.empty:
                    frames.append(temp)

    for start in range(0, len(unique_aliases), batch_size):
        batch = unique_aliases[start:start + batch_size]
        print(f"Yahoo batch {start//batch_size + 1}: {start + 1}-{min(start+batch_size, len(unique_aliases))}/{len(unique_aliases)}", flush=True)
        try:
            data = yf.download(
                tickers=batch, start=SOURCE_START, end=SOURCE_END, group_by="ticker",
                auto_adjust=False, actions=False, progress=False,
                threads=min(16, len(batch)), repair=False, timeout=20,
            )
            normalize_download(data, batch)
        except Exception as exc:
            for ticker in batch:
                failures.setdefault(ticker, f"batch_exception:{type(exc).__name__}")
        time.sleep(0.15)

    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["date", "open", "close", "yahoo_symbol"])
    combined = combined.drop_duplicates(["yahoo_symbol", "date"], keep="last")
    have = set(combined["yahoo_symbol"].unique())

    for ticker in [t for t in unique_aliases if t not in have][:500]:
        try:
            data = yf.download(
                ticker, start=SOURCE_START, end=SOURCE_END, auto_adjust=False,
                actions=False, progress=False, threads=False, repair=False, timeout=20,
            )
            before = len(frames)
            normalize_download(data, [ticker])
            if len(frames) > before:
                failures.pop(ticker, None)
        except Exception as exc:
            failures[ticker] = f"individual_exception:{type(exc).__name__}"
        time.sleep(0.08)

    combined = pd.concat(frames, ignore_index=True).drop_duplicates(["yahoo_symbol", "date"], keep="last") if frames else combined
    reverse = collections.defaultdict(list)
    for source, alias in aliases.items():
        reverse[alias].append(source)
    histories = {}
    for alias, part in combined.groupby("yahoo_symbol", sort=False):
        base = part[["date", "open", "close"]].sort_values("date").reset_index(drop=True)
        if alias == BENCHMARK:
            histories[BENCHMARK] = base
        for source in reverse.get(alias, []):
            histories[source] = base

    persisted = []
    for source, hist in histories.items():
        h = hist.copy()
        h["source_symbol"] = source
        persisted.append(h)
    if persisted:
        pd.concat(persisted, ignore_index=True).to_csv(cache_path, index=False, compression="gzip")
    pd.DataFrame([
        {"source_symbol": s, "yahoo_symbol": a, "history_found": s in histories}
        for s, a in sorted(aliases.items())
    ]).to_csv(alias_path, index=False)
    return histories, {
        "cache_used": False,
        "requested_symbols": len(symbols),
        "requested_yahoo_aliases": len(unique_aliases),
        "returned_symbols": len([s for s in symbols if s in histories]),
        "benchmark_found": BENCHMARK in histories,
        "failure_count": len(failures),
        "failures": failures,
    }


def next_session_outcome(hist, spy, feature_date: str):
    blank = {
        "outcome_date": "", "stock_open": np.nan, "stock_close": np.nan,
        "raw_open_close_return": np.nan, "spy_open_close_return": np.nan,
        "market_adjusted_open_close_return": np.nan, "outcome_status": "missing_stock_history",
    }
    if hist is None or hist.empty:
        return blank
    d = pd.Timestamp(feature_date)
    future = hist[hist["date"] > d]
    if future.empty:
        blank["outcome_status"] = "no_later_session"
        return blank
    bar = future.iloc[0]
    gap = (bar["date"].date() - d.date()).days
    if gap > MAX_SESSION_GAP_DAYS:
        blank["outcome_status"] = "next_session_gap_too_large"
        return blank
    if not (bar["open"] > 0 and bar["close"] > 0):
        blank["outcome_status"] = "invalid_stock_ohlc"
        return blank
    raw = float(bar["close"] / bar["open"] - 1.0)
    spy_ret = np.nan
    if spy is not None and not spy.empty:
        match = spy[spy["date"] == bar["date"]]
        if not match.empty and match.iloc[0]["open"] > 0 and match.iloc[0]["close"] > 0:
            spy_ret = float(match.iloc[0]["close"] / match.iloc[0]["open"] - 1.0)
    return {
        "outcome_date": bar["date"].date().isoformat(),
        "stock_open": float(bar["open"]), "stock_close": float(bar["close"]),
        "raw_open_close_return": raw, "spy_open_close_return": spy_ret,
        "market_adjusted_open_close_return": raw - spy_ret if math.isfinite(spy_ret) else np.nan,
        "outcome_status": "ok_market_adjusted" if math.isfinite(spy_ret) else "ok_raw_only",
    }


def load_clean_texts(cache: Path):
    import nltk
    from nltk.corpus import stopwords

    stop = set(stopwords.words("english"))
    stem = functools.lru_cache(maxsize=250_000)(nltk.PorterStemmer().stem)
    result = {}
    for year in range(2010, 2016):
        with zipfile.ZipFile(cache / f"Data/Press releases/{year}.zip") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                key = member_key(info.filename)
                if key is None:
                    continue
                payload = zf.read(info)
                try:
                    text = payload.decode("utf-8-sig")
                except UnicodeDecodeError:
                    text = payload.decode("cp1252", errors="replace")
                pair = (key[0], key[1])
                if pair in result:
                    raise ValueError(f"Unexpected multiple text documents for {pair}")
                result[pair] = {
                    "clean_text": " ".join(clean400(text, stop, stem)),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
    return result


def make_union_groups(frame: pd.DataFrame):
    n = len(frame)
    parent, rank = list(range(n)), [0] * n

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        if rank[ra] < rank[rb]:
            ra, rb = rb, ra
        parent[rb] = ra
        if rank[ra] == rank[rb]:
            rank[ra] += 1

    seen_permno, seen_hash = {}, {}
    for i, row in enumerate(frame.itertuples(index=False)):
        p, h = str(row.PERMNO), str(row.text_sha256)
        if p in seen_permno:
            union(i, seen_permno[p])
        else:
            seen_permno[p] = i
        if h in seen_hash:
            union(i, seen_hash[h])
        else:
            seen_hash[h] = i
    roots = [find(i) for i in range(n)]
    remap = {r: j for j, r in enumerate(sorted(set(roots)))}
    return np.array([remap[r] for r in roots])


def fit_text_model(train: pd.DataFrame, test: pd.DataFrame):
    train = train.sort_values(["date", "PERMNO"]).reset_index(drop=True)
    n = len(train)
    min_df = max(2, int(math.floor(0.005 * n)))
    max_df = max(min_df + 1, int(math.floor(0.4 * n)))
    vect = CountVectorizer(min_df=min_df, max_df=max_df)
    X = vect.fit_transform(train["clean_text"])
    X_test = vect.transform(test["clean_text"])
    y = train["market_adjusted_open_close_return"].astype(float).to_numpy()
    groups = make_union_groups(train)
    n_groups = len(set(groups))
    if n_groups < 5:
        raise ValueError("Insufficient issuer/content groups for grouped CV")
    cv = list(GroupKFold(n_splits=5).split(X, y, groups=groups))
    model = ElasticNetCV(
        l1_ratio=0.5, alphas=np.logspace(-6, -1, 30), cv=cv,
        max_iter=10000, n_jobs=-1, fit_intercept=True, tol=1e-5,
    )
    model.fit(X, y)
    return model.predict(X_test), {
        "train_rows": n, "train_permnos": int(train["PERMNO"].nunique()),
        "train_components": int(n_groups), "vocabulary": int(len(vect.vocabulary_)),
        "min_df_count": int(min_df), "max_df_count": int(max_df),
        "alpha": float(model.alpha_), "l1_ratio": 0.5,
    }


def fit_novelty_model(train: pd.DataFrame, test: pd.DataFrame):
    tr = train.dropna(subset=["prior_text_jaccard_distance", "market_adjusted_open_close_return"])
    if len(tr) < 50:
        return np.full(len(test), np.nan)
    model = LinearRegression().fit(
        tr[["prior_text_jaccard_distance"]],
        tr["market_adjusted_open_close_return"],
    )
    fill = tr["prior_text_jaccard_distance"].median()
    return model.predict(test[["prior_text_jaccard_distance"]].fillna(fill))


def metric_summary(frame: pd.DataFrame, pred_col: str):
    d = frame[[pred_col, "market_adjusted_open_close_return", "PERMNO", "test_year"]].dropna()
    if len(d) < 4:
        return {"predictor": pred_col, "n": int(len(d))}
    x = d[pred_col].to_numpy(float)
    y = d["market_adjusted_open_close_return"].to_numpy(float)
    pearson = float(stats.pearsonr(x, y).statistic) if np.std(x) and np.std(y) else np.nan
    spearman = float(stats.spearmanr(x, y).statistic) if np.std(x) and np.std(y) else np.nan
    direction = float(np.mean(np.sign(x) == np.sign(y)))
    order = np.argsort(x)
    q = max(1, len(d) // 4)
    low, high = y[order[:q]], y[order[-q:]]
    return {
        "predictor": pred_col, "n": int(len(d)),
        "pearson_ic": pearson, "spearman_ic": spearman,
        "direction_accuracy": direction,
        "mae": float(mean_absolute_error(y, x)), "r2": float(r2_score(y, x)),
        "top_quartile_mean_outcome": float(np.mean(high)),
        "bottom_quartile_mean_outcome": float(np.mean(low)),
        "top_minus_bottom_outcome": float(np.mean(high) - np.mean(low)),
    }


def year_block_permutation_p(frame: pd.DataFrame, pred_col: str, reps: int = 3000):
    d = frame[[pred_col, "market_adjusted_open_close_return", "test_year"]].dropna().copy()
    if len(d) < 5:
        return np.nan
    observed = stats.spearmanr(d[pred_col], d["market_adjusted_open_close_return"]).statistic
    rng = np.random.default_rng(RNG_SEED)
    more = 0
    year_values = d["test_year"].to_numpy()
    for _ in range(reps):
        perm = d[pred_col].to_numpy().copy()
        for year in d["test_year"].unique():
            idx = np.flatnonzero(year_values == year)
            perm[idx] = rng.permutation(perm[idx])
        stat = stats.spearmanr(perm, d["market_adjusted_open_close_return"]).statistic
        more += abs(stat) >= abs(observed)
    return float((more + 1) / (reps + 1))


def cluster_bootstrap_ci(frame: pd.DataFrame, pred_col: str, reps: int = 2000):
    d = frame[[pred_col, "market_adjusted_open_close_return", "PERMNO"]].dropna().copy()
    groups = {p: g for p, g in d.groupby("PERMNO")}
    keys = list(groups)
    if len(keys) < 5:
        return {}
    rng = np.random.default_rng(RNG_SEED + 1)
    vals = []
    for _ in range(reps):
        sampled = rng.choice(keys, size=len(keys), replace=True)
        b = pd.concat([groups[k] for k in sampled], ignore_index=True)
        if b[pred_col].std() == 0 or b["market_adjusted_open_close_return"].std() == 0:
            continue
        vals.append(stats.spearmanr(b[pred_col], b["market_adjusted_open_close_return"]).statistic)
    return {
        "spearman_cluster_bootstrap_ci_2_5": float(np.quantile(vals, .025)),
        "spearman_cluster_bootstrap_ci_97_5": float(np.quantile(vals, .975)),
        "bootstrap_reps_valid": int(len(vals)),
    } if vals else {}


def run(args):
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    download_sources(args.cache)

    sample = load_csv(args.prep / "sample_text_features.csv")
    events = load_csv(args.prep / "event_174_text_features.csv")
    announcements = pd.read_csv(args.announcement_resolutions, dtype=str)
    if len(sample) != 43687 or len(events) != 174 or len(announcements) != 174:
        raise ValueError("Pinned sample/event/G1 counts changed")
    if not announcements["resolution_status"].eq("resolved_exact_public_timestamp").all():
        raise ValueError("All 174 G1 timestamps must be exact-resolved before this experiment")

    clean = load_clean_texts(args.cache)
    sample["date"] = sample["date"].astype(str)
    sample["text_key"] = list(zip(sample["PERMNO"], sample["date"]))
    sample["clean_text"] = [clean.get(k, {}).get("clean_text") for k in sample["text_key"]]
    sample["text_sha256"] = [clean.get(k, {}).get("sha256") for k in sample["text_key"]]
    sample["prior_text_jaccard_distance"] = pd.to_numeric(sample["prior_text_jaccard_distance"], errors="coerce")
    sample["Soft"] = pd.to_numeric(sample["Soft"], errors="coerce")
    text_sample = sample[sample["clean_text"].notna()].copy()
    if len(text_sample) != 36750:
        raise ValueError("Text linkage changed from validated 36,750 rows")

    symbols = sorted(set(text_sample["SYMBOL"].dropna().astype(str)))
    histories, market_meta = fetch_yahoo_histories(symbols, output)
    spy = histories.get(BENCHMARK)
    outcomes = []
    for row in text_sample.itertuples(index=False):
        result = next_session_outcome(histories.get(str(row.SYMBOL)), spy, str(row.date))
        result.update({"PERMNO": str(row.PERMNO), "GVKEY": str(row.GVKEY), "SYMBOL": str(row.SYMBOL), "date": str(row.date)})
        outcomes.append(result)
    outcomes_df = pd.DataFrame(outcomes)
    outcomes_df.to_csv(output / "sample_next_session_outcomes.csv", index=False)
    merged = text_sample.merge(outcomes_df, on=["PERMNO", "GVKEY", "SYMBOL", "date"], how="left", validate="one_to_one")

    ann = announcements.copy()
    ann["event_date"] = ann["event_date"].astype(str)
    ann_map = {(r.historical_symbol, r.event_date): r for r in ann.itertuples(index=False)}
    event_records = []
    for er in events.itertuples(index=False):
        trade_date = str(er.TimeOfFirstTrade)[:10]
        a = ann_map.get((str(er.SYMBOL), trade_date))
        if a is None:
            raise ValueError(f"Missing exact G1 row for {er.SYMBOL} {trade_date}")
        pub_utc = pd.Timestamp(a.public_announcement_ts)
        if pub_utc.tzinfo is None:
            pub_utc = pub_utc.tz_localize("UTC")
        local_date = pub_utc.tz_convert("America/New_York").date().isoformat()
        base = merged[(merged["PERMNO"] == str(er.PERMNO)) & (merged["date"] == str(er.date))]
        record = {
            "source_trade_row": int(er.source_trade_row), "event_id": a.event_id,
            "PERMNO": str(er.PERMNO), "GVKEY": str(er.GVKEY), "SYMBOL": str(er.SYMBOL),
            "first_trade_ts": str(er.TimeOfFirstTrade), "public_announcement_ts": a.public_announcement_ts,
            "announcement_local_date": local_date, "text_date": str(er.date),
            "exact_text_date_match": str(er.date) == local_date,
            "timestamp_confidence": a.timestamp_confidence,
            "information_asymmetry_seconds": safe_float(a.information_asymmetry_seconds),
            "Soft": safe_float(er.Soft),
            "prior_text_jaccard_distance": safe_float(er.prior_text_jaccard_distance),
        }
        if not base.empty:
            b = base.iloc[0]
            for c in ["clean_text", "text_sha256", "outcome_date", "stock_open", "stock_close",
                      "raw_open_close_return", "spy_open_close_return",
                      "market_adjusted_open_close_return", "outcome_status"]:
                record[c] = b[c]
        event_records.append(record)
    event_df = pd.DataFrame(event_records)
    event_df["test_year"] = pd.to_datetime(event_df["text_date"]).dt.year
    event_df.to_csv(output / "event_eligibility_audit.csv", index=False)

    primary_events = event_df[
        event_df["exact_text_date_match"].eq(True)
        & event_df["clean_text"].notna()
        & pd.to_numeric(event_df["market_adjusted_open_close_return"], errors="coerce").notna()
    ].copy()
    primary_events["market_adjusted_open_close_return"] = pd.to_numeric(primary_events["market_adjusted_open_close_return"], errors="coerce")
    primary_events["prior_text_jaccard_distance"] = pd.to_numeric(primary_events["prior_text_jaccard_distance"], errors="coerce")
    primary_events["published_soft_reference"] = pd.to_numeric(primary_events["Soft"], errors="coerce")

    merged["year"] = pd.to_datetime(merged["date"]).dt.year
    merged["market_adjusted_open_close_return"] = pd.to_numeric(merged["market_adjusted_open_close_return"], errors="coerce")
    merged["prior_text_jaccard_distance"] = pd.to_numeric(merged["prior_text_jaccard_distance"], errors="coerce")

    model_receipts, predictions = [], []
    for year in TEST_YEARS:
        test = primary_events[primary_events["test_year"] == year].copy().sort_values(["text_date", "PERMNO"])
        if test.empty:
            model_receipts.append({"test_year": year, "status": "no_eligible_test_events"})
            continue
        train = merged[
            (merged["year"] < year)
            & merged["market_adjusted_open_close_return"].notna()
            & merged["clean_text"].notna()
        ].copy()
        if len(train) < 500:
            model_receipts.append({"test_year": year, "status": "insufficient_training", "train_rows": len(train)})
            continue

        pred_all, meta_all = fit_text_model(train, test)
        test_permnos = set(test["PERMNO"].astype(str))
        test_hashes = set(test["text_sha256"].dropna().astype(str))
        purged = train[
            (~train["PERMNO"].astype(str).isin(test_permnos))
            & (~train["text_sha256"].astype(str).isin(test_hashes))
        ].copy()
        pred_purged, meta_purged = fit_text_model(purged, test)
        pred_novelty = fit_novelty_model(purged, test)

        for i, (_, row) in enumerate(test.iterrows()):
            rec = row.to_dict()
            rec["oos_text_all_prior"] = float(pred_all[i])
            rec["oos_text_issuer_duplicate_purged"] = float(pred_purged[i])
            rec["oos_novelty_only"] = float(pred_novelty[i]) if math.isfinite(pred_novelty[i]) else np.nan
            predictions.append(rec)
        model_receipts.append({
            "test_year": year, "status": "fit", "test_events": len(test),
            "all_prior": meta_all, "issuer_duplicate_purged": meta_purged,
            "purged_rows_removed": int(len(train) - len(purged)),
            "test_issuers": int(test["PERMNO"].nunique()),
        })
        print(f"Fitted {year}: train={len(train):,}, purged={len(purged):,}, test={len(test)}", flush=True)

    pred_df = pd.DataFrame(predictions)
    if pred_df.empty:
        raise RuntimeError("No eligible event predictions produced")
    pred_df.drop(columns=["clean_text"], errors="ignore").to_csv(output / "event_predictions.csv", index=False)
    (output / "year_model_receipts.json").write_text(json.dumps(model_receipts, indent=2, default=str) + "\n")

    predictors = [
        "oos_text_issuer_duplicate_purged",
        "oos_text_all_prior",
        "oos_novelty_only",
        "published_soft_reference",
    ]
    metrics = []
    for col in predictors:
        m = metric_summary(pred_df, col)
        m["year_block_permutation_p_spearman"] = year_block_permutation_p(pred_df, col)
        m.update(cluster_bootstrap_ci(pred_df, col))
        metrics.append(m)
    pd.DataFrame(metrics).to_csv(output / "overall_metrics.csv", index=False)

    year_metrics = []
    for year, part in pred_df.groupby("test_year"):
        for col in predictors:
            m = metric_summary(part, col)
            m["test_year"] = int(year)
            year_metrics.append(m)
    pd.DataFrame(year_metrics).to_csv(output / "year_metrics.csv", index=False)

    coverage = {
        "sample_text_rows": int(len(text_sample)),
        "sample_rows_with_market_adjusted_outcome": int(merged["market_adjusted_open_close_return"].notna().sum()),
        "sample_outcome_coverage": float(merged["market_adjusted_open_close_return"].notna().mean()),
        "core_events": 174,
        "core_events_with_text": int(event_df["clean_text"].notna().sum()),
        "core_events_exact_text_date_match": int(event_df["exact_text_date_match"].sum()),
        "core_events_with_market_adjusted_outcome": int(pd.to_numeric(event_df["market_adjusted_open_close_return"], errors="coerce").notna().sum()),
        "primary_evaluation_events": int(len(pred_df)),
        "primary_unique_issuers": int(pred_df["PERMNO"].nunique()),
        "test_year_counts": {str(int(k)): int(v) for k, v in pred_df["test_year"].value_counts().sort_index().items()},
    }
    primary_metric = next(m for m in metrics if m["predictor"] == "oos_text_issuer_duplicate_purged")
    novelty_metric = next(m for m in metrics if m["predictor"] == "oos_novelty_only")
    soft_metric = next(m for m in metrics if m["predictor"] == "published_soft_reference")

    summary = {
        "status": "COMPLETED_EXPLORATORY_OUT_OF_TIME_EXPERIMENT",
        "source_text_commit": SOURCE_SHA,
        "g1_exact_timestamp_rows": 174,
        "market_data_source": MARKET_SOURCE,
        "outcome_definition": "next trading session open-to-close stock return minus SPY open-to-close return; session strictly after text/source date",
        "training_rule": "for test year Y use only rows dated before Jan 1 Y",
        "primary_purge_rule": "exclude all prior rows for test-year treated PERMNOs and any training text hash identical to test text",
        "cv_rule": "5-fold GroupKFold over connected issuer/content components inside the earlier-only training set",
        "coverage": coverage,
        "primary_metric": primary_metric,
        "novelty_metric": novelty_metric,
        "published_soft_reference_metric": soft_metric,
        "market_fetch": market_meta,
        "canonical_coverage_change": {"G1": 0, "G2": 0, "G3": 0, "G4": 0, "G5": 0},
        "limitations": [
            "Yahoo Finance daily bars are exploratory public outcome data, not canonical G2 market-data evidence.",
            "Training press-release dates are source archive dates, not independently verified exact release clocks; using only prior calendar years prevents same-day look-ahead into held-out years.",
            "Primary test features require the archive text date to equal the independently resolved G1 public-announcement date in America/New_York.",
            "Next-session open-to-close return deliberately omits immediate after-hours/overnight reaction and intraday microstructure.",
            "Ticker-only public price retrieval can miss delisted or renamed securities; missing outcomes are excluded and coverage is reported.",
            "The 174 core events are selected historical illicit-trading cases, not a random population of earnings announcements.",
            "Published Soft is an optimistic in-sample reference and is not treated as a fair out-of-time benchmark.",
            "Top-minus-bottom values are descriptive outcome spreads, not executable portfolio returns; no costs, capacity, or slippage are modeled.",
        ],
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2, default=str, allow_nan=False) + "\n")

    def pct(x):
        return "n/a" if x is None or not math.isfinite(float(x)) else f"{100*float(x):.2f}%"

    def dec(x):
        return "n/a" if x is None or not math.isfinite(float(x)) else f"{float(x):.3f}"

    report = [
        "# Out-of-time hacked-earnings text experiment", "",
        "## Executive Summary", "",
        f"The experiment produced **{len(pred_df)} leakage-screened event predictions across {pred_df['PERMNO'].nunique()} issuers** using exact G1 public-release dates for test eligibility and earlier-calendar-year training only.", "",
        f"The primary issuer/duplicate-purged text model has Spearman IC **{dec(primary_metric.get('spearman_ic'))}**, Pearson IC **{dec(primary_metric.get('pearson_ic'))}**, and top-minus-bottom descriptive next-session market-adjusted outcome **{pct(primary_metric.get('top_minus_bottom_outcome'))}**. Year-block permutation p-value for the rank relationship is **{dec(primary_metric.get('year_block_permutation_p_spearman'))}**.", "",
        f"The language-change-only model has Spearman IC **{dec(novelty_metric.get('spearman_ic'))}**. The original published Soft score is shown only as an in-sample reference (Spearman **{dec(soft_metric.get('spearman_ic'))}**) and is not credited as out-of-time evidence.", "",
        "## Design", "",
        "- Test years: 2011–2015. Each year is scored by a model trained only on earlier calendar years.",
        "- Primary model removes all earlier observations from issuers appearing in that test year and any training text identical to held-out text.",
        "- Hyperparameter selection uses grouped folds over connected issuer/content components.",
        "- Outcome is the next trading session's open-to-close stock return minus SPY's same-session return, with the session strictly after the text date.",
        "- Test text is admitted only when its archive date equals the independently resolved G1 public-announcement date in New York time.", "",
        "## Coverage", "",
        f"- Source text observations: {coverage['sample_text_rows']:,}",
        f"- Source text rows with usable market-adjusted outcome: {coverage['sample_rows_with_market_adjusted_outcome']:,} ({100*coverage['sample_outcome_coverage']:.1f}%)",
        f"- Core events with text: {coverage['core_events_with_text']} / 174",
        f"- Core events whose text date matches exact G1 public-release date: {coverage['core_events_exact_text_date_match']} / 174",
        f"- Final leakage-screened evaluation rows: {coverage['primary_evaluation_events']}", "",
        "## Predictor comparison", "",
        "| Predictor | N | Spearman | Pearson | Direction | Top-bottom outcome | Permutation p |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for m in metrics:
        report.append(
            f"| {m['predictor']} | {m.get('n','')} | {dec(m.get('spearman_ic'))} | {dec(m.get('pearson_ic'))} | "
            f"{pct(m.get('direction_accuracy'))} | {pct(m.get('top_minus_bottom_outcome'))} | {dec(m.get('year_block_permutation_p_spearman'))} |"
        )
    report += ["", "## Interpretation guardrails", ""] + [f"- {x}" for x in summary["limitations"]]
    report += ["", "## Artifacts", "",
               "event_predictions.csv contains held-out event predictions and realized outcomes. overall_metrics.csv and year_metrics.csv contain aggregate and year-specific diagnostics. year_model_receipts.json records training-set sizes, vocabulary sizes, CV grouping and selected alpha for every yearly fit.", ""]
    (output / "REPORT.md").write_text("\n".join(report), encoding="utf-8")

    hashes = {}
    for p in sorted(output.iterdir()):
        if p.is_file() and p.name not in {"output_hashes.json", "yahoo_daily_cache.csv.gz"}:
            hashes[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    (output / "output_hashes.json").write_text(json.dumps(hashes, indent=2) + "\n")
    print(json.dumps(summary, indent=2, default=str, allow_nan=False), flush=True)
    return summary


def self_test():
    assert yahoo_symbol("BRK.B") == "BRK-B"
    toy = pd.DataFrame({"date": pd.to_datetime(["2015-01-02", "2015-01-05"]), "open": [100., 101.], "close": [101., 100.]})
    spy = pd.DataFrame({"date": pd.to_datetime(["2015-01-02", "2015-01-05"]), "open": [200., 202.], "close": [201., 203.]})
    out = next_session_outcome(toy, spy, "2015-01-02")
    assert out["outcome_date"] == "2015-01-05"
    assert abs(out["market_adjusted_open_close_return"] - ((100/101-1) - (203/202-1))) < 1e-12
    groups = make_union_groups(pd.DataFrame({"PERMNO":["1","1","2","3"], "text_sha256":["a","b","b","c"]}))
    assert groups[0] == groups[1] == groups[2] and groups[3] != groups[0]
    print("self-test: PASS")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prep", type=Path, default=Path("data/processed/hacked_earnings_deep"))
    p.add_argument("--cache", type=Path, default=Path("private_runtime/hacked_earnings_source"))
    p.add_argument("--announcement-resolutions", type=Path, default=Path("data/processed/authorized_input_real/announcement_resolutions.csv"))
    p.add_argument("--output", type=Path, default=Path("data/processed/hacked_earnings_oos"))
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    if args.self_test:
        self_test()
        sys.exit(0)
    run(args)
