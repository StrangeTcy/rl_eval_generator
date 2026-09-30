"""Fail-open, resumable campaign telemetry.

This module deliberately contains no experiment semantics.  It exports only
sanitized controller progress to Weights & Biases when ``WANDB_API_KEY`` is
available.  A missing SDK, invalid key, blocked network, full queue, or W&B
service failure must never change campaign state or delay its worker.
"""
from __future__ import annotations

import atexit
import hashlib
import json
import os
import queue
import threading
import time
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any


_STATE_FILE = "campaign_telemetry.json"
_QUEUE_SIZE = 256
_instances: dict[Path, "CampaignTelemetry"] = {}
_instances_lock = threading.Lock()


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _scalar_payload(values: dict[str, Any]) -> dict[str, Any]:
    """Keep telemetry metadata-only and safe for an external service."""
    safe: dict[str, Any] = {}
    for key, value in values.items():
        if value is None or isinstance(value, (str, int, float, bool)):
            safe[str(key)] = value
    return safe


class _Heartbeat(AbstractContextManager["_Heartbeat"]):
    def __init__(self, telemetry: "CampaignTelemetry", fields: dict[str, Any], interval: float):
        self._telemetry = telemetry
        self._fields = _scalar_payload(fields)
        self._interval = max(5.0, float(interval))
        self._started = time.monotonic()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "_Heartbeat":
        if self._telemetry.enabled:
            self._thread = threading.Thread(target=self._run, name="campaign-telemetry-heartbeat", daemon=True)
            self._thread.start()
        return self

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            self._telemetry.log(
                event="heartbeat",
                elapsed_seconds=round(time.monotonic() - self._started, 1),
                **self._fields,
            )

    def __exit__(self, *_args: object) -> None:
        self._stop.set()
        # Never wait for an external telemetry service on a campaign path.
        if self._thread is not None:
            self._thread.join(timeout=0.05)
        self._telemetry.log(
            event="finished",
            elapsed_seconds=round(time.monotonic() - self._started, 1),
            **self._fields,
        )


class CampaignTelemetry:
    """A bounded, daemon-thread W&B client with a durable run identity."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.enabled = bool(os.environ.get("WANDB_API_KEY"))
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=_QUEUE_SIZE)
        self._disabled = not self.enabled
        self._worker: threading.Thread | None = None
        self.run_id = self._load_or_create_run_id()
        if self.enabled:
            self._worker = threading.Thread(target=self._run, name="campaign-telemetry", daemon=True)
            self._worker.start()

    def _load_or_create_run_id(self) -> str:
        path = self.output_dir / _STATE_FILE
        existing = _read_json(path)
        run_id = existing.get("wandb_run_id") if existing else None
        if isinstance(run_id, str) and run_id:
            return run_id
        ref = ""
        try:
            ref = (self.output_dir / "campaign_ref.txt").read_text(encoding="utf-8").strip()
        except OSError:
            pass
        intent = _read_json(self.output_dir / "campaign_intent.json") or _read_json(
            self.output_dir / "campaign_bootstrap.json"
        ) or {}
        material = json.dumps({"ref": ref, "intent": intent}, sort_keys=True, separators=(",", ":"))
        run_id = "atria-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
        try:
            _write_json_atomic(path, {"schema_version": 1, "wandb_run_id": run_id})
        except OSError:
            pass
        return run_id

    def _run(self) -> None:
        try:
            import wandb  # type: ignore[import-not-found]

            settings = wandb.Settings(init_timeout=10, _disable_stats=True)
            init_kwargs: dict[str, Any] = {
                "project": os.environ.get("WANDB_PROJECT", "rl-eval-generator"),
                "name": self.run_id,
                "id": self.run_id,
                "resume": "allow",
                "job_type": "campaign-telemetry",
                "settings": settings,
            }
            entity = os.environ.get("WANDB_ENTITY")
            if entity:
                init_kwargs["entity"] = entity
            run = wandb.init(**init_kwargs)
        except Exception:
            self._disabled = True
            return

        try:
            while True:
                item = self._queue.get()
                if item is None:
                    break
                try:
                    run.log(item)
                except Exception:
                    # The campaign must keep running if one telemetry event is
                    # rejected or the service becomes unavailable.
                    self._disabled = True
                    break
        finally:
            try:
                run.finish(exit_code=0)
            except Exception:
                pass

    def log(self, **fields: Any) -> None:
        if self._disabled:
            return
        payload = _scalar_payload(fields)
        payload.setdefault("telemetry/run_id", self.run_id)
        payload.setdefault("telemetry/queued_at", round(time.time(), 3))
        try:
            self._queue.put_nowait(payload)
        except queue.Full:
            # Drop telemetry rather than block or alter evaluation timing.
            return

    def heartbeat(self, *, interval_seconds: float = 60.0, **fields: Any) -> _Heartbeat:
        return _Heartbeat(self, fields, interval_seconds)

    def close(self) -> None:
        if self._disabled:
            return
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            return


def get_campaign_telemetry(output_dir: Path) -> CampaignTelemetry:
    """Return one process-local telemetry object per persisted campaign path."""
    resolved = output_dir.resolve()
    with _instances_lock:
        instance = _instances.get(resolved)
        if instance is None:
            instance = CampaignTelemetry(resolved)
            _instances[resolved] = instance
        return instance


@atexit.register
def _close_instances() -> None:
    for telemetry in list(_instances.values()):
        telemetry.close()
