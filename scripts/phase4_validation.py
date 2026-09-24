"""Phase 4 system-level validation (self-contained).

Runs the three promoted production configs in parallel — one Modal container
each — and pulls back events/benchmarks/segments for combined-portfolio
analysis. Config JSONs travel as payloads so the latest promoted configs are
always used. Self-contained by design: modal mounts the entry script at /root/
inside the container, so importing sibling modules at module scope is fragile.
"""
from __future__ import annotations

import concurrent.futures
import json
import os
from pathlib import Path

import modal

app = modal.App("ai-value-phase4")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("pandas==2.3.0", "numpy==2.0.2", "requests==2.32.3",
                 "python-dotenv==1.0.1", "urllib3==2.2.3")
    .add_local_dir("src", "/root/src", copy=True)
    .add_local_dir("scripts", "/root/scripts", copy=True)
    .add_local_dir("configs", "/root/configs", copy=True)
    .add_local_dir("data", "/root/data", copy=True)
)

cache_volume = modal.Volume.from_name("ai-scanner-cache", create_if_missing=True)

CONFIGS = {
    "balanced": "configs/config.balanced.json",
    "risk_on": "configs/config.risk_on.json",
    "risk_off": "configs/config.risk_off.json",
}

BT_ARGS = {
    "list_types": ["low_value", "industry_trend", "momentum", "research_pool"],
    "top_n": 10,
    "horizons": [20, 60, 120],
    "start": "2023-01-01",
    "end": None,
    "freq": "monthly",
}


@app.function(
    image=image,
    volumes={"/root/cache": cache_volume},
    secrets=[modal.Secret.from_dotenv(".env")],
    timeout=3 * 3600,
    cpu=1.0,
    memory=4096,
)
def run_config_backtest(config_json: str, label: str, bt_args_json: str) -> str:
    import json
    import os
    import sys

    sys.path.insert(0, "/root/src")
    os.chdir("/root")

    from ai_value_scanner.backtest import BacktestConfig, run_backtest

    cfg_path = "/root/phase4_cfg.json"
    with open(cfg_path, "w") as f:
        f.write(config_json)
    a = json.loads(bt_args_json)
    out_dir = "/root/phase4_out"
    os.makedirs(out_dir, exist_ok=True)
    cfg = BacktestConfig(
        mode="historical_replay",
        scan_config_path=cfg_path,
        outputs_dir=out_dir,
        output_prefix=label,
        list_types=a["list_types"],
        top_n=a["top_n"],
        horizons=a["horizons"],
        start_date=a["start"],
        end_date=a["end"],
        rebalance_frequency=a["freq"],
        theme_source="rules_proxy",
        allow_latest_watchlist_fallback=True,
    )
    result = run_backtest(cfg)
    cache_volume.commit()

    def _read(key: str) -> str:
        path = result.get(key)
        if path and os.path.exists(path):
            with open(path) as f:
                return f.read()
        return ""

    return json.dumps(
        {
            "label": label,
            "events": _read("events_path"),
            "benchmarks": _read("benchmarks_path"),
            "segments": _read("segments_path"),
        }
    )


@app.local_entrypoint()
def phase4_main() -> None:
    bt_json = json.dumps(BT_ARGS)
    payloads = []
    for label, path in CONFIGS.items():
        config_json = Path(path).read_text()
        payloads.append((config_json, label, bt_json))

    def _run(payload):
        call = run_config_backtest.spawn(*payload)
        return call.get()

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futs = [pool.submit(_run, p) for p in payloads]
        for fut in futs:
            results.append(json.loads(fut.result()))

    out_dir = Path("outputs")
    for r in results:
        label = r["label"]
        for kind in ("events", "benchmarks", "segments"):
            text = r[kind]
            if text:
                (out_dir / f"phase4_{label}_{kind}.csv").write_text(text)
        print(f"saved phase4_{label}_* artifacts", flush=True)
    print("PHASE4_DONE", flush=True)
