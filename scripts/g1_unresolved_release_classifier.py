from __future__ import annotations

import csv
import hashlib
import json
import re
import zipfile
from pathlib import Path

SOURCE_COMMIT = "c23c7d79d067a79d70cf20e31b072d3703497eae"
EXPECTED_BLOBS = {
    "2011.zip": "8f4b9b391e8e87649d2a5f5615a30371741c5e6a",
    "2012.zip": "afa44be02ab5aaea6e6105cbca247286bc892fd7",
    "2013.zip": "59e183f05e377ebd0ef2f581ba88522863663972",
    "2014.zip": "0e0e349b76318bb9558a790000c9cbe5ee933001",
    "2015.zip": "919ba9f271abdc06ba7c539ad278d5bb4fcb3715",
}
WIRE_MARKERS = [
    ("business_wire", ("business wire",)),
    ("pr_newswire", ("pr newswire", "prnewswire")),
    ("globenewswire", ("globenewswire", "globe newswire", "prime newswire")),
    ("marketwired", ("marketwired", "market wire")),
    ("accesswire", ("accesswire",)),
    ("canada_news_wire", ("canada newswire", "cnw group")),
    ("newsfile", ("newsfile",)),
]
TIME_RE = re.compile(
    r"""(?ix)
    \b(
      (?:(?:1[0-2]|0?[1-9])(?::[0-5]\d)?\s*(?:a\.?m\.?|p\.?m\.?))
      |
      (?:(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?)
    )
    \s*
    (
      eastern(?:\s+(?:daylight|standard))?\s+time|
      central(?:\s+(?:daylight|standard))?\s+time|
      mountain(?:\s+(?:daylight|standard))?\s+time|
      pacific(?:\s+(?:daylight|standard))?\s+time|
      e(?:s|d)?t|c(?:s|d)?t|m(?:s|d)?t|p(?:s|d)?t|utc|gmt
    )\b
    """
)
BARE_ET_RE = re.compile(
    r"""(?ix)\b((?:1[0-2]|0?[1-9])(?::[0-5]\d)?\s*(?:a\.?m\.?|p\.?m\.?))\s+(ET|CT|MT|PT)\b"""
)


def git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def clean_context(text: str, start: int, end: int, radius: int = 170) -> str:
    lo = max(0, start - radius)
    hi = min(len(text), end + radius)
    return re.sub(r"\s+", " ", text[lo:hi]).strip()[:420]


def load_unresolved(exclusions_path: Path) -> set[str]:
    data = json.loads(exclusions_path.read_text(encoding="utf-8"))
    return {row["event_id"] for row in data["exclusions"]}


def load_index(index_path: Path, unresolved: set[str]) -> list[dict]:
    with index_path.open(newline="", encoding="utf-8") as fh:
        return [row for row in csv.DictReader(fh) if row["event_id"] in unresolved]


def member_text(archive: zipfile.ZipFile, requested: str) -> str:
    names = archive.namelist()
    candidates = [requested, requested.split("/", 1)[-1]]
    basename = Path(requested).name
    candidates.extend(name for name in names if Path(name).name == basename)
    for name in candidates:
        try:
            raw = archive.read(name)
            return raw.decode("utf-8", errors="replace")
        except KeyError:
            pass
    raise KeyError(f"member not found: {requested}")


def classify_text(text: str) -> tuple[list[str], list[dict], str]:
    lower = text.lower()
    wires = [name for name, needles in WIRE_MARKERS if any(n in lower for n in needles)]
    hits: list[dict] = []
    seen = set()
    for regex in (TIME_RE, BARE_ET_RE):
        for match in regex.finditer(text):
            raw = re.sub(r"\s+", " ", match.group(0)).strip()
            key = raw.lower()
            if key in seen:
                continue
            seen.add(key)
            hits.append({"text": raw, "context": clean_context(text, match.start(), match.end())})
            if len(hits) >= 20:
                break
        if len(hits) >= 20:
            break
    prefix = re.sub(r"\s+", " ", text[:900]).strip()[:700]
    return wires, hits, prefix


def main() -> None:
    root = Path.cwd()
    zip_dir = Path("/tmp/he/Data/Press releases")
    out_dir = root / "private_runtime/audit/g1-unresolved-release-classifier"
    out_dir.mkdir(parents=True, exist_ok=True)

    for name, expected in EXPECTED_BLOBS.items():
        path = zip_dir / name
        if not path.is_file():
            raise SystemExit(f"missing archive {path}")
        actual = git_blob_sha(path)
        if actual != expected:
            raise SystemExit(f"{name} blob mismatch {actual} != {expected}")

    unresolved = load_unresolved(root / "data/processed/authorized_input_real/g1_final_timing_exclusions.json")
    rows = load_index(root / "data/processed/hacked_earnings_jfe/event_press_release_index.csv", unresolved)

    archives: dict[str, zipfile.ZipFile] = {}
    output: list[dict] = []
    for row in rows:
        paths = [p for p in row["release_member_paths"].split(";") if p]
        item = {
            "event_id": row["event_id"],
            "symbol": row["historical_symbol"],
            "first_trade": row["first_documented_illicit_trade_ts"],
            "matched_earnings_date": row["matched_earnings_date"],
            "release_match_count": int(row["release_match_count"]),
            "members": paths,
            "wire_markers": [],
            "time_hits": [],
            "prefix": "",
        }
        if len(paths) == 1:
            member = paths[0]
            year = member[:4]
            zname = f"{year}.zip"
            archive = archives.setdefault(zname, zipfile.ZipFile(zip_dir / zname))
            text = member_text(archive, member)
            wires, hits, prefix = classify_text(text)
            item["wire_markers"] = wires
            item["time_hits"] = hits
            item["prefix"] = prefix
        output.append(item)

    for archive in archives.values():
        archive.close()

    payload = {
        "schema_version": "1",
        "research_use_only": True,
        "source_repository": "vgreg/hacked_earnings_jfe",
        "source_commit": SOURCE_COMMIT,
        "unresolved_count": len(unresolved),
        "indexed_unresolved_count": len(rows),
        "with_release_member": sum(x["release_match_count"] == 1 for x in output),
        "with_wire_marker": sum(bool(x["wire_markers"]) for x in output),
        "with_explicit_time_hit": sum(bool(x["time_hits"]) for x in output),
        "items": output,
        "warning": "Time strings are research clues only. Calls, schedules, filing times and other non-publication clocks must be rejected unless independently proven to be the first-public release timestamp.",
    }
    (out_dir / "classification.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    fields = ["event_id","symbol","matched_earnings_date","release_match_count","wire_markers","time_hit_count","first_time_hit","members"]
    with (out_dir / "classification.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for item in output:
            writer.writerow({
                "event_id": item["event_id"],
                "symbol": item["symbol"],
                "matched_earnings_date": item["matched_earnings_date"],
                "release_match_count": item["release_match_count"],
                "wire_markers": ";".join(item["wire_markers"]),
                "time_hit_count": len(item["time_hits"]),
                "first_time_hit": item["time_hits"][0]["text"] if item["time_hits"] else "",
                "members": ";".join(item["members"]),
            })

    print(json.dumps({k: payload[k] for k in ("unresolved_count","indexed_unresolved_count","with_release_member","with_wire_marker","with_explicit_time_hit")}, indent=2))
    print("G1_UNRESOLVED_TIME_HITS")
    for item in output:
        if item["time_hits"] or item["wire_markers"]:
            print(json.dumps({
                "event_id": item["event_id"],
                "symbol": item["symbol"],
                "wire_markers": item["wire_markers"],
                "time_hits": item["time_hits"][:6],
                "prefix": item["prefix"][:280],
            }, ensure_ascii=False))


if __name__ == "__main__":
    main()
