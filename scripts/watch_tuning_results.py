"""Watchdog for Phase 3R tuner runs: retrieve + back up results immediately.

The Modal tuner flow materializes results ONLY at the very end:
  containers -> call.get() (local memory) -> modal_results.json -> results.csv
If the local process dies before writing, hours of compute are lost. This
watchdog polls process liveness; on exit it immediately (a) verifies all
expected artifacts exist, (b) copies them to a timestamped backup dir, and
(c) writes a clear status line for each run.

Usage (background):
  nohup .venv/bin/python scripts/watch_tuning_results.py \
      --patterns "tuning_risk_on_3r:tune_parameters.*risk_on" \
                 "tuning_risk_off_3r:tune_parameters.*risk_off" \
      --watch-log .debug_logs/watchdog_3r.log &
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

EXPECTED = ["_modal_results.json", "_results.csv", "_summary.json", "_report.md"]


def log(msg: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[watchdog {stamp}] {msg}", flush=True)


def pgrep_alive(pattern: str) -> bool:
    """True if another process (not this watchdog) matches the pattern.

    The watchdog's own cmdline embeds the pattern text, so raw pgrep -f
    self-matches forever. Exclude our PID explicitly.
    """
    out = subprocess.run(
        ["pgrep", "-f", pattern], capture_output=True, text=True
    ).stdout.split()
    pids = [int(x) for x in out if x.strip().isdigit() and int(x) != os.getpid()]
    return bool(pids)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--patterns",
        nargs="+",
        required=True,
        help="stem:process_regex pairs, e.g. tuning_risk_on_3r:tune_parameters.*risk_on",
    )
    p.add_argument("--outputs-dir", default="outputs")
    p.add_argument("--backup-dir", default="outputs/tuning_3r_backup")
    p.add_argument("--interval-sec", type=int, default=60)
    args = p.parse_args()

    runs = []
    for token in args.patterns:
        stem, regex = token.split(":", 1)
        runs.append({"stem": stem, "regex": regex, "done": False})
    log(f"watching {len(runs)} runs: {[r['stem'] for r in runs]}")

    while not all(r["done"] for r in runs):
        time.sleep(args.interval_sec)
        for r in runs:
            if r["done"]:
                continue
            alive = pgrep_alive(r["regex"])
            if alive:
                continue
            # process exited: verify artifacts NOW
            stem = r["stem"]
            found = {}
            for suffix in EXPECTED:
                path = Path(args.outputs_dir) / f"{stem}{suffix}"
                found[suffix] = path.exists()
            if all(found.values()):
                ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                dest = Path(args.backup_dir) / f"{stem}_{ts}"
                dest.mkdir(parents=True, exist_ok=True)
                for suffix in EXPECTED:
                    src = Path(args.outputs_dir) / f"{stem}{suffix}"
                    if src.exists():
                        shutil.copy2(src, dest / src.name)
                log(f"{stem}: COMPLETE, all artifacts present, backed up to {dest}")
                r["done"] = True
            else:
                missing = [s for s, ok in found.items() if not ok]
                log(
                    f"ALERT {stem}: process exited but MISSING {missing}! "
                    f"Results may be lost - investigate immediately."
                )
                r["done"] = True  # don't spam; single loud alert

    log("all runs processed; watchdog exiting")


if __name__ == "__main__":
    main()
