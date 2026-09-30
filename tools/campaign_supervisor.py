"""Provider-free continuation policy for the Atria covering campaign.

The scheduled workflow restores the latest ``atria-campaign-state-*`` artifact
and calls :func:`decide_tick`.  This policy deliberately treats the artifact as
the continuation contract: it identifies both the pinned code ref and the mode
that the original manual dispatch authorized.

A campaign may take more than GitHub Actions' per-job limit because gate rows
and episode checkpoints are persisted atomically.  A scheduled run is allowed
to continue only an explicit ``campaign_intent.json`` written by the wrapper.
It never guesses a mode from a profile, a secret, or a missing checkpoint.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

# Pause reasons the schedule or an explicit manual Continue may resume.
# Budget ceilings, floor effects, invalid gates, and an exhausted
# infrastructure-retry ledger stop for an operator; manual Continue never
# raises a ceiling.
RESUMABLE_PAUSE_REASONS = {
    "provider_error",
    "max_wall_seconds",
    "provider_infrastructure_error_compatibility",
    # run_suite persists an attempt ledger and switches to the distinct,
    # non-resumable infrastructure_error_retries_exhausted after the bounded
    # automatic retry count is consumed.
    "infrastructure_error",
    "docker_unavailable",
    "wrapper_transient_error",
}

# Scheduled ticks give a freshly paused campaign 20 minutes to let a provider
# window or the previous job's slot clear. An explicit manual Continue may
# override only this cooldown; all terminal and budget stops remain in force.
RESUME_BACKOFF_SECONDS = 1200
VALID_EXECUTION_MODES = {"gates_only", "paid"}


def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def _read_json(path: str) -> dict[str, Any] | None:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _decision(
    *, mode: str, execution_mode: str, ref: str, reason: str
) -> dict[str, str]:
    result = {"mode": mode, "reason": reason}
    if mode != "none":
        result["ref"] = ref
        result["execution_mode"] = execution_mode
    return result


def _is_backoff_active(checkpoint: dict[str, Any]) -> str | None:
    updated_at = str(checkpoint.get("updated_at") or "")
    if not updated_at:
        return None
    try:
        paused_at = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - paused_at).total_seconds()
    except ValueError:
        return None
    if age < RESUME_BACKOFF_SECONDS:
        return f"backoff: paused {int(age)}s ago, retry in {int(RESUME_BACKOFF_SECONDS - age)}s"
    return None


def decide_tick(
    state_dir: str | os.PathLike[str], *, manual_continue: bool = False
) -> dict[str, str]:
    """Decide whether a schedule tick or explicit manual Continue may resume.

    ``manual_continue`` is supplied only for a checked workflow-dispatch
    checkbox. It bypasses the 20-minute transient cooldown, not campaign
    intent validation, terminal markers, pause-reason allowlists, budgets, or
    concurrency checks in the workflow.

    Returns ``{"mode": "none"}`` for a terminal or untrusted state. A resume
    decision also contains the exact recorded ``ref`` and either ``gates_only``
    or ``paid`` as ``execution_mode``. The function is pure: no network,
    provider, or write side effects.
    """
    root = os.fspath(state_dir)
    recorded_ref = _read_text(os.path.join(root, "campaign_ref.txt"))
    intent = _read_json(os.path.join(root, "campaign_intent.json"))
    if intent is None:
        # Written by the workflow before checkout/dependency setup. It carries
        # only the explicit manual mode and pinned ref; the controller replaces
        # it with the manifest-bound campaign_intent once setup succeeds.
        intent = _read_json(os.path.join(root, "campaign_bootstrap.json"))
    if not recorded_ref:
        return _decision(
            mode="none",
            execution_mode="",
            ref="",
            reason="state artifact has no recorded code ref",
        )
    if intent is None:
        return _decision(
            mode="none",
            execution_mode="",
            ref="",
            reason="state artifact has no campaign intent; scheduled continuation is refused",
        )
    execution_mode = str(intent.get("execution_mode") or "")
    if execution_mode not in VALID_EXECUTION_MODES:
        return _decision(
            mode="none",
            execution_mode="",
            ref="",
            reason="state artifact has an invalid campaign execution mode",
        )
    if intent.get("provider") != "atria":
        return _decision(
            mode="none",
            execution_mode="",
            ref="",
            reason="state artifact intent is not an Atria campaign",
        )

    # A terminal marker survives only when the wrapper made a deliberate,
    # non-resumable decision. Never retry it on cron.
    marker = _read_json(os.path.join(root, "wrapper_failed.json"))
    if marker is not None:
        reason = str(marker.get("pause_reason") or "unknown")
        return _decision(
            mode="none",
            execution_mode="",
            ref="",
            reason=f"operator stop: {reason} (wrapper recorded a terminal failure)",
        )

    report = _read_json(os.path.join(root, "campaign_report.json")) or {}
    report_status = str(report.get("status") or "")
    report_reason = str(report.get("pause_reason") or "")
    if report_status in {"completed", "gate_passed"}:
        return _decision(
            mode="none",
            execution_mode="",
            ref="",
            reason=f"campaign already {report_status}",
        )

    checkpoint = _read_json(os.path.join(root, "suite_checkpoint.json"))
    if checkpoint is None:
        # Intent is committed before the exact-instance gate.  If the runner
        # dies before its first checkpoint (or between atomically banked gate
        # rows), the next scheduled job may safely redo only provider-free
        # work.  This is not permission inferred from a profile: the manual
        # dispatch has already persisted its exact mode in campaign_intent.
        partial_exists = os.path.isfile(os.path.join(root, "instance_oracles_partial.json"))
        return _decision(
            mode="resume",
            execution_mode=execution_mode,
            ref=recorded_ref,
            reason=(
                "resuming provider-free gate after an interrupted partial row"
                if partial_exists
                else "restarting provider-free gate after a pre-checkpoint interruption"
            ),
        )

    if not checkpoint.get("paused"):
        execution_state = str(((checkpoint.get("run") or {}).get("execution_state")) or "")
        if execution_state == "active":
            # A result row is atomically recorded only after an episode has a
            # definitive outcome. An active marker therefore means the prior
            # worker disappeared between durable boundaries; resuming skips
            # every recorded row and retries at most its named in-flight case.
            # Pin to the checkpoint's commit, not the recorded ref string:
            # campaign_ref.txt may hold a branch name that has since moved.
            active_ref = str(((checkpoint.get("run") or {}).get("manifest_commit")) or "") or recorded_ref
            return _decision(
                mode="resume",
                execution_mode=execution_mode,
                ref=active_ref,
                reason="resuming after an interrupted active worker",
            )
        return _decision(
            mode="none",
            execution_mode="",
            ref="",
            reason="checkpoint is not paused; no scheduled continuation is needed",
        )

    pause_reason = str(checkpoint.get("pause_reason") or "")
    if pause_reason not in RESUMABLE_PAUSE_REASONS:
        return _decision(
            mode="none",
            execution_mode="",
            ref="",
            reason=f"operator pause: {pause_reason} (supervisor never raises ceilings)",
        )
    backoff_reason = _is_backoff_active(checkpoint)
    if backoff_reason and not manual_continue:
        return _decision(
            mode="none",
            execution_mode="",
            ref="",
            reason=backoff_reason,
        )

    # campaign_ref.txt records the dispatched ref STRING (a branch name or
    # the default "main"); the checkpoint's run.manifest_commit records the
    # commit SHA the controller resolved and actually executed. The two are
    # equal only when the operator dispatched a full SHA, so a strict string
    # comparison refuses every branch-name dispatch forever and the cron
    # continuation the workflow advertises never runs. Resume pinned to the
    # checkpoint's commit instead: it is the exact code that produced this
    # state, and unlike a branch name it cannot have moved since the dispatch.
    checkpoint_ref = str(((checkpoint.get("run") or {}).get("manifest_commit")) or "")
    resume_ref = checkpoint_ref or recorded_ref
    reason = f"resuming after {pause_reason}"
    if checkpoint_ref and checkpoint_ref != recorded_ref:
        reason = (
            f"resuming after {pause_reason} pinned to checkpoint commit "
            f"{checkpoint_ref[:12]} (campaign_ref recorded {recorded_ref})"
        )
    if backoff_reason and manual_continue:
        reason = f"manual Continue bypassed cooldown; {reason}"
    return _decision(
        mode="resume",
        execution_mode=execution_mode,
        ref=resume_ref,
        reason=reason,
    )
