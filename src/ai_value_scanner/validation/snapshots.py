from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
import json

import pandas as pd


SNAPSHOT_SCHEMA_VERSION = 1


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_frame(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if "symbol" in out.columns:
        out["symbol"] = out["symbol"].astype(str)
        out = out.sort_values("symbol", kind="mergesort")
    out = out.reset_index(drop=True)
    columns = list(out.columns)
    if "symbol" in columns:
        columns = ["symbol", *sorted(c for c in columns if c != "symbol")]
    else:
        columns = sorted(columns)
    return out.loc[:, columns]


def load_feature_snapshot(path: str | Path) -> pd.DataFrame:
    """Load one frozen cross-section snapshot without touching live data.

    Object/string columns are restored from the bundle manifest so values such
    as ticker NA or a SIC with leading zeroes are not reinterpreted by the
    CSV parser.
    """
    snapshot_path = Path(path)
    dtype_map: dict[str, str] = {}
    manifest_path = snapshot_path.parent / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        record = next(
            (
                item
                for item in manifest.get("snapshots", [])
                if item.get("path") == snapshot_path.name
            ),
            None,
        )
        if record is not None:
            dtype_map = {
                str(column): "object"
                for column in record.get("object_columns", [])
            }
    return pd.read_csv(
        snapshot_path,
        low_memory=False,
        keep_default_na=False,
        na_values=[""],
        dtype=dtype_map or None,
    )


def load_snapshot_manifest(root: str | Path) -> dict[str, Any]:
    return json.loads((Path(root) / "manifest.json").read_text(encoding="utf-8"))


def compare_snapshot_manifests(
    baseline: dict[str, Any],
    current: dict[str, Any],
) -> list[str]:
    """Return deterministic snapshot-contract differences."""
    diffs: list[str] = []
    for key in ("schema_version", "metadata", "bundle_sha256"):
        if baseline.get(key) != current.get(key):
            diffs.append(
                f"{key}: baseline={baseline.get(key)!r} current={current.get(key)!r}"
            )

    baseline_records = {
        record["key"]: record for record in baseline.get("snapshots", [])
    }
    current_records = {
        record["key"]: record for record in current.get("snapshots", [])
    }
    if set(baseline_records) != set(current_records):
        diffs.append(
            "snapshot keys differ: "
            f"baseline={sorted(baseline_records)} current={sorted(current_records)}"
        )
        return diffs

    for key in sorted(baseline_records):
        left = baseline_records[key]
        right = current_records[key]
        for field_name in ("sha256", "rows", "columns", "object_columns"):
            if left.get(field_name) != right.get(field_name):
                diffs.append(
                    f"snapshots[{key}].{field_name}: "
                    f"baseline={left.get(field_name)!r} "
                    f"current={right.get(field_name)!r}"
                )
    return diffs


@dataclass
class FeatureSnapshotWriter:
    """Write deterministic pre-strategy cross sections for fast offline gates."""

    root: Path
    metadata: dict[str, Any]
    records: list[dict[str, Any]] = field(default_factory=list)

    def __init__(self, root: str | Path, metadata: dict[str, Any] | None = None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.metadata = dict(metadata or {})
        self.records = []

    def write(
        self,
        *,
        style: str,
        scenario: str,
        asof: pd.Timestamp,
        frame: pd.DataFrame,
    ) -> dict[str, Any]:
        normalized_asof = pd.Timestamp(asof)
        if normalized_asof.tzinfo is None:
            normalized_asof = normalized_asof.tz_localize("UTC")
        else:
            normalized_asof = normalized_asof.tz_convert("UTC")
        date_token = normalized_asof.date().isoformat()
        safe_style = str(style or "unknown").replace("/", "_")
        safe_scenario = str(scenario or "base").replace("/", "_")
        filename = f"{safe_style}__{safe_scenario}__{date_token}.csv"
        path = self.root / filename

        canonical = _canonical_frame(frame)
        canonical.to_csv(
            path,
            index=False,
            na_rep="",
            float_format="%.17g",
            lineterminator="\n",
        )
        record = {
            "key": f"{safe_style}|{safe_scenario}|{date_token}",
            "path": filename,
            "style": safe_style,
            "scenario": safe_scenario,
            "asof": date_token,
            "rows": int(len(canonical)),
            "columns": list(canonical.columns),
            "object_columns": [
                str(column)
                for column in canonical.columns
                if pd.api.types.is_object_dtype(canonical[column].dtype)
                or pd.api.types.is_string_dtype(canonical[column].dtype)
            ],
            "sha256": _sha256_file(path),
            "bytes": int(path.stat().st_size),
        }
        self.records = [r for r in self.records if r["key"] != record["key"]]
        self.records.append(record)
        self.records.sort(key=lambda r: r["key"])
        return record

    def finalize(self) -> Path:
        records = sorted(self.records, key=lambda record: record["key"])
        aggregate = sha256(
            "\n".join(
                f"{record['key']}:{record['sha256']}" for record in records
            ).encode("utf-8")
        ).hexdigest()
        manifest = {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "purpose": "pre-strategy frozen feature snapshots for fast refactor gates",
            "metadata": self.metadata,
            "snapshot_count": len(records),
            "bundle_sha256": aggregate,
            "snapshots": records,
        }
        path = self.root / "manifest.json"
        path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path
