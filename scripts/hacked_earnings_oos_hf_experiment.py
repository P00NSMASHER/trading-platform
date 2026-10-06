#!/usr/bin/env python3
"""Run the OOS hacked-earnings experiment against a pinned bulk daily-price snapshot."""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd
import pyarrow.dataset as pads
from huggingface_hub import hf_hub_download

import hacked_earnings_oos_experiment as base

HF_REPO = "paperswithbacktest/Stocks-Daily-Price"
HF_REVISION = "a4aead2543e91598321225b72100abead3ec8908"
HF_FILES = [f"data/train-{i:05d}-of-00004.parquet" for i in range(4)]
SPY_REPO = "hackingthemarkets/datasets"
SPY_COMMIT = "1f545c1cd9c6ed5764732f23c27f7172128fce0f"
SPY_PATH = "spy.csv"
SPY_GIT_BLOB_SHA1 = "effa9438da8a115c30af95d530d11ac9c491bb15"
START = "2010-01-01"
END = "2016-01-15"


def git_blob_hash(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def fetch_spy() -> tuple[pd.DataFrame, dict]:
    url = f"https://raw.githubusercontent.com/{SPY_REPO}/{SPY_COMMIT}/{SPY_PATH}"
    with urlopen(Request(url, headers={"User-Agent": "hacked-earnings-oos/1.0"}), timeout=60) as response:
        payload = response.read()
    if git_blob_hash(payload) != SPY_GIT_BLOB_SHA1:
        raise ValueError("Pinned SPY source blob mismatch")
    from io import BytesIO
    df = pd.read_csv(BytesIO(payload))
    df.columns = [str(c).strip().lower() for c in df.columns]
    if not {"date", "open", "close"}.issubset(df.columns):
        raise ValueError(f"Unexpected SPY schema: {list(df.columns)}")
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    df["open"] = pd.to_numeric(df["open"], errors="coerce")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df[(df["date"] >= START) & (df["date"] <= END)][["date", "open", "close"]].dropna()
    return df.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True), {
        "repo": SPY_REPO, "commit": SPY_COMMIT, "path": SPY_PATH,
        "git_blob_sha1": SPY_GIT_BLOB_SHA1, "sha256": hashlib.sha256(payload).hexdigest(),
        "rows": int(len(df)),
    }


def fetch_hf_histories(symbols: list[str], output: Path, batch_size: int = 80):
    del batch_size
    cache = output / "hf_daily_filtered.csv.gz"
    aliases = {}
    requested = set()
    for source in symbols:
        source = str(source).strip().upper()
        candidates = [source]
        if "." in source:
            candidates.append(source.replace(".", "-"))
        aliases[source] = list(dict.fromkeys(candidates))
        requested.update(candidates)

    file_meta = []
    if cache.exists():
        data = pd.read_csv(cache, parse_dates=["date"])
    else:
        paths = []
        for filename in HF_FILES:
            path = hf_hub_download(
                repo_id=HF_REPO, repo_type="dataset", revision=HF_REVISION,
                filename=filename,
            )
            paths.append(path)
            stat = Path(path).stat()
            file_meta.append({"filename": filename, "bytes": stat.st_size})
            print(f"Downloaded pinned bulk shard {filename}: {stat.st_size:,} bytes", flush=True)

        dataset = pads.dataset(paths, format="parquet")
        fields = set(dataset.schema.names)
        required = {"symbol", "date", "open", "close"}
        if not required.issubset(fields):
            raise ValueError(f"Bulk price schema missing {sorted(required-fields)}")

        expression = (
            pads.field("symbol").isin(sorted(requested))
            & (pads.field("date") >= START)
            & (pads.field("date") <= END)
        )
        table = dataset.to_table(columns=["symbol", "date", "open", "close"], filter=expression)
        data = table.to_pandas()
        data["symbol"] = data["symbol"].astype(str).str.upper()
        data["date"] = pd.to_datetime(data["date"]).dt.tz_localize(None)
        data["open"] = pd.to_numeric(data["open"], errors="coerce")
        data["close"] = pd.to_numeric(data["close"], errors="coerce")
        data = data.dropna(subset=["symbol", "date", "open", "close"])
        data = data[(data["open"] > 0) & (data["close"] > 0)]
        data = data.drop_duplicates(["symbol", "date"], keep="last").sort_values(["symbol", "date"])
        data.to_csv(cache, index=False, compression="gzip")
        print(f"Filtered bulk snapshot to {len(data):,} daily rows for requested aliases", flush=True)

    by_alias = {
        sym: g[["date", "open", "close"]].sort_values("date").reset_index(drop=True)
        for sym, g in data.groupby("symbol", sort=False)
    }
    histories = {}
    alias_used = {}
    for source, candidates in aliases.items():
        for alias in candidates:
            if alias in by_alias:
                histories[source] = by_alias[alias]
                alias_used[source] = alias
                break

    spy, spy_meta = fetch_spy()
    histories[base.BENCHMARK] = spy

    alias_rows = [
        {"source_symbol": source, "candidate_aliases": "|".join(candidates),
         "alias_used": alias_used.get(source, ""), "history_found": source in histories}
        for source, candidates in sorted(aliases.items())
    ]
    pd.DataFrame(alias_rows).to_csv(output / "bulk_symbol_aliases.csv", index=False)
    manifest = {
        "provider": "Hugging Face bulk snapshot plus pinned public SPY CSV",
        "stocks_repo": HF_REPO, "stocks_revision": HF_REVISION, "stock_files": HF_FILES,
        "downloaded_file_meta": file_meta, "date_filter": [START, END],
        "requested_source_symbols": len(symbols), "requested_aliases": len(requested),
        "returned_source_symbols": len(histories) - 1,
        "missing_source_symbols": len(symbols) - (len(histories) - 1),
        "SPY": spy_meta,
        "research_only": True,
        "canonical_G2_credit": 0,
    }
    (output / "bulk_market_source_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return histories, {
        "cache_used": cache.exists(),
        "requested_symbols": len(symbols),
        "returned_symbols": len(histories) - 1,
        "benchmark_found": True,
        "failure_count": len(symbols) - (len(histories) - 1),
        "source": manifest["provider"],
        "stocks_revision": HF_REVISION,
        "spy_commit": SPY_COMMIT,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prep", type=Path, default=Path("data/processed/hacked_earnings_deep"))
    p.add_argument("--cache", type=Path, default=Path("private_runtime/hacked_earnings_source"))
    p.add_argument("--announcement-resolutions", type=Path, default=Path("data/processed/authorized_input_real/announcement_resolutions.csv"))
    p.add_argument("--output", type=Path, default=Path("data/processed/hacked_earnings_oos_hf"))
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    if args.self_test:
        base.self_test()
        spy, meta = fetch_spy()
        assert len(spy) > 1000 and spy["date"].min().date().isoformat() == "2010-01-04"
        print("HF wrapper self-test: PASS", meta)
        return
    base.fetch_yahoo_histories = fetch_hf_histories
    base.MARKET_SOURCE = (
        f"Hugging Face {HF_REPO}@{HF_REVISION} daily OHLC; "
        f"SPY benchmark {SPY_REPO}@{SPY_COMMIT}/{SPY_PATH}"
    )
    result = base.run(args)
    summary_path = args.output / "summary.json"
    summary = json.loads(summary_path.read_text())
    summary["market_data_source"] = base.MARKET_SOURCE
    summary["outcome_definition"] = (
        "next trading session open-to-close raw stock return minus pinned SPY "
        "open-to-close return; session strictly after text/source date"
    )
    summary["limitations"] = [
        x for x in summary["limitations"]
        if not x.startswith("Yahoo Finance daily bars")
    ]
    summary["limitations"].insert(
        0,
        "Bulk public daily prices are exploratory external evidence, not canonical G2; "
        "the source dataset itself reports limited delisted-company coverage."
    )
    summary_path.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    print(json.dumps(summary, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
