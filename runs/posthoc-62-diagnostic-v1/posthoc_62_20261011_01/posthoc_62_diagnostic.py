"""Post-hoc 62-symbol cross-industry diagnostic (research-only, isolated).

Fixed cohort from the frozen generalized-v0 sources, evaluated as of
HISTORICAL dates with strictly point-in-time evidence (bars/filings at or
before each date; no forward data of any kind). Membership is labeled
``retrospective_posthoc_cohort`` — the 2026-10-11 roster is NOT valid PIT
membership for these dates and must never be presented as a historical
candidate pool or formal snapshot.

Guards (fail-closed, see tests/test_posthoc_62_guards.py):
  - output root must not be/inside outputs/decisions and must not mention
    "formal"; existing date dirs are never overwritten;
  - every target date must be a real QQQ trading session not later than the
    latest observed session (no future fabrication, no silent weekend drift);
  - no --formal flag exists on this entry by design.

Reuses the frozen v1 pipeline end to end (no reimplementation):
  universe audit -> PIT bars/fundamentals -> build_cross_section_asof ->
  build_stock_decisions -> render_action_list / render_detailed_report.
Quality v1, Entry v1, Action mapping, QQQ regime, IEX feed and the $2m
snapshot gate (informational here; pre-decision exclusion still reported)
are byte-identical to production. Only the universe (fixed post-hoc) and
the output root (isolated) differ.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ai_value_scanner.backtest import (
    benchmark_trailing_return_asof,
    benchmark_trend_ok_asof,
    build_bar_db,
    build_cross_section_asof,
    build_fundamental_pti_db,
    build_theme_scores_rules_proxy,
)
from ai_value_scanner.config import load_config
from ai_value_scanner.decision.integrated import (
    DEFAULT_ATTENTION_CAP,
    build_stock_decisions,
    decisions_by_symbol,
)
from ai_value_scanner.decision.model import (
    stock_decisions_to_jsonl,
)
from ai_value_scanner.evaluation.backtest import (
    fetch_split_events_or_raise,
    split_query_end_iso,
)
from ai_value_scanner.reporting.decision import (
    render_action_list,
    render_detailed_report,
)
from ai_value_scanner.scanner import (
    collect_candidates_with_universe_audit,
    load_runtime_settings,
)

SOURCE_TAGS = ("us_core", "thematic", "manual")
HORIZONS = (20, 60, 120)


def refuse_formal_like(out_dir: Path) -> None:
    token = out_dir.as_posix().lower()
    if "formal" in token:
        raise SystemExit("refusing formal-like output root for a post-hoc diagnostic")
    decisions = Path("outputs") / "decisions"
    try:
        out_dir.resolve().relative_to(decisions.resolve())
        raise SystemExit("refusing to write inside outputs/decisions")
    except ValueError:
        pass


def load_frozen_cohort(config: object) -> tuple[list[str], list[dict], dict[str, str]]:
    """Return (62 symbols, membership rows, {tag: sha256})."""
    files = (getattr(config, "discovery_source_files", None) or {})
    if not files:
        raise SystemExit("config has no discovery_source_files; refusing ad-hoc universe")
    symbols: list[str] = []
    rows: list[dict] = []
    hashes: dict[str, str] = {}
    for tag in SOURCE_TAGS:
        path = Path(str(files.get(tag, "")))
        if not path.is_file():
            raise SystemExit(f"frozen source missing: {tag} -> {path}")
        raw = path.read_bytes()
        hashes[tag] = hashlib.sha256(raw).hexdigest()
        with path.open(newline="", encoding="utf-8") as handle:
            for rec in csv.DictReader(handle):
                sym = str(rec.get("symbol") or rec.get("ticker") or "").strip().upper()
                if not sym or str(rec.get("enabled", "1")).strip() == "0":
                    continue
                symbols.append(sym)
                rows.append({"tag": tag, "symbol": sym,
                             "etfs": str(rec.get("etfs") or ""),
                             "bucket": str(rec.get("legacy_bucket") or tag)})
    uniq = sorted(set(symbols))
    if len(uniq) != 62:
        raise SystemExit(f"post-hoc cohort must be exactly the frozen 62, got {len(uniq)}")
    return uniq, rows, hashes


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", default="outputs/config.generalized_v0.experiment.json")
    p.add_argument("--dates", default="2026-09-30,2026-10-05,2026-10-09")
    p.add_argument("--out-dir", default="outputs/posthoc_62")
    p.add_argument("--attention-cap", type=int, default=DEFAULT_ATTENTION_CAP)
    return p


def main() -> None:
    args = build_parser().parse_args()
    out_root = Path(args.out_dir)
    refuse_formal_like(out_root)
    dates = sorted({d.strip() for d in str(args.dates).split(",") if d.strip()})
    for d in dates:
        if (out_root / d).exists():
            raise SystemExit(f"refusing to overwrite existing date dir: {out_root / d}")
    cap = max(1, int(args.attention_cap))
    code_sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
    config = load_config(args.config)
    if getattr(config, "max_symbols", None) is not None:
        raise SystemExit("diagnostic requires max_symbols=null (full 62-symbol cohort)")
    symbols, memberships, source_hashes = load_frozen_cohort(config)

    alpaca, sec, monitor = load_runtime_settings(config)
    start_iso = (pd.Timestamp(min(dates), tz="UTC") - pd.Timedelta(days=420)).date().isoformat()
    need = sorted(set(symbols + ["QQQ"] + list(config.ai_link_benchmark_etfs or [])))
    bar_db = build_bar_db(alpaca, need, start_iso, config.chunk_size)
    qqq = bar_db.get("QQQ")
    if qqq is None or qqq.empty:
        raise SystemExit("no QQQ bars: cannot anchor post-hoc sessions")
    sessions = set(qqq.index.date.astype(str))
    for d in dates:
        if d not in sessions:
            raise SystemExit(f"{d} is not an observed QQQ session: refusing silent asof drift")
        if d > max(sessions):
            raise SystemExit(f"{d} is in the future relative to cached bars")
    split_end = split_query_end_iso(max(dates), HORIZONS)
    splits = fetch_split_events_or_raise(alpaca, need, start_iso, split_end)

    uni_df, uni_exclusions, _ = collect_candidates_with_universe_audit(
        alpaca, sec, config, symbol_allowlist=set(symbols))
    if "cik" not in uni_df.columns:
        raise SystemExit("universe audit returned no CIK mapping")
    have = set(uni_df["symbol"].astype(str).str.upper())
    missing_map = sorted(set(symbols) - have)
    universe = uni_df[uni_df["symbol"].astype(str).str.upper().isin(set(symbols))].copy()
    fundamentals = build_fundamental_pti_db(universe, sec, int(config.max_workers or 8))
    themes = build_theme_scores_rules_proxy(universe, fundamentals, config)
    by_sym: dict[str, list[dict]] = {}
    for m in memberships:
        by_sym.setdefault(m["symbol"], []).append(m)
    watchlist_by_symbol = {
        s: ("posthoc:" + "+".join(sorted({m["tag"] for m in ms})),
            len(ms), ";".join(sorted({m["etfs"] for m in ms if m["etfs"]})) or "-")
        for s, ms in by_sym.items()
    }

    previous_by_symbol: dict = {}
    summaries: list[dict] = []
    for d in dates:
        asof = pd.Timestamp(d, tz="UTC")
        b60 = benchmark_trailing_return_asof(bar_db, "QQQ", asof, 60, splits.get("QQQ"))
        regime = "unknown" if b60 is None else ("up" if b60 >= 0 else "down")
        trend_ok = benchmark_trend_ok_asof(
            bar_db, str(config.benchmark_trend_filter_symbol or "QQQ"), asof,
            int(config.benchmark_trend_filter_sma_days or 200),
            splits.get(str(config.benchmark_trend_filter_symbol or "QQQ")))
        med20, med60 = [], []
        for etf in (config.ai_link_benchmark_etfs or []):
            fb = bar_db.get(str(etf))
            if fb is None or fb.empty:
                continue
            from ai_value_scanner.backtest import compute_price_features_asof
            feat = compute_price_features_asof(fb, asof=asof,
                                               lookback_days=int(config.price_lookback_days or 420),
                                               split_events=splits.get(str(etf)))
            if not feat:
                continue
            if feat.get("return_20d") is not None:
                med20.append(float(feat["return_20d"]))
            if feat.get("return_60d") is not None:
                med60.append(float(feat["return_60d"]))
        df = build_cross_section_asof(
            asof=asof, universe=universe, bar_db=bar_db, fundamentals=fundamentals,
            theme_scores=themes, watchlist_by_symbol=watchlist_by_symbol,
            benchmark_return_20d=float(pd.Series(med20).median()) if med20 else None,
            benchmark_return_60d=float(pd.Series(med60).median()) if med60 else None,
            disclosure_lookback_days=720, scan_config=config,
            qqq_return_60d=b60, benchmark_trend_ok=trend_ok, split_events=splits)
        df["regime"] = regime
        decisions = build_stock_decisions(
            df, decision_date=d, generated_at_utc=datetime.now(timezone.utc).isoformat(),
            previous_by_symbol=previous_by_symbol or None,
            run_provenance={"code_sha": code_sha, "mode": "retrospective_posthoc_cohort",
                            "cohort": "generalized_v0_62frozen",
                            "membership_asof": "2026-10-11 (NOT PIT for these dates)"})
        day_root = out_root / d
        (day_root / "detailed").mkdir(parents=True)
        (day_root / "decisions.jsonl").write_text(
            stock_decisions_to_jsonl(decisions), encoding="utf-8")
        ordered = sorted(decisions,
                         key=lambda x: ({"PRIORITY_REVIEW": 0, "WATCH_PULLBACK": 1,
                                         "WATCH_BREAKOUT": 2, "HOLD_MONITOR": 3,
                                         "AVOID": 4}[x.action_state.value],
                                        {"A": 0, "B": 1, "C": 2, "UNRATED": 3}[x.quality.grade.value],
                                        x.symbol))
        (day_root / "action_list.md").write_text(
            render_action_list(ordered[:cap], title=f"Action List — post-hoc {d}",
                               cadence="Daily (post-hoc)"), encoding="utf-8")
        for dec in decisions:
            (day_root / "detailed" / f"{dec.symbol}.md").write_text(
                render_detailed_report(dec), encoding="utf-8")
        excl = list(uni_exclusions)
        for s in missing_map:
            excl.append({"symbol": s, "reason": "NO_CIK_MAPPING"})
        for s in sorted(set(symbols) - set(x.symbol for x in decisions) - set(missing_map)):
            excl.append({"symbol": s, "reason": "NO_PIT_EVIDENCE_ROW"})
        (day_root / "universe_exclusions.jsonl").write_text(
            "\n".join(json.dumps(e, default=str) for e in excl) + "\n", encoding="utf-8")
        manifest = {
            "mode": "retrospective_posthoc_cohort",
            "decision_date": d, "cohort": "generalized_v0 frozen 62",
            "n_symbols": len(symbols), "n_decisions": len(decisions),
            "regime": regime, "qqq_trailing_60d": b60,
            "code_sha": code_sha, "attention_cap": cap,
            "source_hashes": source_hashes, "split_query_end": split_end,
            "bars_start": start_iso, "monitor": monitor.to_dict(),
            "membership_note": "2026-10-11 roster is provenance only, not PIT membership",
        }
        (day_root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"{d}: decisions={len(decisions)} regime={regime} exclusions={len(excl)}")
        summaries.append({"date": d, "decisions": [(x.symbol, x.quality.grade.value,
                                                   x.entry.state.value,
                                                   x.action_state.value)
                                                  for x in decisions]})
        previous_by_symbol = decisions_by_symbol(decisions)

    # stability across the three dates (same symbols, chained previous)
    def _changes(trail: list[str], k: int) -> int:
        n = 0
        for i in range(1, len(trail)):
            if "ABSENT" in (trail[i - 1], trail[i]):
                continue
            if trail[i - 1].split("/")[k] != trail[i].split("/")[k]:
                n += 1
        return n

    with (out_root / "posthoc_stability.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["symbol"] + [f"{s['date']}_grade/state/action" for s in summaries]
                   + ["grade_changes", "state_changes", "action_changes"])
        syms = sorted({s for summ in summaries for s, _, _, _ in summ["decisions"]})
        for s in syms:
            trail = []
            for summ in summaries:
                hit = [t for t in summ["decisions"] if t[0] == s]
                trail.append("/".join(hit[0][1:]) if hit else "ABSENT")
            w.writerow([s] + trail + [_changes(trail, k) for k in range(3)])
    print(f"wrote {out_root} (3 dates chained)")


if __name__ == "__main__":
    main()
