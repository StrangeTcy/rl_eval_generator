"""Provider-free continuation policy for pinned covering campaigns.

The scheduled workflow restores the latest provider-specific state artifact
and calls :func:`decide_tick`. This policy deliberately treats the artifact asthe continuation contract: it identifies both the pinned code ref and the mode
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

# Pause reasons a scheduled tick may resume on its own. Budget ceilings, floor
# effects, invalid gates, and an exhausted infrastructure-retry ledger stop for
# an operator; the supervisor never raises a ceiling.
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

# A freshly paused campaign is not retried immediately: give the provider
# window (or the previous job's slot) time to clear first.
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


# The deterministic refusals `tools/run_suite._load_checkpoint` raises against the state it was handed.
# A marker naming one of them is a *configuration* stop, not a verdict about the campaign, and it is the
# only class worth second-guessing here: the operator cannot acknowledge it away, and a leg that dies on
# it re-uploads the marker, which is how Mercury spent five legs at 190 / 416 (runs 24, 25, 27, 28, 29).
STATE_CONTRACT_MARKERS = (
    "checkpoint metadata mismatch",
    "manifest case count changed",
    "gate coverage is incomplete",
)


# The checkout this file was fetched from, as a name rather than a `__file__` arithmetic: a test of the
# ancestry verdict has to be able to point it at a repository it made itself, because CI checks this out
# with `fetch-depth: 1` and an assertion about two named commits of this branch is then a claim about the
# clone, not about the rule. That is exactly how tests/test_campaign_supervisor.py went red in CI and green
# on a desk (16:0x UTC, 2026-10-13).
GIT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _is_ancestor(older: str, newer: str) -> bool:
    """Reachability test for two shas, answered by the checkout this file was fetched from.

    Duplicated from `tools/run_suite.py` on purpose: the launcher fetches *this file alone* and executes
    it provider-free (`gh api contents/tools/campaign_supervisor.py?ref=...`), so an import from the
    package would not resolve on a runner. Fails closed on any git trouble, including a shallow clone.
    """
    import subprocess

    root = GIT_ROOT

    def usable(value: str) -> bool:
        return 7 <= len(value) <= 40 and all(char in "0123456789abcdef" for char in value)

    if not (usable(older) and usable(newer)):
        return False
    for value in (older, newer):
        if subprocess.run(["git", "-C", root, "cat-file", "-e", f"{value}^{{commit}}"],
                          capture_output=True, text=True).returncode != 0:
            return False
    return subprocess.run(["git", "-C", root, "merge-base", "--is-ancestor", older, newer],
                          capture_output=True, text=True).returncode == 0


def _stale_operator_gate(root: str, marker: dict[str, Any]) -> str:
    """A sentence about whether this code could still produce the recorded refusal. Empty if unknown.

    The refusal is re-derived from the staged files rather than trusted from a chat log: the two stamps
    the marker names are read back out of `suite_checkpoint.json` and `suite_manifest.json`, and the
    verdict is one of three things the operator can act on without taking anyone's word for it.
    """
    detail = " ".join(str(marker.get("detail") or "").split())
    if not any(needle in detail for needle in STATE_CONTRACT_MARKERS):
        return ""
    checkpoint = _read_json(os.path.join(root, "suite_checkpoint.json")) or {}
    manifest = _read_json(os.path.join(root, "suite_manifest.json")) or {}
    ledger = str(((checkpoint.get("run") or {}).get("manifest_commit")) or "")
    stamped = str(((manifest.get("repository") or {}).get("commit")) or "")
    if not ledger or not stamped:
        return "state-contract gate: the stamps it names are not both readable from the artifact"
    if ledger == stamped:
        return (
            f"the recorded cause cannot recur here: the artifact's own stamps now agree ({ledger[:7]}), "
            "so only the acknowledgement is missing - `clear_wrapper_stop` alone is sufficient and "
            "`rebase_onto_ref` is not needed"
        )
    if _is_ancestor(ledger, stamped):
        return (
            f"the artifact still disagrees with itself (checkpoint {ledger[:7]}, manifest {stamped[:7]}) "
            "but that is a fast-forward of one lineage, which this code carries with the move recorded; "
            "so `clear_wrapper_stop` alone resumes it, and `rebase_onto_ref` is only needed to run newer "
            "code than the pinned ref of this decision"
        )
    return (
        f"the gate stands on the state, not on the acknowledgement: checkpoint {ledger[:7]} is not an "
        f"ancestor of manifest {stamped[:7]}, so no leg resumes until the artifact itself is repaired"
    )


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


# Pause reasons that mean "the operator's money ran out", not "the measurement is
# invalid". They are terminal for the cron loop by default - see
# CEILING_FIELDS in tools/run_suite.py - and a dispatched ceiling override that
# actually exceeds the value the campaign stopped at is the only thing that lifts them.
CEILING_PAUSE_REASONS = ("max_api_calls", "max_tokens_total", "max_http_attempts")


def _normalised_override(limits_override: object) -> dict[str, int]:
    """Accept ``{"max_api_calls": 300}`` or ``["max_api_calls=300"]``.

    The launcher builds this from workflow inputs, where everything arrives as a
    string; anything unparseable is dropped rather than guessed, because a ceiling the
    supervisor cannot read cannot be compared against the recorded one.
    """
    parsed: dict[str, int] = {}
    if isinstance(limits_override, dict):
        items = list(limits_override.items())
    elif isinstance(limits_override, (list, tuple, set)):
        items = []
        for entry in limits_override or ():
            key, _, raw = str(entry).partition("=")
            items.append((key.strip(), raw.strip()))
    else:
        items = []
    for key, raw in items:
        if str(key) not in CEILING_PAUSE_REASONS:
            continue
        try:
            parsed[str(key)] = int(str(raw).strip())
        except (TypeError, ValueError):
            continue
    return parsed


def _ceiling_was_raised(
    pause_reason: str,
    limits_override: object,
    checkpoint: dict[str, Any],
) -> str | None:
    """Return a reason when this tick is authorised to bill past a spent ceiling."""
    if pause_reason not in CEILING_PAUSE_REASONS:
        return None
    override = _normalised_override(limits_override).get(pause_reason)
    if override is None:
        return None
    recorded = (checkpoint.get("run") or {}).get(pause_reason)
    if not isinstance(recorded, int):
        # Nothing to compare against: refusing is the honest answer, because the
        # alternative is resuming on the assumption that the ceiling still has room.
        return None
    if override <= recorded:
        return None
    return f"{pause_reason} raised by dispatcher {recorded} -> {override}"


def decide_tick(
    state_dir: str | os.PathLike[str],
    *,
    expected_provider: str = "atria",
    limits_override: object = None,
) -> dict[str, str]:
    """Decide whether a scheduled tick may continue staged campaign state.

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
    if intent.get("provider") != expected_provider:
        return _decision(
            mode="none",
            execution_mode="",
            ref="",
            reason=(
                "state artifact intent provider does not match expected "
                f"target {expected_provider!r}"
            ),
        )

    # T1 makes paid calls outside the episode scheduler and currently has no
    # per-trial resume ledger. An interrupted run is therefore an operator
    # decision: automatic replay could duplicate any already-completed calls.
    t1_started = os.path.isfile(os.path.join(root, "t1_started.json"))
    t1_report = os.path.isfile(os.path.join(root, "t1_same_fact_presentation.json"))
    if t1_started and not t1_report:
        return _decision(
            mode="none",
            execution_mode="",
            ref="",
            reason=(
                "operator stop: T1 same_fact_presentation was interrupted before "
                "its final report; no automatic provider-call replay"
            ),
        )

    # A terminal marker survives only when the wrapper made a deliberate,
    # non-resumable decision. Never retry it on cron.
    marker = _read_json(os.path.join(root, "wrapper_failed.json"))
    if marker is not None:
        reason = str(marker.get("pause_reason") or "unknown")
        # The decision stays a refusal - a scheduled tick must not talk itself past a terminal marker,
        # and this function has no idea who is reading it - but the *reason* now says what the code
        # could verify, so the answer comes off the run page instead of from somebody's guess.
        note = _stale_operator_gate(root, marker)
        return _decision(
            mode="none",
            execution_mode="",
            ref="",
            reason="operator stop: " + reason + " (wrapper recorded a terminal failure)"
            + ((" - " + note) if note else ""),
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
    ceiling_resume = _ceiling_was_raised(pause_reason, limits_override, checkpoint)
    if pause_reason not in RESUMABLE_PAUSE_REASONS and not ceiling_resume:
        return _decision(
            mode="none",
            execution_mode="",
            ref="",
            reason=(
                f"operator pause: {pause_reason} (supervisor never raises ceilings; "
                f"dispatch {pause_reason}=<a number above the spent value> to authorise "
                "more spend against this campaign)"
            ),
        )
    backoff_reason = _is_backoff_active(checkpoint)
    if backoff_reason:
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
    if ceiling_resume:
        reason = f"resuming after {pause_reason}: {ceiling_resume}"
    if checkpoint_ref and checkpoint_ref != recorded_ref:
        reason = (
            f"resuming after {pause_reason} pinned to checkpoint commit "
            f"{checkpoint_ref[:12]} (campaign_ref recorded {recorded_ref})"
        )
    return _decision(
        mode="resume",
        execution_mode=execution_mode,
        ref=resume_ref,
        reason=reason,
    )
