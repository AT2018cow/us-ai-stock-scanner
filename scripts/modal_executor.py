"""Modal cloud executor for tune_parameters: candidate-level parallelism.

Each tuning candidate runs its full 4-window x 3-scenario replay inside one
Modal container (fast cloud CPU), fully reusing tune_parameters.run_candidate.
The local process only builds candidates, dispatches them with .map, and
collects CandidateScore results — no scoring logic is duplicated.

Volume: ai-scanner-cache holds the SEC/Alpaca cache tree under /cache.
Image: pins the same pandas/numpy/requests versions as the local .venv.
Secrets: ALPACA_*/SEC_USER_AGENT come from the local .env file.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path
from typing import Any

import modal

app = modal.App("ai-value-tuner")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("pandas==2.3.0", "numpy==2.0.2", "requests==2.32.3", "python-dotenv==1.0.1", "urllib3==2.2.3")
    .add_local_dir("src", "/root/src", copy=True)
    .add_local_dir("scripts", "/root/scripts", copy=True)
    .add_local_dir("configs", "/root/configs", copy=True)
    .add_local_dir("data", "/root/data", copy=True)
)

# create_if_missing=True avoids a blocking existence-check API round trip;
# the volume already exists, so this is a lazy no-op either way.
cache_volume = modal.Volume.from_name("ai-scanner-cache", create_if_missing=True)


@app.function(
    image=image,
    volumes={"/root/cache": cache_volume},
    secrets=[modal.Secret.from_dotenv(".env")],
    timeout=6 * 3600,
    # The replay is single-core pandas/JSON work (json.load holds the GIL),
    # so more cores per container only increase billing, not speed.
    cpu=1.0,
    memory=4096,
)
def run_candidate_remote(
    candidate_json: str,
    windows_json: str,
    args_json: str,
    output_stem: str,
) -> str:
    """Execute one candidate end-to-end in the cloud; return its scores.

    All payloads travel as JSON strings: modal 1.5.5 cannot parse
    free-form dict annotations in function signatures.
    """
    import json
    import sys
    from types import SimpleNamespace
    from pathlib import Path

    candidate_payload = json.loads(candidate_json)
    windows_payload = json.loads(windows_json)
    args_payload = json.loads(args_json)

    sys.path.insert(0, "/root/src")
    sys.path.insert(0, "/root/scripts")

    import tune_parameters as tp

    candidate = tp.Candidate(
        cid=str(candidate_payload["cid"]),
        config=candidate_payload["config"],
        deltas=candidate_payload["deltas"],
    )
    windows = [
        tp.TuneWindow(label=str(w["label"]), start_date=str(w["start_date"]), end_date=str(w["end_date"]))
        for w in windows_payload
    ]
    args = SimpleNamespace(**args_payload)

    work_dir = Path("/root/remote_work")
    work_dir.mkdir(parents=True, exist_ok=True)
    outputs_dir = Path("/root/remote_outputs")
    outputs_dir.mkdir(parents=True, exist_ok=True)
    args.outputs_dir = str(outputs_dir)

    try:
        score: tp.CandidateScore = tp.run_candidate(
            candidate=candidate,
            windows=windows,
            args=args,
            output_stem=output_stem,
            horizons=[int(x) for x in args_payload["_horizons"]],
            list_types=list(args_payload["_list_types"]),
            primary_list_types=list(args_payload["_primary_list_types"]),
            objective_weights=dict(tp.DEFAULT_OBJECTIVE_WEIGHTS),
            scenario_weights=dict(tp.DEFAULT_SCENARIO_WEIGHTS),
            list_weights=dict(tp.DEFAULT_LIST_WEIGHTS),
            horizon_weights={int(k): float(v) for k, v in tp.DEFAULT_HORIZON_WEIGHTS.items()},
            work_dir=work_dir,
        )
        cache_volume.commit()
        result = {"ok": True, **asdict(score)}
    except Exception as exc:  # surface the failure to the local collector
        import traceback

        result = {
            "ok": False,
            "cid": candidate.cid,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc()[-2000:],
        }
    return json.dumps(result)


def dispatch(
    candidates: list[Any],
    windows: list[Any],
    args: argparse.Namespace,
    output_stem: str,
) -> list[dict[str, Any]]:
    """Local entrypoint: dispatch the candidate batch via the Modal CLI.

    The in-process Python client's app.run() channel hangs in this
    environment, while the CLI channel (`modal run`) works fine, so we
    serialize the batch to JSON, invoke `modal run scripts/modal_executor.py`
    as a subprocess, and read back the results file.
    """
    import json
    import subprocess
    import sys

    windows_payload = [
        {"label": w.label, "start_date": w.start_date, "end_date": w.end_date} for w in windows
    ]
    args_payload = dict(vars(args))
    args_payload["_horizons"] = [int(x) for x in args.horizons.split(",") if x.strip()]
    args_payload["_list_types"] = [x for x in args.list_types.split(",") if x.strip()]
    from tune_parameters import DEFAULT_PRIMARY_LIST_TYPES

    primary = [
        x for x in args.primary_list_types.split(",") if x.strip()
    ] or list(DEFAULT_PRIMARY_LIST_TYPES)
    args_payload["_primary_list_types"] = primary

    from pathlib import Path

    work = Path(args.outputs_dir)
    work.mkdir(parents=True, exist_ok=True)
    batch_path = work / f"{output_stem}_modal_batch.json"
    results_path = work / f"{output_stem}_modal_results.json"
    batch = {
        "output_stem": output_stem,
        "windows": windows_payload,
        "args": args_payload,
        "candidates": [
            {"cid": c.cid, "config": c.config, "deltas": c.deltas} for c in candidates
        ],
    }
    batch_path.write_text(json.dumps(batch))

    modal_bin = str(Path(sys.executable).with_name("modal"))
    cmd = [modal_bin, "run", str(Path(__file__).resolve())]
    import os

    env = {**os.environ, "MODAL_BATCH_JSON": str(batch_path), "MODAL_OUT_JSON": str(results_path)}
    completed = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if completed.returncode != 0:
        raise RuntimeError(
            f"modal run failed (exit {completed.returncode}):\n{completed.stdout[-2000:]}\n{completed.stderr[-2000:]}"
        )
    results = json.loads(results_path.read_text())
    return results


@app.local_entrypoint()
def main() -> None:
    """Entry point executed by `modal run` (local entrypoint in CLI channel).

    Paths arrive via environment variables because modal run's own CLI
    parser reserves option names for function parameters.
    """
    import json
    import os
    from types import SimpleNamespace
    from pathlib import Path

    batch = json.loads(Path(os.environ["MODAL_BATCH_JSON"]).read_text())
    out_path = Path(os.environ["MODAL_OUT_JSON"])
    windows_payload = batch["windows"]
    args_payload = batch["args"]
    candidates_payload = batch["candidates"]
    output_stem = batch["output_stem"]

    from tune_parameters import TuneWindow

    windows = [
        TuneWindow(label=str(w["label"]), start_date=str(w["start_date"]), end_date=str(w["end_date"]))
        for w in windows_payload
    ]
    args = SimpleNamespace(**args_payload)

    payloads = [
        (
            json.dumps({"cid": c["cid"], "config": c["config"], "deltas": c["deltas"]}),
            json.dumps(windows_payload),
            json.dumps(args_payload),
            f"{output_stem}_{c['cid']}",
        )
        for c in candidates_payload
    ]
    # modal 1.5.5 functions have no max_concurrency knob, so concurrency is
    # capped locally: at most N tasks are in flight (spawned + awaited) at
    # any time, limiting the number of simultaneously running containers.
    import concurrent.futures

    concurrency = int(os.environ.get("MODAL_TUNER_CONCURRENCY", "12"))

    def _run_one(payload: tuple) -> str:
        call = run_candidate_remote.spawn(*payload)
        return call.get()

    raw_results: list[Any] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        futs = {pool.submit(_run_one, p): i for i, p in enumerate(payloads)}
        ordered: dict[int, str] = {}
        for fut in concurrent.futures.as_completed(futs):
            i = futs[fut]
            try:
                ordered[i] = fut.result()
            except Exception as exc:  # keep one bad candidate from killing the batch
                ordered[i] = json.dumps(
                    {"ok": False, "cid": candidates_payload[i]["cid"], "error": f"{type(exc).__name__}: {exc}"}
                )
        raw_results = [ordered[i] for i in range(len(payloads))]
    results = [json.loads(r) for r in raw_results]
    out_path.write_text(json.dumps(results))


if __name__ == "__main__":
    main()
