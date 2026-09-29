"""每日运行入口：按当前日期选择该跑的任务。

工作日（Mon-Fri）：
  1. AI 双风格观察扫描（risk_off + risk_on）
  2. 五主题扫描 + cohort 归档
  3. Venture sleeve 扫描 + cohort 归档

周一额外：
  4. 数据质量门槛（validate_ttm_population）
  5. 主题篮子刷新 + 新成员 diff
  6. Venture 三层底单重建（--fts）

周五额外：
  7. 所有到期 cohort 结算（--evaluate，120 交易日到期才真正结算）
  8. AI trade plan 生成（可选，仅 P0 阶段标记纸面）

所有日志写入 .debug_logs/daily_YYYYMMDD.log。可用 --skip-scan 跳过扫描只跑结算。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def log(msg: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[daily {stamp}] {msg}", flush=True)


def print_operation_guidance(capital: float) -> None:
    """Consolidated operation guidance from all observation streams."""
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
            log(f"  AI trade plan: {len(rows)} 个仓位:")
            for r in rows[:12]:
                log(f"    {r['symbol']:<8s} {r['triage']:<12s} {r['weight']}")
            if len(rows) > 12:
                log(f"    ... 共 {len(rows)} 个")
        log(f"  详细计划: {plans[0]}")

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
    log("  ⚡ 操作: AI trade plan 的仓位按次日开盘市价单执行；")
    log("  主题/venture 为 P0 纸面（不买），120 交易日后自动结算。")
    log("  每周五 --evaluate 结算到期行。")
    log("═" * 60)


def run(cmd: list[str], label: str) -> bool:
    log(f"▶ {label}")
    result = subprocess.run(cmd)
    ok = result.returncode == 0
    log(f"{'✓' if ok else '✗ FAIL'} {label} (exit {result.returncode})")
    return ok


def main() -> None:
    p = argparse.ArgumentParser(description="Daily runner for all observation loops.")
    p.add_argument("--skip-scan", action="store_true", help="Skip scans, only run evaluate/maintenance")
    p.add_argument("--evaluate", action="store_true", help="Run cohort settlement even on non-Friday")
    p.add_argument("--capital", type=float, default=100000, help="Default capital for trade plan generation")
    args = p.parse_args()

    now = datetime.now(timezone.utc)
    dow = now.weekday()  # 0=Mon ... 4=Fri, 5=Sat, 6=Sun
    date_tag = now.strftime("%Y%m%d")
    log_file = Path(f".debug_logs/daily_{date_tag}.log")

    if dow >= 5 and not args.evaluate:
        log("周末（Sat/Sun）——市场关闭，仅可跑 --evaluate 结算或数据维护。跳过扫描。")
        return

    themes = ["nuclear", "quantum", "biotech", "rare_earth", "critical_minerals"]
    python = sys.executable
    ok = True

    # ---- 每日：AI 双风格 ----
    if not args.skip_scan:
        ok &= run([python, "-u", "scripts/observation_scan.py"], "① AI 双风格观察扫描")

    # ---- 每日：五主题 ----
    if not args.skip_scan:
        ok &= run([python, "-u", "scripts/theme_observation_scan.py"], "② 五主题扫描 + cohort 归档")

    # ---- 每日：Venture sleeve ----
    if not args.skip_scan:
        ok &= run([python, "-u", "scripts/theme_observation_scan.py", "--sleeve", "venture"],
                  "③ Venture sleeve 扫描 + cohort 归档")

    # ---- 周一：数据质量门槛 + 主题篮子刷新 + venture 底单重建 ----
    if dow == 0:
        ok &= run([python, "-u", "scripts/validate_ttm_population.py"], "④ 数据质量门槛（周检）")
        ok &= run([python, "-u", "scripts/build_theme_universe.py"], "⑤ 主题篮子刷新 + 新成员 diff")
        ok &= run([python, "-u", "scripts/build_venture_universe.py", "--fts"], "⑥ Venture 三层底单重建")

    # ---- 周五（或 --evaluate 强制）：cohort 结算 ----
    if dow == 4 or args.evaluate:
        ok &= run([python, "-u", "scripts/theme_observation_scan.py", "--evaluate"], "⑦ 五主题 cohort 结算")
        ok &= run([python, "-u", "scripts/theme_observation_scan.py", "--sleeve", "venture", "--evaluate"],
                  "⑧ Venture cohort 结算")

    # ---- 每日：trade plan + 操作指导 ----
    ok &= run([python, "-u", "scripts/generate_trade_plan.py", "--capital", str(args.capital)],
              "④ AI trade plan 生成")

    # ---- 整合操作指导 ----
    log("═" * 60)
    log("📋 TODAY'S OPERATION GUIDE")
    log("═" * 60)
    print_operation_guidance(args.capital)

    if not ok:
        log("⚠ 有任务失败——检查上方日志")
        sys.exit(1)
    log(f"✓ 全部任务完成。日志: {log_file}")


if __name__ == "__main__":
    main()
