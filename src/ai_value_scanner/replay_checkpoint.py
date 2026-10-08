from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, Callable


CHECKPOINT_VERSION = 1


def path_sha256(path: str | Path | None) -> str | None:
    """Stable SHA256 for one file or a directory tree.

    Directory hashing includes each relative path and file content in sorted
    order so a checkpoint cannot be resumed against a silently changed frozen
    watchlist history.
    """
    if path is None:
        return None
    p = Path(path)
    if not p.exists():
        return None
    digest = hashlib.sha256()
    if p.is_file():
        digest.update(p.read_bytes())
        return digest.hexdigest()

    for child in sorted(x for x in p.rglob("*") if x.is_file()):
        rel = child.relative_to(p).as_posix().encode("utf-8")
        digest.update(len(rel).to_bytes(8, "big"))
        digest.update(rel)
        with child.open("rb") as handle:
            while True:
                block = handle.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
    return digest.hexdigest()


def _json_default(value: Any) -> Any:
    item = getattr(value, "item", None)
    if callable(item):
        return item()
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            default=_json_default,
        )
        + "\n"
    )
    os.replace(tmp, path)


class SignalDateCheckpointStore:
    """Small, deterministic per-signal-date checkpoint store.

    A manifest mismatch is a hard failure in resume mode. This prevents a
    partially completed replay from being reused after config/watchlist/date
    changes merely because the checkpoint directory name happened to match.
    """

    def __init__(
        self,
        root: str | Path,
        manifest: dict[str, Any],
        *,
        resume: bool,
        commit_callback: Callable[[], None] | None = None,
    ) -> None:
        self.root = Path(root)
        self.dates_dir = self.root / "dates"
        self.manifest_path = self.root / "manifest.json"
        self.resume = bool(resume)
        self.commit_callback = commit_callback

        normalized = {
            "checkpoint_version": CHECKPOINT_VERSION,
            **manifest,
        }
        if self.resume:
            if not self.manifest_path.exists():
                raise ValueError(
                    f"resume requested but checkpoint manifest is missing: {self.manifest_path}"
                )
            existing = json.loads(self.manifest_path.read_text())
            if existing != normalized:
                raise ValueError(
                    "checkpoint manifest mismatch; refuse to mix replay states. "
                    f"checkpoint={self.manifest_path}"
                )
        else:
            if self.dates_dir.exists():
                shutil.rmtree(self.dates_dir)
            self.root.mkdir(parents=True, exist_ok=True)
            _atomic_json_write(self.manifest_path, normalized)
            self._commit()

        self.dates_dir.mkdir(parents=True, exist_ok=True)

    def _commit(self) -> None:
        if self.commit_callback is not None:
            self.commit_callback()

    def path_for_date(self, signal_date: str) -> Path:
        return self.dates_dir / f"{signal_date}.json"

    def load(self, signal_date: str) -> dict[str, Any] | None:
        if not self.resume:
            return None
        path = self.path_for_date(signal_date)
        if not path.exists():
            return None
        payload = json.loads(path.read_text())
        if str(payload.get("signal_date")) != str(signal_date):
            raise ValueError(f"checkpoint signal_date mismatch: {path}")
        rows = payload.get("rows")
        if not isinstance(rows, list):
            raise ValueError(f"checkpoint rows must be a list: {path}")
        return payload

    def save(
        self,
        signal_date: str,
        rows: list[dict[str, Any]],
        watchlist_source: str | None,
    ) -> None:
        payload = {
            "signal_date": str(signal_date),
            "watchlist_source": watchlist_source,
            "rows": rows,
        }
        _atomic_json_write(self.path_for_date(signal_date), payload)
        self._commit()
