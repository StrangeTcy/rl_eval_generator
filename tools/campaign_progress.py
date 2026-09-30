"""Durable, metadata-only progress snapshots for campaign observers."""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROGRESS_FILE = "campaign_progress.json"


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _safe_fields(fields: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in fields.items()
        if value is None or isinstance(value, (str, int, float, bool))
    }


def write_progress(output_dir: Path, **fields: Any) -> None:
    """Atomically replace the observer snapshot; never affect campaign work."""
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / PROGRESS_FILE
        payload = {**_safe_fields(fields), "updated_at": utc_now()}
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    except (OSError, TypeError, ValueError):
        # Observability must not affect experiment execution.
        return


def read_progress(output_dir: Path) -> dict[str, Any]:
    try:
        value = json.loads((output_dir / PROGRESS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}
