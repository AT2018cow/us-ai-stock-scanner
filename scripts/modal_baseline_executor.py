"""Modal runner for heavy post-PR23 baseline research stages.

The 2-vCPU/8-GB experiment host is only the launcher. Historical replay and
survivor-dataset extraction run in a larger Modal container with the canonical
cache Volume mounted at /root/cache.

Replay checkpoints and final artifacts live in the persistent
ai-scanner-research Volume. The replay commits both research and cache Volumes
after every completed signal date, so interruption resumes from the last
completed date instead of restarting the full history.

This runner is intentionally foreground-only. Launch it with "modal run" and
do not use detached execution for research evidence runs.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import modal

app = modal.App("ai-value-post-pr23-baseline")

REQUIRED_MODAL_PROFILE = "infi"

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "pandas==2.3.0",
        "numpy==2.0.2",
        "requests==2.32.3",
        "python-dotenv==1.0.1",
        "urllib3==2.2.3",
    )
    .add_local_dir("src", "/root/src", copy=True)
    .add_local_dir("scripts", "/root/scripts", copy=True)
    .add_local_dir("configs", "/root/configs", copy=True)
    .add_local_dir("data", "/root/data", copy=True)
)

cache_volume = modal.Volume.from_name("ai-scanner-cache", create_if_missing=True)
research_volume = modal.Volume.from_name(
    "ai-scanner-research",
    create_if_missing=True,
)

# The launcher host OOM'd at 8 GB, but the true peak is not yet measured.
# Request modest resources and allow bounded burst instead of reserving 24 GB
# for the whole run. Raise MEMORY_LIMIT_MIB only after a reproducible OOM.
CPU_REQUEST_LIMIT = (1.0, 2.0)
MEMORY_REQUEST_LIMIT_MIB = (8192, 16384)

_MODAL_ENV_KEYS = (
    "ALPACA_API_ENDPOINT",
    "ALPACA_API_KEY",
    "ALPACA_API_SECRET",
    "ALPACA_DATA_ENDPOINT",
    "ALPACA_FEED",
    "SEC_USER_AGENT",
)


def _modal_secrets() -> list:
    found: dict[str, str] = {}
    try:
        for line in Path(".env").read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key in _MODAL_ENV_KEYS and val:
                found[key] = val
    except OSError:
        pass
    print(
        f"[modal-baseline] shipping {len(found)}/{len(_MODAL_ENV_KEYS)} "
        "env keys (names only)",
        flush=True,
    )
    return [modal.Secret.from_dict(found)]


def _validate_token(raw: str, name: str) -> str:
    token = str(raw).strip()
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
    if not token or any(ch not in allowed for ch in token):
        raise ValueError(f"invalid {name}: {raw!r}")
    return token


def _style_config(style: str) -> str:
    if style not in {"risk_on", "risk_off"}:
        raise ValueError(f"unsupported style: {style}")
    return f"/root/configs/config.{style}.json"


def _durable_spec(spec: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in spec.items() if key != "resume"}


def _success_matches(path: Path, spec: dict[str, Any]) -> bool:
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text())
    except Exception:
        return False
    return (
        payload.get("spec") == _durable_spec(spec)
        and payload.get("status") == "success"
    )


@app.function(
    image=image,
    volumes={
        "/root/cache": cache_volume,
        "/root/research": research_volume,
    },
    secrets=_modal_secrets(),
    timeout=12 * 3600,
    cpu=CPU_REQUEST_LIMIT,
    memory=MEMORY_REQUEST_LIMIT_MIB,
)
def run_replay_remote(payload_json: str) -> str:
    import sys

    os.chdir("/root")
    sys.path.insert(0, "/root/src")

    from ai_value_scanner.backtest import BacktestConfig, run_backtest

    spec = json.loads(payload_json)
    run_id = _validate_token(spec["run_id"], "run_id")
    style = _validate_token(spec["style"], "style")
    resume = bool(spec.get("resume", True))

    root = Path("/root/research") / run_id
    output_dir = root / "replay" / style
    checkpoint_dir = root / "checkpoints" / style
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    success_path = output_dir / "_SUCCESS.json"

    if resume and _success_matches(success_path, spec):
        return json.dumps(
            {
                "status": "already_complete",
                "style": style,
                "output_dir": str(output_dir),
                "success": str(success_path),
            }
        )

    durable_spec = _durable_spec(spec)
    runner_spec_path = checkpoint_dir / "_RUN_SPEC.json"
    if runner_spec_path.exists():
        existing_spec = json.loads(runner_spec_path.read_text())
        if resume and existing_spec != durable_spec:
            raise RuntimeError(
                "checkpoint run spec mismatch; use a new run_id or --no-resume"
            )
    if not resume or not runner_spec_path.exists():
        runner_spec_path.write_text(
            json.dumps(durable_spec, indent=2, sort_keys=True) + "\n"
        )
        research_volume.commit()

    checkpoint_manifest = checkpoint_dir / "base" / "manifest.json"
    resume_checkpoints = bool(resume and checkpoint_manifest.exists())

    def commit_state() -> None:
        research_volume.commit()
        cache_volume.commit()

    cfg = BacktestConfig(
        mode="historical_replay",
        scan_config_path=_style_config(style),
        outputs_dir=str(output_dir),
        output_prefix=f"{run_id}_{style}",
        list_types=[
            "low_value",
            "industry_trend",
            "momentum",
            "research_pool",
        ],
        top_n=10,
        per_channel_top_n=True,
        include_channels=[
            "core_ai",
            "ai_enabler",
            "ai_peripheral",
        ],
        horizons=[20, 60, 120],
        start_date=str(spec["start_date"]),
        end_date=str(spec["end_date"]),
        benchmark_symbols=["QQQ", "SOXX", "XLI", "XLU"],
        trading_cost_bps=15.0,
        entry_price_mode="next_open",
        exit_price_mode="close",
        rebalance_frequency="monthly",
        replay_max_symbols=800,
        replay_asset_status="all",
        watchlist_history_dir="/root/data/watchlist_history",
        watchlist_csv_path="/root/data/ai_watchlist.csv",
        allow_latest_watchlist_fallback=False,
        pre_snapshot_universe="union",
        disclosure_lookback_days=720,
        theme_source="rules_proxy",
        enable_perturbation=False,
        delist_return_assumption=-0.55,
        delist_detection_buffer_days=7,
        signal_checkpoint_dir=str(checkpoint_dir),
        resume_signal_checkpoints=resume_checkpoints,
        signal_checkpoint_commit=commit_state,
    )
    result = run_backtest(cfg)
    normalized = {key: str(value) for key, value in result.items()}
    success_payload = {
        "status": "success",
        "spec": durable_spec,
        "result": normalized,
    }
    success_path.write_text(
        json.dumps(success_payload, indent=2, sort_keys=True) + "\n"
    )
    commit_state()
    return json.dumps(
        {
            "status": "success",
            "style": style,
            "output_dir": str(output_dir),
            "checkpoints": str(checkpoint_dir),
            "result": normalized,
        }
    )


@app.function(
    image=image,
    volumes={
        "/root/cache": cache_volume,
        "/root/research": research_volume,
    },
    secrets=_modal_secrets(),
    timeout=12 * 3600,
    cpu=CPU_REQUEST_LIMIT,
    memory=MEMORY_REQUEST_LIMIT_MIB,
)
def run_dataset_remote(payload_json: str) -> str:
    import sys

    os.chdir("/root")
    spec = json.loads(payload_json)
    run_id = _validate_token(spec["run_id"], "run_id")
    style = _validate_token(spec["style"], "style")
    resume = bool(spec.get("resume", True))

    root = Path("/root/research") / run_id
    output_dir = root / "datasets"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"weight_dataset_{style}.csv"
    success_path = output_dir / f"weight_dataset_{style}.SUCCESS.json"

    if resume and _success_matches(success_path, spec):
        return json.dumps(
            {
                "status": "already_complete",
                "style": style,
                "output": str(output_path),
            }
        )

    cmd = [
        sys.executable,
        "/root/scripts/extract_weight_dataset.py",
        "--scan-config",
        _style_config(style),
        "--output",
        str(output_path),
        "--list-types",
        "low_value,momentum",
        "--start-date",
        str(spec["start_date"]),
        "--end-date",
        str(spec["end_date"]),
        "--rebalance-frequency",
        "monthly",
        "--horizons",
        "20,60,120",
        "--trading-cost-bps",
        "15",
        "--entry-price-mode",
        "next_open",
        "--exit-price-mode",
        "close",
        "--watchlist-history-dir",
        "/root/data/watchlist_history",
        "--watchlist-csv-path",
        "/root/data/ai_watchlist.csv",
        "--pre-snapshot-universe",
        "union",
        "--no-latest-watchlist-fallback",
        "--theme-source",
        "rules_proxy",
        "--include-channels",
        "core_ai,ai_enabler,ai_peripheral",
    ]
    completed = subprocess.run(cmd, text=True)
    if completed.returncode != 0:
        raise RuntimeError(
            f"weight dataset extraction failed with exit {completed.returncode}"
        )

    success_path.write_text(
        json.dumps(
            {
                "status": "success",
                "spec": _durable_spec(spec),
                "output": str(output_path),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    research_volume.commit()
    cache_volume.commit()
    return json.dumps(
        {
            "status": "success",
            "style": style,
            "output": str(output_path),
        }
    )


def _local_path_sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    if path.is_file():
        digest.update(path.read_bytes())
        return digest.hexdigest()
    for child in sorted(x for x in path.rglob("*") if x.is_file()):
        rel = child.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(rel).to_bytes(8, "big"))
        digest.update(rel)
        with child.open("rb") as handle:
            while True:
                block = handle.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
    return digest.hexdigest()


def _verify_frozen_inputs(
    frozen_dir: Path,
    styles: list[str],
) -> None:
    pairs: list[tuple[Path, Path]] = [
        (frozen_dir / "ai_watchlist.csv", Path("data/ai_watchlist.csv")),
        (
            frozen_dir / "watchlist_history",
            Path("data/watchlist_history"),
        ),
    ]
    for style in styles:
        pairs.append(
            (
                frozen_dir / f"config.{style}.json",
                Path(f"configs/config.{style}.json"),
            )
        )

    mismatches: list[str] = []
    for frozen, live in pairs:
        frozen_hash = _local_path_sha256(frozen)
        live_hash = _local_path_sha256(live)
        if frozen_hash is None:
            mismatches.append(f"missing frozen input: {frozen}")
        elif live_hash is None:
            mismatches.append(f"missing repository input: {live}")
        elif frozen_hash != live_hash:
            mismatches.append(
                f"hash mismatch: frozen={frozen} live={live}"
            )
    if mismatches:
        raise RuntimeError(
            "Modal image inputs do not match the frozen experiment state:\n- "
            + "\n- ".join(mismatches)
        )


def _require_experiment_modal_profile() -> None:
    profile = os.getenv("MODAL_PROFILE", "").strip()
    if profile != REQUIRED_MODAL_PROFILE:
        raise RuntimeError(
            "post-PR23 research runs must explicitly target the infi Modal "
            "workspace/profile. Prefix the command with MODAL_PROFILE=infi; "
            f"got {profile!r}."
        )


def _current_git_sha() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


@app.local_entrypoint()
def main(
    run_id: str = "post_pr23_baseline_202610",
    stage: str = "replay",
    styles: str = "risk_off,risk_on",
    start_date: str = "2023-01-01",
    end_date: str = "2026-09-30",
    frozen_input_dir: str = "",
    resume: bool = True,
) -> None:
    """Launch heavy baseline stages on Modal."""
    _require_experiment_modal_profile()
    run_id = _validate_token(run_id, "run_id")
    style_list = [x.strip() for x in styles.split(",") if x.strip()]
    if not style_list or any(x not in {"risk_on", "risk_off"} for x in style_list):
        raise ValueError("styles must contain risk_on and/or risk_off")
    if stage not in {"replay", "dataset", "all"}:
        raise ValueError("stage must be replay, dataset, or all")

    frozen_dir = (
        Path(frozen_input_dir)
        if frozen_input_dir
        else Path("outputs") / run_id / "frozen_inputs"
    )
    _verify_frozen_inputs(frozen_dir, style_list)

    code_sha = _current_git_sha()
    specs = [
        json.dumps(
            {
                "run_id": run_id,
                "style": style,
                "start_date": start_date,
                "end_date": end_date,
                "code_sha": code_sha,
                "resume": bool(resume),
            },
            sort_keys=True,
        )
        for style in style_list
    ]

    print(
        f"[modal-baseline] run_id={run_id} stage={stage} "
        f"styles={style_list} code_sha={code_sha}",
        flush=True,
    )
    print(
        "[modal-baseline] verified repository data/config hashes against "
        f"{frozen_dir}",
        flush=True,
    )

    if stage in {"replay", "all"}:
        for spec in specs:
            print(run_replay_remote.remote(spec), flush=True)

    if stage in {"dataset", "all"}:
        for spec in specs:
            print(run_dataset_remote.remote(spec), flush=True)

    print(
        "[modal-baseline] durable artifacts: "
        f"ai-scanner-research:/{run_id}",
        flush=True,
    )
