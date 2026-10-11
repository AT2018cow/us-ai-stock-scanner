"""Read-only cross-sectional liquidity attrition audit for immutable MVP evidence."""

import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path


RANGES = (
    ("under_250k", 0, 250_000),
    ("250k_500k", 250_000, 500_000),
    ("500k_1m", 500_000, 1_000_000),
    ("1m_1_5m", 1_000_000, 1_500_000),
    ("1_5m_1_8m", 1_500_000, 1_800_000),
    ("1_8m_2m", 1_800_000, 2_000_000),
)


def _jsonl(path):
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def audit_frozen_evidence(directory):
    root = Path(directory)
    manifest = json.loads((root / "run_manifest.json").read_text(encoding="utf-8"))
    contract = manifest.get("candidate_universe")
    if not isinstance(contract, dict):
        raise ValueError("candidate_universe contract required")
    membership = defaultdict(set)
    with (root / "ai_watchlist.csv").open(newline="", encoding="utf-8") as source:
        for item in csv.DictReader(source):
            if str(item.get("enabled", "1")).lower() in ("0", "false"):
                continue
            symbol = str(item.get("symbol") or "").strip().upper()
            bucket = str(item.get("bucket") or "").strip()
            if symbol and bucket:
                membership[symbol].add(bucket)

    excluded = _jsonl(root / "universe_exclusions.jsonl")
    decisions = _jsonl(root / "decisions.jsonl")
    xs = [str(x["symbol"]) for x in excluded]
    ds = [str(x["symbol"]) for x in decisions]
    if len(xs) != len(set(xs)) or len(ds) != len(set(ds)):
        raise ValueError("duplicate symbols")
    if set(xs) & set(ds):
        raise ValueError("decision and exclusion overlap")
    if set(membership) != set(xs) | set(ds):
        raise ValueError("universe conservation failed")
    if (len(membership), len(ds), len(xs)) != (
        contract["discovery_unique_symbols"],
        contract["decision_universe_symbols"],
        contract["excluded_symbols"],
    ):
        raise ValueError("manifest count mismatch")
    reasons = Counter(str(r["reason_code"]) for r in excluded)
    if dict(reasons) != contract["exclusion_reason_counts"]:
        raise ValueError("manifest reason counts mismatch")

    rates = {}
    for bucket in sorted({b for members in membership.values() for b in members}):
        members = {sym for sym, buckets in membership.items() if bucket in buckets}
        misses = [r for r in excluded if r["symbol"] in members]
        below = sum(r["reason_code"] == "DOLLAR_VOLUME_BELOW_MIN" for r in misses)
        rates[bucket] = {
            "discovered": len(members),
            "excluded": len(misses),
            "below_min": below,
            "excluded_rate": round(len(misses) / len(members), 6),
            "below_min_rate": round(below / len(members), 6),
        }

    volume = [r for r in excluded if r["reason_code"] == "DOLLAR_VOLUME_BELOW_MIN"]
    for row in volume:
        v = float(row["dollar_volume"])
        if v < 0 or not v < float(contract["min_dollar_volume"]):
            raise ValueError("invalid dollar-volume rejection: " + row["symbol"])
        if row["market_data_feed"] != contract["market_data_feed"]:
            raise ValueError("market-data feed mismatch: " + row["symbol"])
    histogram = {
        label: sum(low <= float(r["dollar_volume"]) < high for r in volume)
        for label, low, high in RANGES
    }
    return {
        "scope": "single_session_attrition_not_performance_or_optimal_threshold",
        "decision_date": manifest["decision_date"],
        "scanner_sha": manifest["code_sha"],
        "market_data_feed": contract["market_data_feed"],
        "min_dollar_volume": contract["min_dollar_volume"],
        "discovery": len(membership),
        "decisions": len(ds),
        "excluded": len(xs),
        "reason_counts": dict(sorted(reasons.items())),
        "bucket_rates": rates,
        "volume_histogram": histogram,
        "limitations": [
            "Multi-label discovery buckets overlap; they are not business sectors.",
            "IEX daily dollar volume is not consolidated liquidity.",
            "No 20-day comparable liquidity observations for excluded names here.",
            "No decisions or forward outcomes for excluded names; not an alpha test.",
        ],
    }


def render_markdown(result):
    out = [
        "# Liquidity gate: frozen cross-sectional audit",
        "",
        "This is not a return study or production-policy recommendation.",
        "",
        "Decision date: " + result["decision_date"],
        "Scanner SHA: " + result["scanner_sha"],
        "Market-data feed: " + result["market_data_feed"],
        "",
        "| Discovery bucket | Discovered | Excluded | Dollar-volume rejected | Rejected rate |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for bucket, item in result["bucket_rates"].items():
        out.append(
            "| {} | {} | {} | {} | {:.1%} |".format(
                bucket, item["discovered"], item["excluded"],
                item["below_min"], item["below_min_rate"]
            )
        )
    out += ["", "## Limitations", ""]
    out.extend("- " + item for item in result["limitations"])
    return "\n".join(out) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence_directory", type=Path)
    parser.add_argument("--format", choices=["json", "markdown"], default="markdown")
    args = parser.parse_args()
    summary = audit_frozen_evidence(args.evidence_directory)
    if args.format == "json":
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_markdown(summary), end="")


if __name__ == "__main__":
    main()
