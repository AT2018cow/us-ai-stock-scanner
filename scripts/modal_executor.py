"""Modal cloud executor for tune_parameters: candidate-level parallelism.

Each tuning candidate runs its full 4-window x 3-scenario replay inside one
Modal container (fast cloud CPU), fully reusing tune_parameters.run_candidate.
No scoring logic is duplicated.

Batch orchestration runs SERVER-SIDE (run_batch_remote): a single orchestrator
container spawns the candidate calls, collects their results, and persists
them incrementally to the ai-scanner-research volume after every completed
candidate. This survives local CLI/network failures: even if the `modal run`
client dies mid-batch, committed partial results remain on the volume and a
re-run of the same batch resumes from them.

The local process only builds candidates, invokes `modal run` (CLI channel),
and copies the finished results file back from the volume. If the CLI channel
fails after the batch completed, dispatch() recovers the results file with
`modal volume get`.

Volume: ai-scanner-cache holds the SEC/Alpaca cache tree under /cache;
ai-scanner-research holds resumable batch results under /batch_results.
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
research_volume = modal.Volume.from_name("ai-scanner-research", create_if_missing=True)

BATCH_RESULTS_DIR = "batch_results"


def _batch_result_paths(output_stem: str) -> tuple[Path, Path]:
    root = Path("/root/research") / BATCH_RESULTS_DIR
    return (
        root / f"{output_stem}_modal_results.partial.json",
        root / f"{output_stem}_modal_results.json",
    )


# Exact env keys the cloud replay reads (grep os.getenv/os.environ in src/):
# shipping the whole .env would also grant unrelated local secrets.
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
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key in _MODAL_ENV_KEYS and val:
                found[key] = val
    except OSError:
        pass
    print(f"[modal] shipping {len(found)}/{len(_MODAL_ENV_KEYS)} env keys (names only, never values)")
    return [modal.Secret.from_dict(found)]


@app.function(
    image=image,
    volumes={"/root/cache": cache_volume},
    secrets=_modal_secrets(),
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


@app.function(
    image=image,
    volumes={"/root/research": research_volume},
    secrets=_modal_secrets(),
    timeout=12 * 3600,
    # The orchestrator only spawns/awaits/persists; it needs no CPU itself.
    cpu=0.25,
    memory=1024,
)
def run_batch_remote(batch_json: str) -> str:
    """Server-side batch orchestrator with durable, resumable results.

    Runs entirely inside Modal's network: candidate calls are spawned and
    awaited here, so a flaky local connection cannot lose completed results.
    After every completed candidate the partial result file is rewritten and
    committed to the research volume; a restart of this function resumes from
    the committed partial state and skips already-finished candidates.
    """
    import concurrent.futures
    import json
    import sys
    from pathlib import Path

    sys.path.insert(0, "/root/src")
    sys.path.insert(0, "/root/scripts")

    batch = json.loads(batch_json)
    output_stem = str(batch["output_stem"])
    windows_payload = batch["windows"]
    args_payload = batch["args"]
    candidates_payload = batch["candidates"]
    concurrency = max(1, int(batch.get("concurrency") or 12))

    partial_path, final_path = _batch_result_paths(output_stem)
    partial_path.parent.mkdir(parents=True, exist_ok=True)

    ordered: dict[int, str] = {}
    if partial_path.exists():
        try:
            prior = json.loads(partial_path.read_text())
            for key, value in (prior.get("completed") or {}).items():
                ordered[int(key)] = value
            print(f"[batch] resuming: {len(ordered)} previously completed candidates", flush=True)
        except Exception:
            ordered = {}
    research_volume.commit()

    def _run_one(index: int, candidate: dict) -> str:
        call = run_candidate_remote.spawn(
            json.dumps({"cid": candidate["cid"], "config": candidate["config"], "deltas": candidate["deltas"]}),
            json.dumps(windows_payload),
            json.dumps(args_payload),
            f"{output_stem}_{candidate['cid']}",
        )
        return call.get()

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        futs = {
            pool.submit(_run_one, i, c): i
            for i, c in enumerate(candidates_payload)
            if i not in ordered
        }
        for fut in concurrent.futures.as_completed(futs):
            index = futs[fut]
            try:
                ordered[index] = fut.result()
            except Exception as exc:  # keep one bad candidate from killing the batch
                ordered[index] = json.dumps(
                    {
                        "ok": False,
                        "cid": candidates_payload[index]["cid"],
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
            partial_path.write_text(
                json.dumps(
                    {"output_stem": output_stem, "completed": {str(k): v for k, v in sorted(ordered.items())}},
                    sort_keys=True,
                )
            )
            research_volume.commit()

    results = [json.loads(ordered[i]) for i in range(len(candidates_payload))]
    final_path.write_text(json.dumps(results))
    research_volume.commit()
    return json.dumps(
        {"ok": True, "results_path": str(final_path), "n_results": len(results)}
    )


@app.function(
    image=image,
    volumes={"/root/research": research_volume},
)
def fetch_results_remote(remote_path: str) -> str:
    """Read one committed file from the research volume; '' means missing."""
    from pathlib import Path

    if not remote_path.startswith("/") or ".." in remote_path:
        raise ValueError(f"unsafe remote path: {remote_path}")
    path = Path("/root/research") / remote_path.lstrip("/")
    if not path.exists():
        return ""
    return path.read_text()


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
    as a subprocess, and read back the results file. If the CLI channel fails
    or hangs, the durable volume copy written by run_batch_remote is
    recovered with `modal volume get`.
    """
    import json
    import os
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
        "concurrency": int(os.environ.get("MODAL_TUNER_CONCURRENCY", "12")),
        "candidates": [
            {"cid": c.cid, "config": c.config, "deltas": c.deltas} for c in candidates
        ],
    }
    batch_path.write_text(json.dumps(batch))

    modal_bin = str(Path(sys.executable).with_name("modal"))
    cmd = [modal_bin, "run", str(Path(__file__).resolve())]
    env = {**os.environ, "MODAL_BATCH_JSON": str(batch_path), "MODAL_OUT_JSON": str(results_path)}
    completed = subprocess.run(cmd, capture_output=True, text=True, env=env)
    results = None
    if completed.returncode == 0 and results_path.exists():
        try:
            results = json.loads(results_path.read_text())
        except Exception:
            results = None
    if results is None:
        results = _recover_results_from_volume(modal_bin, output_stem, results_path)
    if results is None:
        raise RuntimeError(
            f"modal run failed and volume recovery found no results "
            f"(exit {completed.returncode}):\n{completed.stdout[-2000:]}\n{completed.stderr[-2000:]}"
        )
    return results


def _recover_results_from_volume(
    modal_bin: str,
    output_stem: str,
    results_path: Path,
) -> list[dict[str, Any]] | None:
    """Recover the durable batch results via the `modal volume get` CLI."""
    import json
    import os
    import subprocess
    import tempfile

    remote_rel = f"/{BATCH_RESULTS_DIR}/{output_stem}_modal_results.json"
    env = dict(os.environ)
    env.setdefault("MODAL_PROFILE", "infi")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            completed = subprocess.run(
                [modal_bin, "volume", "get", "ai-scanner-research", remote_rel, tmp],
                capture_output=True,
                text=True,
                env=env,
                timeout=900,
            )
            if completed.returncode != 0:
                return None
            hits = sorted(Path(tmp).rglob(Path(remote_rel).name))
            if not hits:
                return None
            payload = hits[0].read_text()
        results_path.write_text(payload)
        return json.loads(payload)
    except Exception:
        return None


@app.local_entrypoint()
def main() -> None:
    """Entry point executed by `modal run` (local entrypoint in CLI channel).

    Paths arrive via environment variables because modal run's own CLI
    parser reserves option names for function parameters. The batch itself
    is orchestrated server-side; this entrypoint only triggers it and copies
    the durable results file back to the local results path.
    """
    import json
    import os
    from pathlib import Path

    batch = json.loads(Path(os.environ["MODAL_BATCH_JSON"]).read_text())
    out_path = Path(os.environ["MODAL_OUT_JSON"])

    ack = json.loads(run_batch_remote.remote(json.dumps(batch)))
    if not ack.get("ok"):
        raise RuntimeError(f"batch orchestration failed: {ack}")
    remote_rel = "/" + ack["results_path"].split("/root/research/", 1)[1]
    content = fetch_results_remote.remote(remote_rel)
    if not content:
        raise RuntimeError(f"batch results missing on volume: {remote_rel}")
    out_path.write_text(content)


if __name__ == "__main__":
    main()
