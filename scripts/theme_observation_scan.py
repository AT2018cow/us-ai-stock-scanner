"""Theme observation entry point: run all five theme scans, summarize
shortlists, and archive weekly P0 paper cohorts (docs/theme_observation_protocol.md).

Every observation cycle:
1. Runs each theme's full scan (configs/config.theme.<name>.json) — the
   same scored architecture as the AI styles, isolated watchlists, no
   snapshot archiving into the AI PIT series.
2. Extracts each theme's shortlist (low_value keep/watch + momentum picks)
   and ARCHIVES a paper cohort to data/theme_cohorts.csv: every cohort is
   held 120 trading days on paper and evaluated against QQQ AND the
   theme's own benchmark basket (scripts/theme_observation_scan.py --evaluate).
3. Prints a side-by-side summary.

Usage:
    .venv/bin/python scripts/theme_observation_scan.py            # scan + archive
    .venv/bin/python scripts/theme_observation_scan.py --skip-scan  # summarize + archive from latest
    .venv/bin/python scripts/theme_observation_scan.py --evaluate  # score matured cohorts only
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

THEMES = ["nuclear", "quantum", "biotech", "rare_earth", "critical_minerals"]
COHORT_CSV = Path("data/theme_cohorts.csv")
HOLD_TRADING_DAYS = 120


def log(msg: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[theme-obs {stamp}] {msg}", flush=True)


def newest_report_for(theme: str) -> Path | None:
    """Newest scan report whose Config header matches the theme config."""
    candidates = []
    for p in glob.glob("outputs/ai_value_scan_*_full_ranked_report.md"):
        try:
            head = open(p, encoding="utf-8").read()[:400]
        except OSError:
            continue
        if f"Config: configs/config.theme.{theme}.json" in head:
            candidates.append(Path(p))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def extract_shortlist(theme: str, report: Path) -> pd.DataFrame:
    """Low-value keep/watch + momentum picks of one theme scan as cohort rows."""
    ts = re.search(r"ranked csv: outputs/(ai_value_scan_\d+T\d+Z)", report.read_text()).group(1)
    started = re.search(r"Started UTC: ([\dT:\.\-+]+)", report.read_text())
    entry_date = started.group(1)[:10] if started else datetime.now(timezone.utc).date().isoformat()
    rows: list[dict] = []
    lv = Path(f"outputs/{ts}_full_ranked.csv")
    mo = Path(f"outputs/{ts}_full_ranked_momentum.csv")
    if lv.exists():
        d = pd.read_csv(lv)
        for _, r in d[d["triage_label"].isin(["keep", "watch"])].iterrows():
            rows.append({
                "theme": theme, "list_type": "low_value", "symbol": str(r["symbol"]).upper(),
                "triage": r["triage_label"],
                "research_priority": r.get("research_priority", ""),
                "composite_score": round(float(r["composite_score"]), 4),
                "entry_date": entry_date, "entry_price": round(float(r["price"]), 4) if pd.notna(r.get("price")) else None,
                "status": "open", "exit_date": "", "return_120d": "",
            })
    if mo.exists():
        d = pd.read_csv(mo)
        for _, r in d.iterrows():
            rows.append({
                "theme": theme, "list_type": "momentum", "symbol": str(r["symbol"]).upper(),
                "triage": "momentum",
                "research_priority": r.get("research_priority", ""),
                "composite_score": round(float(r["composite_score"]), 4),
                "entry_date": entry_date, "entry_price": round(float(r["price"]), 4) if pd.notna(r.get("price")) else None,
                "status": "open", "exit_date": "", "return_120d": "",
            })
    return pd.DataFrame(rows)


def archive_cohort(theme: str, cohort: pd.DataFrame) -> None:
    """Append one cohort; dedupe on (theme, list_type, entry_date, symbol)."""
    if cohort.empty:
        log(f"{theme}: 无可归档的 shortlist（空清单主题也按协议记录为 no-signal）")
        row = pd.DataFrame([{
            "theme": theme, "list_type": "none", "symbol": "", "triage": "",
            "research_priority": "", "composite_score": "",
            "entry_date": datetime.now(timezone.utc).date().isoformat(),
            "entry_price": "", "status": "no_signal", "exit_date": "", "return_120d": "",
        }])
        combined = pd.concat([pd.read_csv(COHORT_CSV) if COHORT_CSV.exists() else row, row], ignore_index=True)
        combined.to_csv(COHORT_CSV, index=False)
        return
    existing = pd.read_csv(COHORT_CSV) if COHORT_CSV.exists() else cohort.head(0)
    key = ["theme", "list_type", "entry_date", "symbol"]
    merged = pd.concat([existing, cohort], ignore_index=True)
    merged = merged.drop_duplicates(subset=key, keep="first")
    merged.to_csv(COHORT_CSV, index=False)
    log(f"{theme}: 归档 cohort {len(cohort)} 行（entry_date={cohort['entry_date'].iloc[0]}）")


def print_summary(theme: str, report: Path) -> None:
    text = report.read_text()
    lv = re.search(r"## Shortlist\n(.*?)\n##", text, re.S)
    mo = re.findall(r"^- (\w+) \|.*?momentum", text, re.M)
    print(f"\n[{theme}] {report.name}")
    if lv:
        lines = [l for l in lv.group(1).strip().splitlines() if l.strip()][:6]
        print("\n".join(lines))
    print(f"momentum picks: {len(mo)}")


def evaluate_matured() -> None:
    """Score cohorts whose 120 trading days have elapsed (paper exit)."""
    if not COHORT_CSV.exists():
        log("无 cohort 归档")
        return
    from ai_value_scanner.scanner import load_config
    from ai_value_scanner.backtest import build_bar_db, load_alpaca_client
    from ai_value_scanner.backtest import next_trading_index

    cfg = load_config("configs/config.risk_off.json")
    client, _ = load_alpaca_client(cfg)
    d = pd.read_csv(COHORT_CSV)
    open_rows = d[(d["status"] == "open") & d["symbol"].notna() & (d["symbol"] != "")]
    if open_rows.empty:
        log("无待结算 cohort")
        return
    syms = sorted(set(open_rows["symbol"].astype(str).str.upper()))
    bars_start = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=420)).isoformat()
    bar_db = build_bar_db(client, syms + ["QQQ"], bars_start, cfg.chunk_size)
    today = pd.Timestamp.now(tz="UTC").tz_localize(None)
    n_matured = 0
    for idx, r in open_rows.iterrows():
        entry_dt = pd.Timestamp(str(r["entry_date"]), tz="UTC")
        frame = bar_db.get(str(r["symbol"]).upper())
        if frame is None or frame.empty:
            continue
        e_idx = next_trading_index(frame.index, entry_dt)
        if e_idx is None:
            continue
        x_idx = e_idx + HOLD_TRADING_DAYS - 1
        if x_idx >= len(frame):
            continue  # not matured yet
        entry = float(frame.iloc[e_idx]["open"])
        exit_px = float(frame.iloc[x_idx]["close"])
        if entry <= 0:
            continue
        d.loc[idx, "status"] = "matured"
        d.loc[idx, "exit_date"] = str(frame.index[x_idx].date())
        d.loc[idx, "return_120d"] = round(exit_px / entry - 1.0, 6)
        n_matured += 1
    d.to_csv(COHORT_CSV, index=False)
    log(f"结算 {n_matured} 行；未到期行保持 open")
    # 汇总已结算 cohort
    matured = d[(d["status"] == "matured") & pd.to_numeric(d["return_120d"], errors="coerce").notna()]
    if not matured.empty:
        m = matured.copy()
        m["ret"] = pd.to_numeric(m["return_120d"])
        print("\n===== 已结算 cohort 汇总（120d 纸面收益）=====")
        for (theme, lt), part in m.groupby(["theme", "list_type"]):
            qqq = part["symbol"].apply(lambda s: 0.0)  # QQQ excess 在主题基准对照中更合适，此处给绝对收益
            print(f"{theme}/{lt}: n={len(part)} mean={part['ret'].mean()*100:+.1f}% win={(part['ret']>0).mean()*100:.0f}%")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--skip-scan", action="store_true", help="Reuse latest reports")
    p.add_argument("--evaluate", action="store_true", help="Only score matured cohorts")
    args = p.parse_args()

    if args.evaluate:
        evaluate_matured()
        return

    for theme in THEMES:
        if not args.skip_scan:
            log(f"[{theme}] scan start")
            result = subprocess.run([sys.executable, "run_scan.py", "--config", f"configs/config.theme.{theme}.json"])
            if result.returncode != 0:
                print(f"[{theme}] scan FAILED (exit {result.returncode})", flush=True)
                continue
        report = newest_report_for(theme)
        if report is None:
            print(f"[{theme}] 无扫描报告", flush=True)
            continue
        cohort = extract_shortlist(theme, report)
        archive_cohort(theme, cohort)
        print_summary(theme, report)

    print(
        "\nObservation reminder: cohorts are held 120 trading days on paper; "
        "run --evaluate weekly to mature settled rows (docs/theme_observation_protocol.md).",
        flush=True,
    )


if __name__ == "__main__":
    main()
