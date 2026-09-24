import argparse
import pandas as pd
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description="Analyze a scanner output directory")
    parser.add_argument("--scan", type=str, default=None, help="Path to *_full_ranked.csv")
    parser.add_argument("--candidates", type=str, default="outputs/all_candidates_metrics.csv", help="Path to all_candidates_metrics.csv")
    parser.add_argument("--report", type=str, default=None, help="Optional Markdown report output path")
    return parser.parse_args()


def extract_timestamp(ranked_path: Path) -> str:
    stem = ranked_path.stem  # e.g. ai_value_scan_20260810T182029Z_full_ranked
    prefix = "ai_value_scan_"
    suffix = "_full_ranked"
    if stem.startswith(prefix) and stem.endswith(suffix):
        return stem[len(prefix):-len(suffix)]
    # fallback: try first token after prefix
    raise ValueError(f"Cannot parse timestamp from {ranked_path.name}")


def fmt_low_value(ranked: pd.DataFrame):
    df = ranked.copy()
    if df.empty:
        return pd.DataFrame()
    out = []
    for _, r in df.iterrows():
        out.append({
            "symbol": r["symbol"],
            "name": r["name"],
            "channel": r["channel"],
            "triage": r.get("triage_label", r.get("triage", "")),
            "priority": r.get("research_priority", r.get("priority", "")),
            "score": round(r["composite_score"], 3),
            "ai_link": round(r["ai_link_score"], 3),
            "ps_disc": round(r["ps_discount"], 3),
            "pe_disc": round(r["pe_discount"], 3),
            "drawdown": round(r["drawdown_from_52w_high"], 3),
            "pe": round(r["pe"], 1),
            "ps": round(r["ps"], 2),
            "fcf_yield": round(r["fcf_yield"], 3),
        })
    return pd.DataFrame(out)


def fmt_research(rp: pd.DataFrame):
    if rp.empty:
        return pd.DataFrame()
    out = []
    for _, r in rp.iterrows():
        out.append({
            "priority": r["research_priority"],
            "symbol": r["symbol"],
            "name": r["name"],
            "channel": r["channel"],
            "score": round(r["research_score"], 1),
            "ai_link": round(r["ai_link_score"], 3),
            "price": round(r["price"], 2),
            "drawdown": round(r["drawdown_from_52w_high"], 3),
            "r20": round(r["return_20d"], 3),
            "pe": round(r["pe"], 1),
            "ps": round(r["ps"], 2),
            "fcf_yield": round(r["fcf_yield"], 3),
            "risks": r["research_risks"],
        })
    return pd.DataFrame(out)


def main():
    args = parse_args()
    base = Path("outputs")

    if args.scan:
        ranked_path = Path(args.scan)
    else:
        # pick latest
        files = sorted(base.glob("ai_value_scan_*_full_ranked.csv"))
        if not files:
            raise FileNotFoundError("No scan output found in outputs/")
        ranked_path = files[-1]

    timestamp = extract_timestamp(ranked_path)
    rp_path = ranked_path.with_name(f"ai_value_scan_{timestamp}_full_ranked_research_pool.csv")
    candidates_path = Path(args.candidates)

    ranked = pd.read_csv(ranked_path)
    rp = pd.read_csv(rp_path)
    allc = pd.read_csv(candidates_path)

    lv = fmt_low_value(ranked)
    research = fmt_research(rp)

    highs = allc[allc["range_position_52w"] >= 0.95].copy()
    fcf_neg = allc[allc["free_cash_flow"] < 0].copy()
    inter = allc[(allc["range_position_52w"] >= 0.95) & (allc["free_cash_flow"] < 0)].copy()

    sections = []
    sections.append(f"# Scan Analysis Report ({timestamp})")
    sections.append("")

    sections.append("## Low-Value Shortlist")
    if lv.empty:
        sections.append("_No Low-Value candidates passed filters._")
    else:
        sections.append(lv.to_markdown(index=False))
    sections.append("")

    sections.append("## Research Pool")
    if research.empty:
        sections.append("_No research pool candidates._")
    else:
        sections.append(research.to_markdown(index=False))
    sections.append("")

    sections.append(f"- 52-week highs: {len(highs)}")
    sections.append(f"- FCF negative: {len(fcf_neg)}")
    sections.append(f"- High + FCF negative: {len(inter)}")
    sections.append("")

    cols = ["symbol", "name", "sic_description", "range_position_52w",
            "drawdown_from_52w_high", "return_20d", "return_60d", "pe", "ps",
            "fcf_yield", "free_cash_flow", "net_income", "fundamental_quality_score"]

    sections.append("## 52-Week Highs (top 30 by range_position_52w)")
    if highs.empty:
        sections.append("_No 52-week highs._")
    else:
        sections.append(highs[cols].sort_values("range_position_52w", ascending=False).head(30).to_markdown(index=False))
    sections.append("")

    sections.append("## Intersection High + FCF Negative")
    if inter.empty:
        sections.append("_No high+FCF-negative intersection._")
    else:
        sections.append(inter[cols].sort_values("range_position_52w", ascending=False).to_markdown(index=False))
    sections.append("")

    sections.append("## Semiconductor 52-week highs")
    semi = highs[highs["sic_description"].str.contains("Semiconductor|Storage", case=False, na=False)]
    if semi.empty:
        sections.append("_No semiconductor/storage 52-week highs._")
    else:
        semi_cols = ["symbol", "name", "range_position_52w", "drawdown_from_52w_high",
                     "return_20d", "return_60d", "pe", "fcf_yield"]
        sections.append(semi[semi_cols].sort_values("range_position_52w", ascending=False).to_markdown(index=False))

    report_text = "\n".join(sections)
    print(report_text)

    if args.report:
        Path(args.report).write_text(report_text, encoding="utf-8")
        print(f"\nReport written to {args.report}", file=__import__("sys").stderr)


if __name__ == "__main__":
    main()
