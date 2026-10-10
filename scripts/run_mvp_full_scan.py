from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys

from dotenv import load_dotenv

from ai_value_scanner.config import load_config
from validate_mvp_snapshot import validate_snapshot


REQUIRED_ENV = (
    "ALPACA_API_ENDPOINT",
    "ALPACA_API_KEY",
    "ALPACA_API_SECRET",
    "SEC_USER_AGENT",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run one full MVP scan and automatically validate its canonical "
            "decision snapshot."
        )
    )
    parser.add_argument(
        "--config",
        default="configs/config.risk_off.json",
        help="Scan config. Default remains risk_off for compatibility.",
    )
    parser.add_argument(
        "--formal",
        action="store_true",
        help=(
            "Write to the immutable prospective archive. Without this flag, "
            "the run is an isolated repeatable experiment."
        ),
    )
    parser.add_argument(
        "--attention-cap",
        type=int,
        default=15,
        help="Daily/Weekly attention cap (default: 15).",
    )
    parser.add_argument(
        "--skip-unit-tests",
        action="store_true",
        help="Skip the fast unittest preflight.",
    )
    parser.add_argument(
        "--experiment-root",
        default=None,
        help="Optional decision-output root for a non-formal run.",
    )
    return parser


def _run_streamed(command: list[str], *, log_path: Path | None = None) -> int:
    handle = None
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handle = log_path.open("w", encoding="utf-8")
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="")
            if handle is not None:
                handle.write(line)
                handle.flush()
        return int(process.wait())
    finally:
        if handle is not None:
            handle.close()


def _snapshot_roots(root: Path, style: str) -> set[Path]:
    return {
        path.parent
        for path in root.glob(f"*/{style}/decisions.jsonl")
        if path.is_file()
    }


def main() -> None:
    args = build_parser().parse_args()
    load_dotenv()

    missing_env = [key for key in REQUIRED_ENV if not os.getenv(key)]
    if missing_env:
        raise SystemExit(
            "Missing required environment variables: " + ", ".join(missing_env)
        )

    config = load_config(args.config)
    if config.max_symbols is not None:
        raise SystemExit(
            "Full-scan acceptance requires config.max_symbols=null. "
            "Do not use a sample config."
        )

    style = str(config.strategy_style or "default")
    attention_cap = max(1, int(args.attention_cap))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    if not args.skip_unit_tests:
        print("=== 1/3 Unit-test preflight ===")
        test_code = _run_streamed(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests"]
        )
        if test_code != 0:
            raise SystemExit(test_code)

    if args.formal:
        decision_root = Path(config.output_dir) / "decisions"
        scan_command = [
            sys.executable,
            "run_scan.py",
            "--config",
            args.config,
            "--decision-attention-cap",
            str(attention_cap),
        ]
        mode = "formal"
    else:
        decision_root = Path(
            args.experiment_root
            or f"outputs/decision_experiments/{style}_{stamp}"
        )
        scan_command = [
            sys.executable,
            "run_scan.py",
            "--config",
            args.config,
            "--decision-output-root",
            str(decision_root),
            "--decision-attention-cap",
            str(attention_cap),
        ]
        mode = "experiment"

    snapshots_before = _snapshot_roots(decision_root, style)

    log_path = Path("outputs") / f"mvp_full_scan_{style}_{stamp}.log"
    print(f"=== 2/3 Full scan ({mode}) ===")
    print("Command:", " ".join(scan_command))
    print("Log:", log_path)

    scan_code = _run_streamed(scan_command, log_path=log_path)
    if scan_code != 0:
        raise SystemExit(scan_code)

    snapshots_after = _snapshot_roots(decision_root, style)
    new_snapshots = sorted(
        snapshots_after - snapshots_before,
        key=lambda path: path.as_posix(),
    )
    if len(new_snapshots) != 1:
        raise SystemExit(
            "Scan process completed, but acceptance expected exactly one new "
            f"canonical decision snapshot and found {len(new_snapshots)}. "
            f"Inspect {log_path} for a contained decision-output warning or "
            "an immutable same-session collision."
        )
    snapshot = new_snapshots[0]

    print("=== 3/3 Snapshot acceptance ===")
    result = validate_snapshot(snapshot, attention_cap=attention_cap)
    status = "PASS" if result["ok"] else "FAIL"
    print(f"[{status}] {snapshot}")
    counts = result.get("counts", {})
    if counts:
        print(
            f"decisions={counts['decisions']} "
            f"daily={counts['daily_attention']} "
            f"weekly={counts['weekly_attention']}"
        )
        print(f"quality={counts['quality']}")
        print(f"entry={counts['entry']}")
        print(f"action={counts['action']}")
    for warning in result.get("warnings", []):
        print(f"[WARN] {warning}")
    for error in result.get("errors", []):
        print(f"[ERROR] {error}")

    print("Action List:", snapshot / "action_list.md")
    print("Weekly Review:", snapshot / "weekly_review.md")
    print("Manifest:", snapshot / "run_manifest.json")
    print("Full log:", log_path)

    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
