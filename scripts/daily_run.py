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


def log(msg: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[daily {stamp}] {msg}", flush=True)


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
    p.add_argument("--capital", type=float, default=None, help="If set, also generate trade plan")
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

    # ---- 可选：trade plan ----
    if args.capital:
        ok &= run([python, "-u", "scripts/generate_trade_plan.py", "--capital", str(args.capital)],
                  "⑨ AI trade plan 生成")

    if not ok:
        log("⚠ 有任务失败——检查上方日志")
        sys.exit(1)
    log(f"✓ 全部任务完成。日志: {log_file}")


if __name__ == "__main__":
    main()
