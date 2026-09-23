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

from tune_parameters import DEFAULT_PRIMARY_LIST_TYPES

app = modal.App("ai-value-tuner")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("pandas==2.3.0", "numpy==2.0.2", "requests==2.32.3")
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
)
def run_candidate_remote(
    candidate_payload: dict[str, Any],
    windows_payload: list[dict[str, str]],
    args_payload: dict[str, Any],
    output_stem: str,
) -> dict[str, Any]:
    """Execute one candidate end-to-end in the cloud; return its scores."""
    import sys
    from types import SimpleNamespace

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
        return {"ok": True, **asdict(score)}
    except Exception as exc:  # surface the failure to the local collector
        import traceback

        return {"ok": False, "cid": candidate.cid, "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()[-2000:]}


def dispatch(
    candidates: list[Any],
    windows: list[Any],
    args: argparse.Namespace,
    output_stem: str,
) -> list[dict[str, Any]]:
    """Local entrypoint: run all candidates in parallel on Modal."""
    windows_payload = [
        {"label": w.label, "start_date": w.start_date, "end_date": w.end_date} for w in windows
    ]
    args_payload = dict(vars(args))
    args_payload["_horizons"] = [int(x) for x in args.horizons.split(",") if x.strip()]
    args_payload["_list_types"] = [x for x in args.list_types.split(",") if x.strip()]
    primary = [
        x for x in args.primary_list_types.split(",") if x.strip()
    ] or list(DEFAULT_PRIMARY_LIST_TYPES)
    args_payload["_primary_list_types"] = primary

    payloads = [
        (
            {"cid": c.cid, "config": c.config, "deltas": c.deltas},
            windows_payload,
            args_payload,
            f"{output_stem}_{c.cid}",
        )
        for c in candidates
    ]
    with app.run():
        results = list(run_candidate_remote.map(payloads))
    return results
