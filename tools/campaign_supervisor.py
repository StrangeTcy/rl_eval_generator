"""Supervisor decision for scheduled atria-campaign ticks.

The workflow's decision step stages the latest ``atria-campaign-state-*``
artifact and asks :func:`decide_tick` what this tick should do.  The same
function is exercised provider-free by ``tests/test_campaign_tools.py``,
so the tick policy is tested rather than embedded untested in YAML.

The workflow fetches this module from the ref recorded in
``campaign_ref.txt`` — the same pinned code whose wrapper wrote the staged
state — so the marker schema and its reader stay versioned together.  A
ref that predates this module gets an operator review from the workflow,
never a restart loop.

Decision contract (the incident that produced it: a blocked gate row was
banked and replayed by every tick for 13 hours):

* ``wrapper_failed.json`` present — the previous dispatch ended
  non-resumably (wrapper exception, generation preflight failure, a gate
  case blocked twice, missing credentials, Docker down, substantive
  compatibility failure).  The wrapper clears the marker at the start of
  every run, so a marker that survives into a tick means one automatic
  restart already happened: stand down for an operator.
* no ``suite_checkpoint.json`` — the dispatch died before any checkpoint
  (typically mid-gate).  With a recorded ref this is RESUMABLE: restart
  from the ref; the gate re-validates only failed rows and keeps the
  passed ones.  Without a ref there is nothing to restart from.
* ``suite_checkpoint.json`` present — completed campaigns and
  non-resumable pauses (budget ceilings, floor effects, infrastructure)
  are operator territory; resumable pauses (provider outage, wall
  budget, provider-side compatibility) resume after a backoff window.

Returned modes: ``fresh`` (dispatch the recorded ref), ``resume``
(continue from the checkpoint), ``none`` (do nothing this tick).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

# Pause reasons a scheduled tick may resume on its own.  Everything else —
# budget ceilings, floor effects, infrastructure — stops for the operator;
# the supervisor never raises a ceiling.
RESUMABLE_PAUSE_REASONS = {
    "provider_error",
    "max_wall_seconds",
    "provider_infrastructure_error_compatibility",
}

# A freshly paused campaign is not retried immediately: give the provider
# window (or the previous job's slot) time to clear first.
RESUME_BACKOFF_SECONDS = 1200


def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def _read_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def decide_tick(state_dir) -> dict:
    """Decide what a scheduled tick does with a staged campaign state.

    ``state_dir`` is the directory the workflow unzipped the latest state
    artifact into.  Returns ``{"mode": ..., "reason": ...}`` plus, for
    ``fresh``/``resume`` modes, the ``ref`` to run.  Pure and side-effect
    free: no network, no provider, no filesystem writes.
    """
    state_dir = os.fspath(state_dir)

    # A terminal marker that survived into this tick: the wrapper already
    # had its one automatic restart (markers are cleared at run start).
    # A repeat non-resumable failure is an operator decision.
    marker = _read_json(os.path.join(state_dir, "wrapper_failed.json"))
    if marker is not None:
        reason = str(marker.get("pause_reason") or "unknown")
        return {
            "mode": "none",
            "reason": f"operator stop: {reason} "
                      f"(wrapper failed; fix and re-dispatch manually)",
        }

    checkpoint_path = os.path.join(state_dir, "suite_checkpoint.json")
    recorded_ref = _read_text(os.path.join(state_dir, "campaign_ref.txt"))
    checkpoint = _read_json(checkpoint_path)

    if checkpoint is None:
        # Interrupted before the first checkpoint (typically mid-gate).
        # Resumable: the pinned code re-validates only failed rows and
        # keeps the banked passed ones, so a restart makes progress.
        if recorded_ref:
            return {
                "mode": "fresh",
                "ref": recorded_ref,
                "reason": "restarting after pre-checkpoint death",
            }
        return {
            "mode": "none",
            "reason": "state artifact has no checkpoint and no recorded ref",
        }

    if not checkpoint.get("paused"):
        return {"mode": "none", "reason": "campaign already completed"}

    pause_reason = str(checkpoint.get("pause_reason") or "")
    if pause_reason not in RESUMABLE_PAUSE_REASONS:
        return {
            "mode": "none",
            "reason": f"operator pause: {pause_reason} "
                      f"(supervisor never raises ceilings)",
        }

    updated_at = str(checkpoint.get("updated_at") or "")
    if updated_at:
        try:
            paused_at = datetime.fromisoformat(
                updated_at.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - paused_at).total_seconds()
        except ValueError:
            age = None
        if age is not None and age < RESUME_BACKOFF_SECONDS:
            return {
                "mode": "none",
                "reason": f"backoff: paused {int(age)}s ago, "
                          f"retry in {int(RESUME_BACKOFF_SECONDS - age)}s",
            }

    ref = str(((checkpoint.get("run") or {}).get("manifest_commit"))
              or recorded_ref or "")
    if not ref:
        return {
            "mode": "none",
            "reason": "resumable pause but no code ref recorded",
        }
    return {
        "mode": "resume",
        "ref": ref,
        "reason": f"resuming after {pause_reason}",
    }
