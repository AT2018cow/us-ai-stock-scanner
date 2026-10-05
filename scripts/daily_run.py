"""每日运行入口：按当前日期选择该跑的任务。

工作日（Mon-Fri）：
  1. AI 双风格观察扫描（risk_off + risk_on）
  2. 五主题扫描 + cohort 归档
  3. Venture sleeve 扫描 + cohort 归档
  4. 左侧名单资金流统计（scripts/flow_tracker.py，8 交易日大单流回填；
     可 --skip-flow 跳过，--flow-days N 调窗口，--flow-extra-symbols 附加自选）

周一额外：
  5. 数据质量门槛（validate_ttm_population）
  6. 主题篮子刷新 + 新成员 diff
  7. Venture 三层底单重建（--fts）

周五额外：
  8. 所有到期 cohort 结算（--evaluate，120 交易日到期才真正结算）

AI trade plan 是给人工复核用的快速参考摘要，不是订单或自动交易指令。它不读取券商
持仓、不维护账户状态，也不会下单。默认不生成；需要快速参考时由操作人显式传
--generate-trade-plan。生成前要求本次 AI 双风格扫描成功（若本次执行扫描）以及当日
周检成功（若当天为周一）。

所有日志写入 .debug_logs/daily_YYYYMMDD.log。可用 --skip-scan 跳过扫描只跑结算。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def log(msg: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[daily {stamp}] {msg}", flush=True)


def print_reference_guidance(capital: float) -> None:
    """Consolidated manual-review reference from all observation streams."""
    import glob
    import json

    # ---- 1. AI trade plan (latest) ----
    plans = sorted(glob.glob("outputs/trade_plan_*.md"), key=lambda p: Path(p).stat().st_mtime, reverse=True)
    if plans:
        text = Path(plans[0]).read_text()
        # Extract breaker + positions
        breaker_line = [l for l in text.splitlines() if "熔断器" in l]
        if breaker_line:
            log(f"  熔断器: {breaker_line[0].replace('- 熔断器: ', '').strip()}")
        # 从 MD 表格提取持仓行（所有 ### 子标题下的表格统一收集）
        rows = []
        for l in text.splitlines():
            if l.startswith("| ") and "symbol" in l.lower() and "---" not in l:
                continue  # header
            if l.startswith("|---"):
                continue
            if l.startswith("| ") and "weight" not in l and "triage" in l.lower() or l.startswith("| ") and "momentum" in l.lower() or l.startswith("| ") and "keep" in l.lower() or l.startswith("| ") and "watch" in l.lower():
                cols = [x.strip() for x in l.split("|")]
                if len(cols) >= 7 and cols[1] and cols[1] not in ("symbol", "", "lists"):
                    rows.append({"symbol": cols[1].split("/")[0].split("+")[0].strip(),
                                 "triage": cols[5] if len(cols) > 5 else "",
                                 "weight": cols[6] if len(cols) > 6 else ""})
        if rows:
            log(f"  AI trade plan reference: {len(rows)} 个参考标的:")
            for r in rows[:12]:
                log(f"    {r['symbol']:<8s} {r['triage']:<12s} {r['weight']}")
            if len(rows) > 12:
                log(f"    ... 共 {len(rows)} 个")
        log(f"  详细参考: {plans[0]}")

    # ---- 2. Theme cohorts (today's entries) ----
    cohort_file = Path("data/theme_cohorts.csv")
    today = datetime.now(timezone.utc).date().isoformat()
    if cohort_file.exists():
        d = pd.read_csv(cohort_file)
        today_rows = d[d["entry_date"] == today]
        if not today_rows.empty:
            for (theme, lt), part in today_rows.groupby(["theme", "list_type"]):
                syms = part["symbol"].dropna().tolist()
                if syms:
                    log(f"  主题 {theme}/{lt}: {len(part)} 只 → {', '.join(syms[:6])}{'...' if len(syms) > 6 else ''}")
        else:
            log("  五主题: 今日无新 cohort（可能 no_signal 或已有同日数据）")

    # ---- 3. Venture cohorts (today's entries) ----
    vc_file = Path("data/venture_cohorts.csv")
    if vc_file.exists():
        vd = pd.read_csv(vc_file)
        v_today = vd[vd["entry_date"] == today]
        if not v_today.empty:
            for (theme, lt), part in v_today.groupby(["theme", "list_type"]):
                syms = part["symbol"].dropna().tolist()
                if syms:
                    log(f"  Venture {theme}/{lt}: {len(part)} 只 → {', '.join(syms[:6])}{'...' if len(syms) > 6 else ''}")
        else:
            log("  Venture: 今日无新 cohort")

    # ---- 4. Research pool highlights ----
    reports = sorted(glob.glob("outputs/ai_value_scan_*_full_ranked_report.md"), key=lambda p: Path(p).stat().st_mtime, reverse=True)
    for rp in reports[:2]:
        head = Path(rp).read_text()[:300]
        if "config.risk_off.json" in head:
            text = Path(rp).read_text()
            rn = [l for l in text.splitlines() if "priority=research_now" in l and l.startswith("  - ")]
            if rn:
                log(f"  研究池 research_now {len(rn)} 个:")
                for r in rn[:5]:
                    sym = r.strip().split("|")[0].replace("-", "").strip() if "|" in r else r.strip()[:30]
                    log(f"    {sym}")
            break

    # ---- 5. 提醒 ----
    log("─" * 60)
    log("  AI trade plan 仅为人工复核参考；不生成订单、不读取券商持仓、不自动交易。")
    log("  次日开盘/权重等字段是协议参考口径，是否交易及如何执行由人工决定。")
    log("  主题/venture 为 P0 纸面观察，120 交易日后自动结算。")
    log("  每周五 --evaluate 结算到期行。")
    log("═" * 60)


def run(cmd: list[str], label: str) -> bool:
    log(f"▶ {label}")
    result = subprocess.run(cmd)
    ok = result.returncode == 0
    log(f"{'✓' if ok else '✗ FAIL'} {label} (exit {result.returncode})")
    return ok


def collect_left_side_symbols(since_ts: float, today_tag: str) -> tuple[set[str], list[str]]:
    import csv as _csv
    import glob

    pools = sorted(glob.glob(f"outputs/ai_value_scan_{today_tag}*_full_ranked_research_pool.csv"))
    fresh = [p for p in pools if Path(p).stat().st_mtime >= since_ts]
    used = fresh if fresh else pools
    syms: set[str] = set()
    for p in used:
        try:
            with open(p) as f:
                for r in _csv.DictReader(f):
                    if r.get("research_priority") == "left_side_watch" and r.get("symbol"):
                        syms.add(str(r["symbol"]).upper())
        except OSError:
            continue
    return syms, used


def main() -> None:
    p = argparse.ArgumentParser(description="Daily runner for all observation loops.")
    p.add_argument("--skip-scan", action="store_true", help="Skip scans, only run evaluate/maintenance")
    p.add_argument("--evaluate", action="store_true", help="Run cohort settlement even on non-Friday")
    p.add_argument("--capital", type=float, default=100000, help="Default capital for trade plan generation")
    p.add_argument("--skip-flow", action="store_true", help="Skip left-side block-flow statistics")
    p.add_argument("--flow-days", type=int, default=8, help="Lookback trading days for block-flow stats")
    p.add_argument("--flow-extra-symbols", default="", help="Extra symbols appended to the left-side flow run")
    p.add_argument(
        "--generate-trade-plan",
        action="store_true",
        help="Explicitly generate the AI trade-plan reference summary for manual review; never runs by default.",
    )
    args = p.parse_args()

    now = datetime.now(timezone.utc)
    dow = now.weekday()  # 0=Mon ... 4=Fri, 5=Sat, 6=Sun
    date_tag = now.strftime("%Y%m%d")
    run_started_ts = time.time()
    log_file = Path(f".debug_logs/daily_{date_tag}.log")

    if dow >= 5 and not args.evaluate:
        log("周末（Sat/Sun）——市场关闭，仅可跑 --evaluate 结算或数据维护。跳过扫描。")
        return

    themes = ["nuclear", "quantum", "biotech", "rare_earth", "critical_minerals"]
    python = sys.executable
    ok = True
    ai_scan_ok = True
    validation_ok = True

    # ---- 每日：AI 双风格 ----
    if not args.skip_scan:
        ai_scan_ok = run([python, "-u", "scripts/observation_scan.py"], "① AI 双风格观察扫描")
        ok &= ai_scan_ok

    # ---- 每日：五主题 ----
    if not args.skip_scan:
        ok &= run([python, "-u", "scripts/theme_observation_scan.py"], "② 五主题扫描 + cohort 归档")

    # ---- 每日：Venture sleeve ----
    if not args.skip_scan:
        ok &= run([python, "-u", "scripts/theme_observation_scan.py", "--sleeve", "venture"],
                  "③ Venture sleeve 扫描 + cohort 归档")

    # ---- 周一：数据质量门槛 + 主题篮子刷新 + venture 底单重建 ----
    if dow == 0:
        validation_ok = run([python, "-u", "scripts/validate_ttm_population.py"], "④ 数据质量门槛（周检）")
        ok &= validation_ok
        ok &= run([python, "-u", "scripts/build_theme_universe.py"], "⑤ 主题篮子刷新 + 新成员 diff")
        ok &= run([python, "-u", "scripts/build_venture_universe.py", "--fts"], "⑥ Venture 三层底单重建")

    # ---- 周五（或 --evaluate 强制）：cohort 结算 ----
    if dow == 4 or args.evaluate:
        ok &= run([python, "-u", "scripts/theme_observation_scan.py", "--evaluate"], "⑦ 五主题 cohort 结算")
        ok &= run([python, "-u", "scripts/theme_observation_scan.py", "--sleeve", "venture", "--evaluate"],
                  "⑧ Venture cohort 结算")

    # ---- 每日：左侧名单资金流（注释层，失败不阻塞） ----
    if not args.skip_flow:
        syms, used = collect_left_side_symbols(run_started_ts, date_tag)
        if syms:
            cmd = [python, "-u", "scripts/flow_tracker.py", "--days", str(args.flow_days),
                   "--symbols", ",".join(sorted(syms))]
            if args.flow_extra_symbols:
                cmd += ["--extra-symbols", args.flow_extra_symbols]
            run(cmd, f"左侧资金流（{len(syms)} 只 × {args.flow_days} 交易日，池来源 {len(used)} 个）")
        else:
            log("✓ 左侧资金流: 今日无 left_side_watch 名单，跳过")

    # ---- 显式：trade plan + 操作指导 ----
    plan_ok = False
    if args.generate_trade_plan:
        if not ai_scan_ok:
            log("✗ AI trade plan 跳过：本次双风格扫描失败，禁止使用旧报告补位。")
            ok = False
        elif dow == 0 and not validation_ok:
            log("✗ AI trade plan 跳过：今日数据质量周检失败。")
            ok = False
        else:
            plan_ok = run(
                [python, "-u", "scripts/generate_trade_plan.py", "--capital", str(args.capital)],
                "⑨ AI trade plan 生成",
            )
            ok &= plan_ok
        if plan_ok:
            log("═" * 60)
            log("📋 TODAY'S MANUAL-REVIEW REFERENCE")
            log("═" * 60)
            print_reference_guidance(args.capital)
        else:
            log("交易参考未生成成功；不打印任何旧参考摘要。")
    else:
        log("✓ AI trade plan: 默认不生成（按月度 cohort 节奏，需要时显式传 --generate-trade-plan）")

    if not ok:
        log("⚠ 有任务失败——检查上方日志")
        sys.exit(1)
    log(f"✓ 全部任务完成。日志: {log_file}")


if __name__ == "__main__":
    main()
