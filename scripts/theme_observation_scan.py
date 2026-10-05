"""Theme observation entry point: run all five theme scans, summarize
shortlists, and archive weekly P0 paper cohorts (docs/theme_observation_protocol.md).

Every observation cycle:
1. Runs each theme's full scan (configs/config.theme.<name>.json) — the
   same scored architecture as the AI styles, isolated watchlists, no
   snapshot archiving into the AI PIT series.
2. Extracts each theme's shortlist (low_value keep/watch + momentum picks).
   A scan is an observation by default. Only --archive-cohort freezes the
   observation into the weekly paper-cohort dataset.
3. Matured cohorts are held 120 trading days on paper and evaluated on
   absolute net return, excess vs QQQ, and excess vs the registered theme
   benchmark basket.
4. Prints a side-by-side summary.

Usage:
    .venv/bin/python scripts/theme_observation_scan.py              # scan observation only
    .venv/bin/python scripts/theme_observation_scan.py --archive-cohort  # scan + freeze weekly cohort
    .venv/bin/python scripts/theme_observation_scan.py --skip-scan --archive-cohort  # freeze latest
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
from typing import Any

import pandas as pd

from ai_value_scanner.scanner import write_csv_atomic

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

THEMES = ["nuclear", "quantum", "biotech", "rare_earth", "critical_minerals"]
COHORT_CSV = Path("data/theme_cohorts.csv")  # set per sleeve in main()
HOLD_TRADING_DAYS = 120
PAPER_TRADING_COST_BPS = 15.0
THEME_REGISTRY = Path("configs/theme_universe.json")


def log(msg: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[theme-obs {stamp}] {msg}", flush=True)


def newest_report_for(theme: str, prefix: str = "config.theme") -> Path | None:
    """Newest scan report whose Config header matches the config prefix."""
    candidates = []
    for p in glob.glob("outputs/ai_value_scan_*_full_ranked_report.md"):
        try:
            head = open(p, encoding="utf-8").read()[:400]
        except OSError:
            continue
        if f"Config: configs/{prefix}.{theme}.json" in head:
            candidates.append(Path(p))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def extract_shortlist(theme: str, report: Path, prefix: str = "config.theme") -> pd.DataFrame:
    """Low-value keep/watch + momentum picks of one theme scan as cohort rows."""
    text = report.read_text()
    ranked_m = re.search(r"ranked csv: outputs/(ai_value_scan_\d+T\d+Z)", text)
    if ranked_m is None:
        log(f"{theme}: 报告缺少 ranked csv 行，跳过归档（{report.name}）")
        return pd.DataFrame()
    ts = ranked_m.group(1)
    started = re.search(r"Started UTC: ([\dT:\.\-+]+)", text)
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


def _report_entry_date(report: Path | None) -> str:
    if report is not None:
        try:
            text = report.read_text()
        except OSError:
            text = ""
        started = re.search(r"Started UTC: ([\dT:.\-+]+)", text)
        if started:
            return started.group(1)[:10]
    return datetime.now(timezone.utc).date().isoformat()


def weekly_cohort_id(theme: str, entry_date: str) -> str:
    dt = pd.Timestamp(entry_date)
    iso = dt.isocalendar()
    return f"{theme}:{int(iso.year)}-W{int(iso.week):02d}"


def _backfill_cohort_identity(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if "cohort_id" not in out.columns:
        out["cohort_id"] = ""
    if "signal_utc" not in out.columns:
        out["signal_utc"] = ""
    if "source_report" not in out.columns:
        out["source_report"] = ""
    if "entry_date" in out.columns and "theme" in out.columns:
        missing = out["cohort_id"].fillna("").astype(str).eq("")
        for idx in out.index[missing]:
            entry = str(out.loc[idx, "entry_date"] or "")
            theme_name = str(out.loc[idx, "theme"] or "")
            if entry and theme_name and entry.lower() != "nan":
                try:
                    out.loc[idx, "cohort_id"] = weekly_cohort_id(theme_name, entry)
                except (ValueError, TypeError):
                    pass
    return out


def archive_cohort(
    theme: str,
    cohort: pd.DataFrame,
    cohort_csv: Path = COHORT_CSV,
    report: Path | None = None,
) -> None:
    """Freeze one weekly cohort; reruns in the same ISO week are idempotent."""
    entry_date = (
        str(cohort["entry_date"].iloc[0])
        if not cohort.empty and "entry_date" in cohort.columns
        else _report_entry_date(report)
    )
    cohort_id = weekly_cohort_id(theme, entry_date)
    report_name = report.name if report is not None else ""
    signal_utc = ""
    if report is not None:
        try:
            text = report.read_text()
        except OSError:
            text = ""
        started = re.search(r"Started UTC: ([\dT:.\-+]+)", text)
        if started:
            signal_utc = started.group(1)

    if cohort.empty:
        log(f"{theme}: 无可归档 shortlist；冻结 weekly no_signal cohort")
        incoming = pd.DataFrame(
            [
                {
                    "cohort_id": cohort_id,
                    "theme": theme,
                    "list_type": "none",
                    "symbol": "",
                    "triage": "",
                    "research_priority": "",
                    "composite_score": "",
                    "signal_utc": signal_utc,
                    "source_report": report_name,
                    "entry_date": entry_date,
                    "entry_price": "",
                    "status": "no_signal",
                    "exit_date": "",
                    "return_120d": "",
                }
            ]
        )
    else:
        incoming = cohort.copy()
        incoming["cohort_id"] = cohort_id
        incoming["signal_utc"] = signal_utc
        incoming["source_report"] = report_name

    existing = (
        _backfill_cohort_identity(pd.read_csv(cohort_csv))
        if cohort_csv.exists()
        else incoming.head(0)
    )
    incoming = _backfill_cohort_identity(incoming)
    for col in ("cohort_id", "list_type", "symbol"):
        if col in existing.columns:
            existing[col] = existing[col].fillna("")
        incoming[col] = incoming[col].fillna("")

    merged = pd.concat([existing, incoming], ignore_index=True, sort=False)
    merged = merged.drop_duplicates(
        subset=["cohort_id", "list_type", "symbol"],
        keep="first",
    )
    write_csv_atomic(merged, cohort_csv)
    log(
        f"{theme}: weekly cohort {cohort_id} frozen "
        f"({len(incoming)} rows, entry_date={entry_date})"
    )


def print_summary(theme: str, report: Path) -> None:
    text = report.read_text()
    lv = re.search(r"## Shortlist\n(.*?)\n##", text, re.S)
    mo = re.findall(r"^- (\w+) \|.*?momentum", text, re.M)
    print(f"\n[{theme}] {report.name}")
    if lv:
        lines = [l for l in lv.group(1).strip().splitlines() if l.strip()][:6]
        print("\n".join(lines))
    print(f"momentum picks: {len(mo)}")


def load_theme_benchmarks(registry_path: Path = THEME_REGISTRY) -> dict[str, list[str]]:
    raw = json.loads(registry_path.read_text())
    themes = raw.get("themes", {})
    out: dict[str, list[str]] = {}
    for theme, spec in themes.items():
        values = [
            str(x).upper().strip()
            for x in (spec.get("benchmark_etfs") or [])
            if str(x).strip()
        ]
        out[str(theme)] = list(dict.fromkeys(values))
    return out


def ensure_evaluation_columns(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    defaults: dict[str, Any] = {
        "return_120d_gross": "",
        "return_120d": "",
        "qqq_return_120d": "",
        "excess_vs_qqq_120d": "",
        "theme_benchmark_return_120d": "",
        "excess_vs_theme_benchmark_120d": "",
        "theme_benchmark_symbols": "",
        "evaluation_note": "",
    }
    for col, default in defaults.items():
        if col not in out.columns:
            out[col] = default
    return out


def _paper_forward_return(
    frame: pd.DataFrame | None,
    split_events: list[tuple[str, float]] | None,
    signal_date: str,
    *,
    roundtrip_cost: float,
) -> tuple[float | None, float | None, pd.Timestamp | None]:
    if frame is None or frame.empty:
        return None, None, None
    from ai_value_scanner.backtest import apply_split_adjustment_to_frame, forward_return_with_exit

    adjusted = apply_split_adjustment_to_frame(frame, split_events or [])
    net, exit_date = forward_return_with_exit(
        adjusted,
        signal_date,
        HOLD_TRADING_DAYS,
        roundtrip_cost,
        entry_price_mode="next_open",
        exit_price_mode="close",
    )
    if net is None:
        return None, None, exit_date
    gross = float(net) + roundtrip_cost
    return gross, float(net), exit_date


def evaluate_matured(cohort_csv: Path = COHORT_CSV) -> None:
    """Settle matured paper cohorts with absolute and benchmark-relative returns."""
    if not cohort_csv.exists():
        log("无 cohort 归档")
        return
    from ai_value_scanner.scanner import load_config
    from ai_value_scanner.backtest import build_bar_db, load_alpaca_client

    cfg = load_config("configs/config.risk_off.json")
    client, _ = load_alpaca_client(cfg)
    d = ensure_evaluation_columns(pd.read_csv(cohort_csv))
    open_rows = d[(d["status"] == "open") & d["symbol"].notna() & (d["symbol"] != "")]
    if open_rows.empty:
        log("无待结算 cohort")
        return

    theme_benchmarks = load_theme_benchmarks()
    syms = sorted(set(open_rows["symbol"].astype(str).str.upper()))
    benchmark_syms = sorted(
        {"QQQ"}
        | {
            sym
            for theme in open_rows["theme"].dropna().astype(str).unique()
            for sym in theme_benchmarks.get(theme, [])
        }
    )
    all_syms = sorted(set(syms) | set(benchmark_syms))
    bars_start = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=420)).isoformat()
    bar_db = build_bar_db(client, all_syms, bars_start, cfg.chunk_size)

    try:
        split_events = client.get_corporate_action_splits(all_syms, bars_start)
    except Exception as exc:
        split_events = {}
        log(f"拆股事件获取失败 ({exc.__class__.__name__})；按未调整价格结算")

    roundtrip_cost = (2.0 * PAPER_TRADING_COST_BPS) / 10000.0
    n_matured = 0
    n_unresolved = 0
    n_benchmark_degraded = 0

    for idx, r in open_rows.iterrows():
        symbol = str(r["symbol"]).upper()
        signal_date = str(r["entry_date"])
        gross, net, exit_date = _paper_forward_return(
            bar_db.get(symbol),
            split_events.get(symbol),
            signal_date,
            roundtrip_cost=roundtrip_cost,
        )
        if net is None or exit_date is None:
            # Preserve open for genuinely immature rows. If the nominal horizon
            # should already have matured but pricing is unavailable, mark it
            # separately so missing data cannot masquerade as "not matured".
            nominal_end = pd.Timestamp(signal_date, tz="UTC") + pd.Timedelta(days=190)
            if pd.Timestamp.now(tz="UTC") >= nominal_end:
                d.loc[idx, "status"] = "unresolved_price"
                d.loc[idx, "evaluation_note"] = "symbol forward window unavailable"
                n_unresolved += 1
            continue

        d.loc[idx, "status"] = "matured"
        d.loc[idx, "exit_date"] = exit_date.date().isoformat()
        d.loc[idx, "return_120d_gross"] = round(float(gross), 6)
        d.loc[idx, "return_120d"] = round(float(net), 6)

        _, qqq_net, qqq_exit = _paper_forward_return(
            bar_db.get("QQQ"),
            split_events.get("QQQ"),
            signal_date,
            roundtrip_cost=roundtrip_cost,
        )
        if qqq_net is not None and qqq_exit is not None:
            d.loc[idx, "qqq_return_120d"] = round(float(qqq_net), 6)
            d.loc[idx, "excess_vs_qqq_120d"] = round(float(net - qqq_net), 6)
        else:
            d.loc[idx, "evaluation_note"] = "QQQ benchmark unavailable"
            n_benchmark_degraded += 1

        basket = theme_benchmarks.get(str(r["theme"]), [])
        basket_returns: list[float] = []
        for bench in basket:
            _, bench_net, bench_exit = _paper_forward_return(
                bar_db.get(bench),
                split_events.get(bench),
                signal_date,
                roundtrip_cost=roundtrip_cost,
            )
            if bench_net is not None and bench_exit is not None:
                basket_returns.append(float(bench_net))
        d.loc[idx, "theme_benchmark_symbols"] = ",".join(basket)
        if basket_returns:
            basket_ret = float(pd.Series(basket_returns).median())
            d.loc[idx, "theme_benchmark_return_120d"] = round(basket_ret, 6)
            d.loc[idx, "excess_vs_theme_benchmark_120d"] = round(float(net - basket_ret), 6)
        else:
            note_raw = d.loc[idx, "evaluation_note"]
            note = "" if pd.isna(note_raw) else str(note_raw).strip()
            d.loc[idx, "evaluation_note"] = (
                (note + "; " if note else "") + "theme benchmark unavailable"
            )
            n_benchmark_degraded += 1
        n_matured += 1

    write_csv_atomic(d, cohort_csv)
    log(
        f"结算 {n_matured} 行；unresolved_price={n_unresolved}；"
        f"benchmark_degraded={n_benchmark_degraded}；成本={PAPER_TRADING_COST_BPS:.0f}bps/side"
    )

    matured = d[
        (d["status"] == "matured")
        & pd.to_numeric(d["return_120d"], errors="coerce").notna()
    ]
    if not matured.empty:
        m = matured.copy()
        for col in (
            "return_120d",
            "excess_vs_qqq_120d",
            "excess_vs_theme_benchmark_120d",
        ):
            m[col] = pd.to_numeric(m[col], errors="coerce")
        print("\n===== 已结算 cohort 汇总（120d paper）=====")
        for (theme, lt), part in m.groupby(["theme", "list_type"]):
            abs_mean = part["return_120d"].mean()
            qqq_mean = part["excess_vs_qqq_120d"].mean()
            theme_mean = part["excess_vs_theme_benchmark_120d"].mean()
            print(
                f"{theme}/{lt}: n={len(part)} "
                f"abs={abs_mean*100:+.1f}% "
                f"vsQQQ={qqq_mean*100:+.1f}% "
                f"vsTheme={theme_mean*100:+.1f}% "
                f"win={(part['return_120d']>0).mean()*100:.0f}%"
            )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--skip-scan", action="store_true", help="Reuse latest reports")
    p.add_argument("--evaluate", action="store_true", help="Only score matured cohorts")
    p.add_argument(
        "--archive-cohort",
        action="store_true",
        help="Freeze this observation into the weekly paper-cohort dataset.",
    )
    p.add_argument("--sleeve", choices=["theme", "venture"], default="theme",
                   help="theme = config.theme.* (five-theme P0); venture = config.venture.* (venture sleeve P0)")
    return p


def main() -> None:
    args = build_parser().parse_args()

    prefix = f"config.{args.sleeve}"
    cohort_csv = Path(f"data/{args.sleeve}_cohorts.csv")

    if args.evaluate:
        evaluate_matured(cohort_csv)
        return

    failed_themes: list[str] = []

    for theme in THEMES:
        if not args.skip_scan:
            log(f"[{theme}] scan start")
            result = subprocess.run([sys.executable, "run_scan.py", "--config", f"configs/{prefix}.{theme}.json"])
            if result.returncode != 0:
                print(f"[{theme}] scan FAILED (exit {result.returncode})", flush=True)
                failed_themes.append(theme)
                continue
        report = newest_report_for(theme, prefix)
        if report is None:
            print(f"[{theme}] 无扫描报告", flush=True)
            failed_themes.append(theme)
            continue
        cohort = extract_shortlist(theme, report, prefix)
        if args.archive_cohort:
            archive_cohort(theme, cohort, cohort_csv, report)
        else:
            log(f"{theme}: observation only（未传 --archive-cohort，不写 paper cohort）")
        print_summary(theme, report)

    print(
        "\nObservation reminder: scans may run daily, but paper cohorts are frozen explicitly "
        "with --archive-cohort (daily_run does this on Friday only); "
        "run --evaluate weekly to settle matured rows.",
        flush=True,
    )
    if failed_themes:
        print(
            "FAILED themes: " + ", ".join(sorted(set(failed_themes))) + "; returning non-zero status.",
            flush=True,
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
