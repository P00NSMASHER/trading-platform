#!/usr/bin/env python3
"""Walk-forward text experiment on the public hacked_earnings_jfe corpus.

Primary executable question:
Can press-release language available in earlier calendar years rank later
announcements that are retrospectively labeled Actual=1?

This does NOT test trading returns. The repository's authorized non-synthetic
market-data manifest currently has zero active sources, so the return experiment
is explicitly fail-closed rather than silently replaced with synthetic fixtures.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import zipfile

import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from hacked_earnings_deep_research import clean400, member_key

SEED = 20261006
PRIMARY_TEST_YEARS = (2012, 2013, 2015)
ALL_TEST_YEARS = (2012, 2013, 2014, 2015)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def extract_clean_text(cache: Path) -> dict[tuple[str, str], dict]:
    import nltk
    from nltk.corpus import stopwords

    stop = set(stopwords.words("english"))
    stemmer = nltk.PorterStemmer().stem
    selected: dict[tuple[str, str], dict] = {}
    for year in range(2010, 2016):
        with zipfile.ZipFile(cache / f"Data/Press releases/{year}.zip") as archive:
            for info in sorted(archive.infolist(), key=lambda x: x.filename):
                if info.is_dir():
                    continue
                key = member_key(info.filename)
                if key is None:
                    continue
                permno, date, appendix = key
                payload = archive.read(info)
                try:
                    text = payload.decode("utf-8-sig")
                except UnicodeDecodeError:
                    text = payload.decode("cp1252", errors="replace")
                pair = (permno, date)
                candidate = {
                    "appendix": appendix,
                    "member": info.filename,
                    "sha256": sha256_bytes(payload),
                    "clean_text": " ".join(clean400(text, stop, stemmer)),
                }
                if pair not in selected or (appendix, info.filename) < (
                    selected[pair]["appendix"], selected[pair]["member"]
                ):
                    selected[pair] = candidate
    return selected


def metric_block(y: np.ndarray, score: np.ndarray, probability: bool) -> dict:
    y = np.asarray(y, dtype=int)
    score = np.asarray(score, dtype=float)
    result = {"n": int(len(y)), "positives": int(y.sum()), "base_rate": float(y.mean()) if len(y) else None}
    if not len(y):
        return result
    if y.min() != y.max():
        result["roc_auc"] = float(roc_auc_score(y, score))
        result["average_precision"] = float(average_precision_score(y, score))
    else:
        result["roc_auc"] = None
        result["average_precision"] = None
    for frac in (0.01, 0.05, 0.10):
        k = max(1, int(math.ceil(len(y) * frac)))
        idx = np.argsort(-score, kind="mergesort")[:k]
        precision = float(y[idx].mean())
        base = float(y.mean())
        result[f"top_{int(frac*100)}pct_precision"] = precision
        result[f"top_{int(frac*100)}pct_lift"] = precision / base if base > 0 else None
    if probability:
        clipped = np.clip(score, 1e-9, 1 - 1e-9)
        result["brier"] = float(brier_score_loss(y, clipped))
        result["log_loss"] = float(log_loss(y, clipped, labels=[0, 1]))
    return result


def numeric_matrix(train: pd.DataFrame, test: pd.DataFrame):
    cols = ["prior_text_jaccard_distance", "log_text_characters", "novelty_missing"]
    pipe = make_pipeline(SimpleImputer(strategy="median"), StandardScaler())
    return pipe.fit_transform(train[cols]), pipe.transform(test[cols])


def fit_predict(train: pd.DataFrame, test: pd.DataFrame):
    vectorizer = TfidfVectorizer(
        tokenizer=str.split,
        preprocessor=None,
        token_pattern=None,
        lowercase=False,
        ngram_range=(1, 2),
        min_df=5,
        max_df=0.80,
        max_features=30000,
        sublinear_tf=True,
        dtype=np.float32,
    )
    x_train_text = vectorizer.fit_transform(train["clean_text"])
    x_test_text = vectorizer.transform(test["clean_text"])
    y_train = train["Actual"].to_numpy(dtype=int)

    text_model = LogisticRegression(C=1.0, solver="liblinear", max_iter=1000, random_state=SEED)
    text_model.fit(x_train_text, y_train)
    text_prob = text_model.predict_proba(x_test_text)[:, 1]

    x_train_num, x_test_num = numeric_matrix(train, test)
    num_model = LogisticRegression(C=1.0, solver="liblinear", max_iter=1000, random_state=SEED)
    num_model.fit(x_train_num, y_train)
    novelty_prob = num_model.predict_proba(x_test_num)[:, 1]

    x_train_combined = sparse.hstack([x_train_text, sparse.csr_matrix(x_train_num)], format="csr")
    x_test_combined = sparse.hstack([x_test_text, sparse.csr_matrix(x_test_num)], format="csr")
    combined_model = LogisticRegression(C=1.0, solver="liblinear", max_iter=1000, random_state=SEED)
    combined_model.fit(x_train_combined, y_train)
    combined_prob = combined_model.predict_proba(x_test_combined)[:, 1]

    names = np.asarray(vectorizer.get_feature_names_out())
    coef = text_model.coef_[0]
    order = np.argsort(coef)
    terms = []
    for rank, idx in enumerate(order[:25], 1):
        terms.append({"direction": "negative", "rank": rank, "term": names[idx], "coefficient": float(coef[idx])})
    for rank, idx in enumerate(order[-25:][::-1], 1):
        terms.append({"direction": "positive", "rank": rank, "term": names[idx], "coefficient": float(coef[idx])})

    return {
        "text_logit": text_prob,
        "novelty_logit": novelty_prob,
        "text_novelty_logit": combined_prob,
        "terms": terms,
        "vocabulary_size": int(len(names)),
    }


def cluster_bootstrap(frame: pd.DataFrame, score_col: str, reps: int = 300) -> dict:
    if frame["Actual"].nunique() < 2:
        return {}
    rng = np.random.default_rng(SEED)
    groups = sorted(frame["GVKEY"].astype(str).unique())
    grouped = {g: frame.index[frame["GVKEY"].astype(str) == g].to_numpy() for g in groups}
    aucs, aps = [], []
    for _ in range(reps):
        sampled = rng.choice(groups, size=len(groups), replace=True)
        idx = np.concatenate([grouped[g] for g in sampled])
        boot = frame.loc[idx]
        if boot["Actual"].nunique() < 2:
            continue
        aucs.append(roc_auc_score(boot["Actual"], boot[score_col]))
        aps.append(average_precision_score(boot["Actual"], boot[score_col]))
    return {
        "cluster_bootstrap_reps": len(aucs),
        "roc_auc_ci95": [float(np.quantile(aucs, 0.025)), float(np.quantile(aucs, 0.975))],
        "average_precision_ci95": [float(np.quantile(aps, 0.025)), float(np.quantile(aps, 0.975))],
    } if aucs else {}


def run(cache: Path, features_path: Path, repo_root: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    features = pd.read_csv(features_path)
    features["PERMNO"] = features["PERMNO"].astype(str)
    features["GVKEY"] = features["GVKEY"].astype(str)
    features["date"] = features["date"].astype(str)
    features["year"] = pd.to_datetime(features["date"]).dt.year
    features["Actual"] = features["Actual"].astype(int)
    features["Hacked"] = features["Hacked"].astype(int)
    features = features[features["text_document_count"].astype(int) > 0].copy()
    if len(features) != 36750:
        raise ValueError(f"Expected 36,750 text-linked rows, got {len(features)}")

    text_map = extract_clean_text(cache)
    features["pair"] = list(zip(features["PERMNO"], features["date"]))
    missing = [pair for pair in features["pair"] if pair not in text_map]
    if missing:
        raise ValueError(f"Missing extracted text for {len(missing)} source rows")
    features["clean_text"] = [text_map[p]["clean_text"] for p in features["pair"]]
    features["content_sha256"] = [text_map[p]["sha256"] for p in features["pair"]]
    features["log_text_characters"] = np.log1p(features["selected_text_characters"].astype(float))
    features["prior_text_jaccard_distance"] = pd.to_numeric(features["prior_text_jaccard_distance"], errors="coerce")
    features["novelty_missing"] = features["prior_text_jaccard_distance"].isna().astype(int)

    market_manifest = json.loads(
        (repo_root / "data/processed/authorized_input_real/historical_market_backfill_manifest.json").read_text(encoding="utf-8")
    )
    source_count = int(market_manifest.get("source_count", 0))
    return_experiment = {
        "status": "BLOCKED_NO_AUTHORIZED_NON_SYNTHETIC_OUTCOME_DATA" if source_count == 0 else "REVIEW_REQUIRED",
        "source_count": source_count,
        "eligible_for_real_feature_backfill": market_manifest.get("non_synthetic_comparison_readiness", {}).get("eligible_for_real_feature_backfill"),
        "reasons": market_manifest.get("non_synthetic_comparison_readiness", {}).get("reasons", []),
        "synthetic_market_probe_used": False,
        "paper_target_LRet_12pm_OpenNext_present_row_level": False,
    }

    fold_rows, prediction_rows, top_term_rows, leakage_checks = [], [], [], []
    pools = {
        "full_universe": lambda x: x,
        "hacked_only_retrospective": lambda x: x[x["Hacked"] == 1],
    }

    for pool_name, selector in pools.items():
        for test_year in ALL_TEST_YEARS:
            train = selector(features[features["year"] < test_year]).copy()
            test = selector(features[features["year"] == test_year]).copy()
            if len(test) == 0 or train["Actual"].nunique() < 2:
                continue

            overlap = set(train["content_sha256"]) & set(test["content_sha256"])
            leakage_checks.append({
                "pool": pool_name,
                "test_year": test_year,
                "train_rows": len(train),
                "test_rows": len(test),
                "train_positives": int(train["Actual"].sum()),
                "test_positives": int(test["Actual"].sum()),
                "duplicate_content_hash_overlap": len(overlap),
                "strictly_earlier_training": bool(train["year"].max() < test_year),
            })
            if overlap:
                raise ValueError(f"Duplicate text crosses temporal split for {pool_name} {test_year}")

            fitted = fit_predict(train, test)
            if test_year == 2015:
                for row in fitted["terms"]:
                    top_term_rows.append({"pool": pool_name, "test_year": test_year, **row})

            scores = {
                "constant_prior": np.full(len(test), train["Actual"].mean(), dtype=float),
                "published_soft_contaminated": test["Soft"].to_numpy(dtype=float),
                "novelty_logit": fitted["novelty_logit"],
                "text_logit": fitted["text_logit"],
                "text_novelty_logit": fitted["text_novelty_logit"],
            }
            probabilities = {"constant_prior", "novelty_logit", "text_logit", "text_novelty_logit"}
            for model_name, score in scores.items():
                metrics = metric_block(test["Actual"].to_numpy(), score, model_name in probabilities)
                fold_rows.append({
                    "pool": pool_name,
                    "test_year": test_year,
                    "model": model_name,
                    "train_rows": len(train),
                    "train_positives": int(train["Actual"].sum()),
                    "test_rows": len(test),
                    "test_positives": int(test["Actual"].sum()),
                    "vocabulary_size": fitted["vocabulary_size"] if model_name in {"text_logit", "text_novelty_logit"} else "",
                    **metrics,
                })

            issuer_seen = test["GVKEY"].isin(set(train["GVKEY"]))
            for i, (_, row) in enumerate(test.iterrows()):
                prediction_rows.append({
                    "pool": pool_name,
                    "test_year": test_year,
                    "PERMNO": row["PERMNO"],
                    "GVKEY": row["GVKEY"],
                    "SYMBOL": row["SYMBOL"],
                    "date": row["date"],
                    "Actual": int(row["Actual"]),
                    "Hacked": int(row["Hacked"]),
                    "issuer_seen_in_training": bool(issuer_seen.iloc[i]),
                    "content_sha256": row["content_sha256"],
                    "published_soft_contaminated": float(scores["published_soft_contaminated"][i]),
                    "constant_prior": float(scores["constant_prior"][i]),
                    "novelty_logit": float(scores["novelty_logit"][i]),
                    "text_logit": float(scores["text_logit"][i]),
                    "text_novelty_logit": float(scores["text_novelty_logit"][i]),
                })

    predictions = pd.DataFrame(prediction_rows)
    pooled_rows, bootstrap = [], {}
    for pool_name in pools:
        pool_pred = predictions[
            (predictions["pool"] == pool_name) &
            (predictions["test_year"].isin(PRIMARY_TEST_YEARS))
        ].copy()
        for subset_name, sub in {
            "all": pool_pred,
            "unseen_issuer_only": pool_pred[~pool_pred["issuer_seen_in_training"]],
        }.items():
            for model_name in ["constant_prior", "published_soft_contaminated", "novelty_logit", "text_logit", "text_novelty_logit"]:
                probability = model_name != "published_soft_contaminated"
                metrics = metric_block(sub["Actual"].to_numpy(), sub[model_name].to_numpy(), probability)
                pooled_rows.append({"pool": pool_name, "subset": subset_name, "model": model_name, **metrics})
                if subset_name == "all" and model_name in {"published_soft_contaminated", "text_logit", "text_novelty_logit"}:
                    bootstrap[f"{pool_name}:{model_name}"] = cluster_bootstrap(sub.reset_index(drop=True), model_name)

    fold_df = pd.DataFrame(fold_rows)
    pooled_df = pd.DataFrame(pooled_rows)
    leakage_df = pd.DataFrame(leakage_checks)

    fold_df.to_csv(output / "fold_metrics.csv", index=False)
    pooled_df.to_csv(output / "pooled_metrics.csv", index=False)
    predictions.to_csv(output / "walkforward_predictions.csv", index=False)
    pd.DataFrame(top_term_rows).to_csv(output / "top_2015_text_terms.csv", index=False)
    leakage_df.to_csv(output / "leakage_checks.csv", index=False)
    features.groupby("year").agg(
        rows=("Actual", "size"),
        actual_positives=("Actual", "sum"),
        hacked_rows=("Hacked", "sum"),
    ).reset_index().to_csv(output / "year_counts.csv", index=False)

    primary = pooled_df[pooled_df["subset"] == "all"].copy()
    summary = {
        "status": "COMPLETED_RETROSPECTIVE_LABEL_EXPERIMENT",
        "question": "Can earlier-year press-release language rank later Actual=1 source labels?",
        "primary_test_years": list(PRIMARY_TEST_YEARS),
        "negative_only_source_regime_year": 2014,
        "text_rows": int(len(features)),
        "duplicate_hash_temporal_overlap": int(leakage_df["duplicate_content_hash_overlap"].sum()),
        "strictly_earlier_training_all_folds": bool(leakage_df["strictly_earlier_training"].all()),
        "return_experiment": return_experiment,
        "pooled_primary_metrics": json.loads(primary.to_json(orient="records")),
        "cluster_bootstrap": bootstrap,
        "warnings": [
            "Actual is a retrospective SEC-complaint-derived source label, not a trading return and not a live feature.",
            "Hacked-only evaluation conditions on a retrospective exposure label and is for mechanism research only.",
            "Published Soft uses coefficients fitted on the full source sample and is included only as a contaminated benchmark.",
            "Exact public release timestamps are not in archive filenames; no preannouncement tradability claim is made.",
            "The unseen-issuer subset has very few positives and is a stress test, not a powered headline result.",
            "No synthetic market fixture is used to infer return performance.",
        ],
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    def row_for(pool, model):
        return pooled_df[
            (pooled_df["pool"] == pool) &
            (pooled_df["subset"] == "all") &
            (pooled_df["model"] == model)
        ].iloc[0]

    report = [
        "# Hacked earnings walk-forward experiment",
        "",
        "## tl;dr",
        "",
        "This experiment fits text models only on earlier calendar years and evaluates later years. "
        "The executable outcome is the independent retrospective Actual=1 source label. "
        "The requested realized-return experiment remains fail-closed because the authorized real market-data manifest contains zero active sources.",
        "",
        "Primary pooled years are 2012, 2013, and 2015. The source has zero Actual/Hacked observations in 2014, so 2014 is reported separately as a negative-only regime check rather than mixed into headline discrimination metrics.",
        "",
    ]
    for pool in ("full_universe", "hacked_only_retrospective"):
        base = row_for(pool, "constant_prior")
        soft = row_for(pool, "published_soft_contaminated")
        text = row_for(pool, "text_logit")
        combined = row_for(pool, "text_novelty_logit")
        report += [
            f"## {pool.replace('_', ' ').title()}",
            "",
            f"- Evaluated rows: **{int(text['n']):,}**; positives: **{int(text['positives']):,}**; base rate: **{text['base_rate']:.3%}**.",
            f"- Past-only text model: ROC AUC **{text['roc_auc']:.3f}**, average precision **{text['average_precision']:.3f}**.",
            f"- Past-only text + novelty: ROC AUC **{combined['roc_auc']:.3f}**, average precision **{combined['average_precision']:.3f}**.",
            f"- Published full-sample Soft benchmark: ROC AUC **{soft['roc_auc']:.3f}**, average precision **{soft['average_precision']:.3f}**.",
            f"- Constant-prior baseline: ROC AUC **{base['roc_auc']:.3f}**, average precision **{base['average_precision']:.3f}**.",
            "",
        ]
    report += [
        "## Return experiment status",
        "",
        f"- Authorized non-synthetic market source count: **{source_count}**.",
        f"- Real feature backfill eligible: **{return_experiment['eligible_for_real_feature_backfill']}**.",
        "- Synthetic market fixtures were explicitly excluded.",
        "- Therefore no realized-return, excess-return, Sharpe, or profitability statistic is reported.",
        "",
        "## Leakage and robustness checks",
        "",
        f"- Duplicate text hashes crossing train/test: **{int(leakage_df['duplicate_content_hash_overlap'].sum())}**.",
        f"- All temporal folds strictly earlier-only: **{bool(leakage_df['strictly_earlier_training'].all())}**.",
        "- TF-IDF vocabulary is fit separately inside each training fold.",
        "- 2014 is retained as a negative-only source-regime diagnostic, not used to inflate AUC.",
        "- Unseen-issuer results are exported separately and are low-power because very few Actual=1 rows occur for issuers absent from prior-year training.",
        "",
        "## Files",
        "",
        "- fold_metrics.csv: year-by-year results.",
        "- pooled_metrics.csv: pooled primary-year and unseen-issuer stress tests.",
        "- walkforward_predictions.csv: row-level predictions for audit.",
        "- top_2015_text_terms.csv: largest 2015-fold coefficients; associative, not causal.",
        "- leakage_checks.csv: temporal and duplicate-content assertions.",
        "- summary.json: machine-readable experiment receipt.",
        "",
    ]
    (output / "REPORT.md").write_text("\n".join(report), encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.cache, args.features, args.repo_root, args.output), indent=2, allow_nan=False))
