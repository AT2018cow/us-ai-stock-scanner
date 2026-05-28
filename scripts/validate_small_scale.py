#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


CHANNELS = ["core_ai", "ai_enabler"]
REQUIRED_COLS = {
    "channel",
    "symbol",
    "ps",
    "pe",
    "ps_discount",
    "pe_discount",
    "watchlist_bucket",
    "watchlist_etf_count",
    "composite_score",
}


@dataclass
class RunArtifacts:
    name: str
    output_csv: Path
    diag_prefix: Path
    stdout: str


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run small-scale validation for scanner logic.")
    p.add_argument("--config", default="config.production.json")
    p.add_argument("--max-symbols", type=int, default=300)
    p.add_argument("--top-n", type=int, default=20)
    p.add_argument("--workdir", default="outputs/validation")
    p.add_argument("--python", default=sys.executable)
    return p.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def make_variants(base_cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    variants: dict[str, dict[str, Any]] = {}

    base = json.loads(json.dumps(base_cfg))
    variants["base"] = base

    loose = json.loads(json.dumps(base_cfg))
    loose["min_dollar_volume"] = 100_000.0
    loose.setdefault("channel_profiles", {}).setdefault("core_ai", {})["min_ps_discount"] = -1.0
    loose.setdefault("channel_profiles", {}).setdefault("core_ai", {})["min_pe_discount"] = -1.0
    loose.setdefault("channel_profiles", {}).setdefault("ai_enabler", {})["min_ps_discount"] = -1.0
    loose.setdefault("channel_profiles", {}).setdefault("ai_enabler", {})["min_pe_discount"] = -1.0
    variants["loose"] = loose

    strict = json.loads(json.dumps(base_cfg))
    strict["min_dollar_volume"] = float(strict.get("min_dollar_volume", 1_000_000.0)) * 1.5
    variants["strict"] = strict

    return variants


def run_variant(
    name: str,
    cfg_path: Path,
    output_csv: Path,
    diag_prefix: Path,
    max_symbols: int,
    top_n: int,
    python_exec: str,
) -> RunArtifacts:
    cmd = [
        python_exec,
        "run_scan.py",
        "--config",
        str(cfg_path),
        "--max-symbols",
        str(max_symbols),
        "--top-n",
        str(top_n),
        "--output",
        str(output_csv),
        "--diagnostics-output",
        str(diag_prefix),
    ]
    proc = subprocess.run(cmd, text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"{name} run failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return RunArtifacts(name=name, output_csv=output_csv, diag_prefix=diag_prefix, stdout=proc.stdout)


def check_monotonic(diag_file: Path) -> tuple[bool, str]:
    if not diag_file.exists():
        return False, f"missing diagnostics file: {diag_file}"
    df = pd.read_csv(diag_file)
    if "remaining" not in df.columns:
        return False, f"diagnostics missing remaining column: {diag_file}"
    remaining = df["remaining"].tolist()
    ok = all(remaining[i] <= remaining[i - 1] for i in range(1, len(remaining)))
    return ok, "ok" if ok else f"non-monotonic remaining: {remaining}"


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def top_symbols_by_channel(csv_path: Path, top_n: int) -> dict[str, set[str]]:
    out = {c: set() for c in CHANNELS}
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return out
    df = pd.read_csv(csv_path)
    if df.empty or "channel" not in df.columns or "symbol" not in df.columns:
        return out
    for ch in CHANNELS:
        dch = df[df["channel"] == ch].head(top_n)
        out[ch] = set(dch["symbol"].astype(str).tolist())
    return out


def parse_news_fetch_count(stdout: str) -> int | None:
    m = re.search(r"News fetch symbol count:\s*(\d+)", stdout)
    if not m:
        return None
    return int(m.group(1))


def main() -> None:
    args = parse_args()
    root = Path.cwd()
    workdir = root / args.workdir
    workdir.mkdir(parents=True, exist_ok=True)

    base_cfg = load_json(root / args.config)
    variants = make_variants(base_cfg)

    artifacts: list[RunArtifacts] = []
    for name, cfg in variants.items():
        cfg_path = workdir / f"cfg_{name}.json"
        out_csv = workdir / f"scan_{name}.csv"
        diag_prefix = workdir / f"diag_{name}.csv"
        write_json(cfg_path, cfg)
        artifacts.append(
            run_variant(
                name=name,
                cfg_path=cfg_path,
                output_csv=out_csv,
                diag_prefix=diag_prefix,
                max_symbols=args.max_symbols,
                top_n=args.top_n,
                python_exec=args.python,
            )
        )

    print("=== Validation Summary ===")
    base_top = top_symbols_by_channel(artifacts[0].output_csv, args.top_n)

    for art in artifacts:
        print(f"\n[{art.name}]")
        out_exists = art.output_csv.exists()
        print(f"output_exists: {out_exists} ({art.output_csv})")
        if out_exists and art.output_csv.stat().st_size > 0:
            df = pd.read_csv(art.output_csv)
            missing_cols = sorted(list(REQUIRED_COLS - set(df.columns)))
            print(f"rows: {len(df)}")
            print(f"missing_required_cols: {missing_cols}")
        else:
            print("rows: 0")
            print("missing_required_cols: n/a (empty)")

        news_count = parse_news_fetch_count(art.stdout)
        print(f"news_fetch_symbol_count: {news_count}")

        for ch in CHANNELS:
            diag_file = art.diag_prefix.with_name(f"{art.diag_prefix.stem}_{ch}.csv")
            ok, msg = check_monotonic(diag_file)
            print(f"{ch}_funnel_monotonic: {ok} ({msg})")
            ch_out = art.output_csv.with_name(f"{art.output_csv.stem}_{ch}{art.output_csv.suffix}")
            print(f"{ch}_output_exists: {ch_out.exists()} ({ch_out})")

    print("\n=== Sensitivity (vs base) ===")
    for art in artifacts[1:]:
        top = top_symbols_by_channel(art.output_csv, args.top_n)
        for ch in CHANNELS:
            score = jaccard(base_top[ch], top[ch])
            print(f"{art.name}_{ch}_top{args.top_n}_jaccard: {score:.3f}")

    template_rows = []
    base_df = pd.read_csv(artifacts[0].output_csv) if artifacts[0].output_csv.exists() and artifacts[0].output_csv.stat().st_size > 0 else pd.DataFrame()
    if not base_df.empty:
        for ch in CHANNELS:
            for _, row in base_df[base_df["channel"] == ch].head(min(10, args.top_n)).iterrows():
                template_rows.append(
                    {
                        "channel": ch,
                        "symbol": row.get("symbol", ""),
                        "watchlist_bucket": row.get("watchlist_bucket", ""),
                        "watchlist_etf_count": row.get("watchlist_etf_count", ""),
                        "review_label": "",
                        "notes": "",
                    }
                )
    template_path = workdir / "manual_review_template.csv"
    pd.DataFrame(template_rows).to_csv(template_path, index=False)
    print(f"\nmanual_review_template: {template_path}")


if __name__ == "__main__":
    main()
