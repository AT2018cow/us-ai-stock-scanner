"""Small shared identity checks for frozen research inputs and checkpoints."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Mapping, Any


def provenance_path(path: str | Path, root: str | Path) -> str:
    """Keep logical mount paths; external inputs retain absolute identities."""
    absolute = Path(os.path.abspath(path))
    base = Path(os.path.abspath(root))
    try:
        return str(absolute.relative_to(base))
    except ValueError:
        return str(absolute)


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_config_identity(manifest: Mapping[str, Any], config_path: str | Path) -> None:
    """Reject legacy/changed configurations before checkpoint reuse."""
    recorded = manifest.get('config_sha256')
    if not isinstance(recorded, str) or recorded != sha256_file(config_path):
        raise ValueError('configuration identity mismatch or missing config_sha256; use a new result directory')
