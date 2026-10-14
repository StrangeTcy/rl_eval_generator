#!/usr/bin/env python3
"""Ask the runner for the campaign's next leg, from the leg that just banked work.

Why this exists, measured rather than assumed: a resumable pause is only a pause if
something starts the successor. Every pairwise leg ends on the repository's ``13,43 * * * *``
cron, and on 2026-10-12 both pairwise lineages finished a leg at 14:41Z / 14:42Z in a
``max_wall_seconds`` pause with 162 / 416 and 75 / 416 rows persisted, while the cron block
was intact in the deployed ``.github/workflows/`` copies on ``main`` and both workflows
reported ``state: active``. No run was created for hours afterwards - GitHub skips and
delays schedule events, and the repository cannot see or repair that from a workflow file.
The ledgers were safe; the cadence was not, and "dispatch it again" is not a fix.

So a leg that pauses resumably requests its own successor over the REST API with the job
token. Three properties are deliberate:

* It refuses rather than spins, on the same terms the covering campaign's CHAIN already uses, so
  one repo does not grow two scheduler workarounds: a ``max_wall_seconds`` pause hands over at
  once, every other resumable pause waits 10 minutes, chaining stops after 40 legs, and a leg
  that was cancelled, that regressed its state upload, or that left a ``wrapper_failed.json``
  marker never continues. If the API cannot be read it refuses too, because "is a leg already
  running?" is exactly the question the answer is needed for.
* It never reddens a leg. Every failure path prints the reason and exits 0: a broken re-arm
  must cost one missed tick, not a red campaign and a paused ledger. The cron stays as the
  fallback, so this is additive.
* It cannot change what may bill. The dispatched inputs are ``ref`` and the launcher's own
  ``resume_previous: true`` default - never ``rebase_onto_ref``, never an execution mode. A
  re-arm resumes the lineage at its pinned commit; promoting gates-only to paid, or moving the
  code, remains an explicit human dispatch.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

# The launcher never executes this file from a checkout. It fetches the copy that matches its own workflow
# file to `$RUNNER_TEMP/campaign_rearm.py` and runs *that* (and when the fetch is empty it `cp`s the
# checkout's copy to the same place), so the directory the file sits in has no `tools` package in it and a
# bare package import is a traceback before `main` is reached:
#
#     File "campaign_rearm.py", line 44, in <module>
#       from tools.campaign_supervisor import (
#     ModuleNotFoundError: No module named 'tools'
#
# Reproduced at 17:52 UTC from the copy at 32a350d - which is the copy Mercury's legs actually run - and it
# is the whole of `campaign re-arm declined: the tool exited non-zero`, the one decline message that never
# explained itself. A step wrapped in `|| { echo ...; }` cannot tell a crash from a decision, so the crash
# was indistinguishable from a refusal for every campaign in this repository, whatever else got fixed.
for _root in {os.getcwd(), os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}:
    if _root not in sys.path:
        sys.path.insert(0, _root)

try:  # inside a tree, the supervisor stays the single source of truth
    from tools.campaign_supervisor import (  # noqa: E402
        RESUMABLE_PAUSE_REASONS,
        RESUME_BACKOFF_SECONDS,
    )
except ImportError:  # the runner's $RUNNER_TEMP, and nothing else - so the values are inlined verbatim
    RESUME_BACKOFF_SECONDS = 1200
    RESUMABLE_PAUSE_REASONS = {
        "provider_error",
        "max_wall_seconds",
        "provider_infrastructure_error_compatibility",
        "infrastructure_error",
        "docker_unavailable",
        "wrapper_transient_error",
    }

BUSY_RUN_STATUSES = {"queued", "in_progress", "requested", "waiting", "pending"}


def other_legs(runs, exclude_run: str | int | None) -> list[dict]:
    """The run list minus *this* leg.

    `decide_rearm` asks whether another leg is still running before it arms a successor, and read
    literally against the workflow's newest run that question always answers "yes" - the leg doing the
    asking is the newest run, and it is `in_progress`, because a step cannot run after its own job. So
    every self-dispatch this tool ever attempted refused with `a leg is already in_progress`, and a leg
    that declines to re-arm never arms the next one either: the chain's only continuation was a favor
    asked of a human. Mercury run 28 (38335486606, 02:08-02:11Z) is the measurement - its step 16 ran,
    the tool was reached, and the run still ended `campaign re-arm declined`.

    Excluding the current run id is the whole fix; the *other* guards are untouched, so a genuinely
    busy sibling - the previous leg, a concurrent dispatch - still refuses.
    """
    keep = str(exclude_run or "")
    if not keep:
        return list(runs or [])
    return [run for run in (runs or []) if str(run.get("id") or "") != keep]


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


DEFAULT_COOLDOWN_SECONDS = 600
IMMEDIATE_HANDOVER_REASONS = {"max_wall_seconds"}

# A pause whose *next leg costs something the campaign cannot get back*. `infrastructure_error` means the
# arena controller or judge failed on one specific case, and run_suite meters that per case with a bounded
# attempt ledger - 10 automatic retries, after which the reason becomes
# `infrastructure_error_retries_exhausted`, which nothing but an operator resumes. Every leg that reaches
# that case spends one entry whether or not it produces a row: measured on Mercury today, 1/10 in the
# 17:37 report and 2/10 in the 19:15 report, with 365/416 unchanged and 3m20s of work in between. A
# self-armed successor therefore does not recover a stalled campaign; it consumes the patience the stall
# was granted, one entry every ~23 minutes, and ends the lineage in under three hours. For this reason the
# re-arm stands down and leaves the wait to the scheduled tick, whose hours are the interval the ledger was
# sized for.
LEDGER_GOVERNING_REASONS = {"infrastructure_error"}


def cooldown_seconds_for(reason: str) -> int:
    """The *self-imposed* floor: how long the group sits idle before a successor is asked for.

    ``max_wall_seconds`` has nothing wrong with it and needs no extra courtesy wait; every other
    resumable pause is a provider or case failure that waits 10 minutes first, matching the covering
    campaign's CHAIN. What actually governs is ``RESUME_BACKOFF_SECONDS`` below: the successor leg
    runs ``campaign_supervisor.decide_tick``, which answers ``mode="none"`` to any resume attempted
    inside the supervisor's own backoff window (``tools/campaign_supervisor.py:285-292``, no bypass
    flag exists there), and a refused leg does not re-arm either - so dispatching early does not
    resume early, it just ends the chain. This is why the floor is the maximum of the two.
    """
    return 0 if str(reason) in IMMEDIATE_HANDOVER_REASONS else DEFAULT_COOLDOWN_SECONDS


def effective_floor_seconds(reason: str, override: int | None = None) -> int:
    base = cooldown_seconds_for(reason) if override is None else max(0, int(override))
    return max(base, int(RESUME_BACKOFF_SECONDS))


# The leg that just finished is the only actor that can wait for nothing: the paid work is over, and
# a successor dispatched inside the supervisor's window is refused and does not re-arm. So the wait
# happens HERE, in the last step, instead of being pushed onto cron (hours away) or onto a leg that
# will decline. This is the other half of `0e8cb71`: refusing to dispatch early was right, and it also
# meant never dispatching - a `paused` lineage whose leg ended 3 s ago was left to the schedule.
SLEEP = time.sleep
DEFAULT_SLEEP_CAP = 1800


def _floor_state(report: object, newest_run: object, now: datetime,
                 min_interval_seconds: int | None = None) -> tuple[int, int] | None:
    """(floor, age) for the waiting window, or None when the window is not what is being decided."""
    if not isinstance(report, Mapping) or not report or not isinstance(newest_run, Mapping):
        return None
    if str(report.get("status") or "") != "paused":
        return None
    reason = str(report.get("pause_reason") or "")
    resumable = report.get("resumable")
    if not isinstance(resumable, bool):
        resumable = reason in RESUMABLE_PAUSE_REASONS
    if not resumable:
        return None
    started = _parse_timestamp(newest_run.get("updated_at")) or _parse_timestamp(newest_run.get("created_at"))
    if started is None:
        return None
    return effective_floor_seconds(reason, min_interval_seconds), int((now - started).total_seconds())


def handover_wait(report: object, newest_run: object, now: datetime, *,
                  min_interval_seconds: int | None = None,
                  sleep_cap: int | None = DEFAULT_SLEEP_CAP,
                  ledger_governs: bool = False) -> int:
    """Seconds this leg should sit before asking, or 0 when no wait could make a successor acceptable."""
    state = _floor_state(report, newest_run, now, min_interval_seconds)
    if state is None:
        return 0
    reason = str(report.get("pause_reason") or "")
    if reason in LEDGER_GOVERNING_REASONS and not ledger_governs:
        return 0
    floor, age = state
    wait = int(floor - age)
    if wait <= 0:
        return 0
    if sleep_cap is not None and wait > int(sleep_cap):
        return 0
    return wait


DEFAULT_CRON_INTERVAL_SECONDS = 1800


def cron_delivery_gap(newest_schedule_run, now: datetime) -> int | None:
    """Seconds since the most recent *other* scheduled run of this workflow was created, or None."""
    if not isinstance(newest_schedule_run, Mapping):
        return None
    at = _parse_timestamp(newest_schedule_run.get("created_at")) or _parse_timestamp(
        newest_schedule_run.get("updated_at"))
    if at is None:
        return None
    return max(0, int((now - at).total_seconds()))


def cron_is_not_delivering(newest_schedule_run, now: datetime, *, readable: bool,
                           interval: int = DEFAULT_CRON_INTERVAL_SECONDS,
                           tolerance: int = 2) -> bool:
    """Whether the fallback this tool would otherwise defer to has stopped arriving.

    Both pairwise workflows declare `schedule: - cron: "13,43 * * * *"`, and that is what three of the
    four stand-down rules lean on: a refused handover is survivable if a tick shows up in half an hour.
    Measured on the runs list on 2026-10-14, it does not. Mercury's scheduled legs were created
    06:42:34Z, 12:27:22Z and 17:37:07Z - 5h45m and 5h10m apart, against a 30-minute declaration;
    Atria's at 06:10:45Z, 11:52:07Z and 17:07:10Z, the same shape. The repository already documents
    this ("after run 36791154490 ended at 04:35 UTC nothing ran for 2+ hours"), and the campaign
    died on it twice today: run 44 paused at 18:17 with a ledger reason and stood down *for a cron
    that had not run in five hours*.

    So an absent or stale scheduled sibling is read as "nothing is coming", and a leg with a pause the
    ledger meters arms its own successor on the ordinary floor instead. An unreadable run list never
    escalates: the absence of evidence about cron is not evidence of absence.
    """
    if not readable:
        return False
    gap = cron_delivery_gap(newest_schedule_run, now)
    if gap is None:
        return not isinstance(newest_schedule_run, Mapping)
    return gap >= int(interval) * int(tolerance)


def is_unstarted_scheduled_run(run) -> bool:
    """True for a `schedule` run GitHub has queued but never given a runner.

    `run_started_at` is set the moment a job begins, and a `queued` run with no start time is a slot
    reservation, not activity. Anything already `in_progress` is excluded by the status set, so this
    can never read a live leg as a placeholder.
    """
    if not isinstance(run, Mapping):
        return False
    if str(run.get("event") or "") != "schedule":
        return False
    if str(run.get("status") or "") not in {"queued", "requested", "pending"}:
        return False
    return not (run.get("run_started_at") or run.get("started_at"))


def decide_rearm(
    report,
    *,
    newest_run,
    now: datetime,
    min_interval_seconds: int | None = None,
    workflow_state: str | None,
    token_present: bool,
    chain_depth: int = 0,
    max_chain_depth: int = 40,
    marker_paths=(),
    stage_failed: bool = False,
    was_cancelled: bool = False,
    sleep_cap: int | None = DEFAULT_SLEEP_CAP,
    run_list_readable: bool = False,
    newest_schedule_run: object = None,
) -> tuple[bool, str]:
    """Return (dispatch?, reason). Pure: no network, no clock, no filesystem, so every branch
    is testable. Order matters: the stops a human would use are checked first, so a cancelled
    leg or a regressed upload cannot be talked into a successor by a report written before it."""
    if was_cancelled:
        return False, "this leg was cancelled; a cancelled leg is the documented way to stop the chain"
    if stage_failed:
        return False, "the state upload was refused because the checkpoint regressed; never continue from a regressed state"
    for marker in marker_paths:
        if marker and os.path.exists(marker):
            return False, _marker_decline(marker)
    if not isinstance(report, Mapping) or not report:
        return False, "no campaign report was written, so there is nothing to prove a resumable pause"
    status = str(report.get("status") or "")
    if status != "paused":
        return False, f"campaign status is {status!r}; only a paused lineage re-arms"
    reason = str(report.get("pause_reason") or "")
    resumable = report.get("resumable")
    if not isinstance(resumable, bool):
        resumable = reason in RESUMABLE_PAUSE_REASONS
    if not resumable:
        return False, f"pause_reason={reason!r} is not resumable; a successor leg would refuse this state"
    if reason in LEDGER_GOVERNING_REASONS:
        if not cron_is_not_delivering(newest_schedule_run, now, readable=run_list_readable):
            return False, (
                f"pause_reason={reason!r} is metered by the campaign's per-case attempt ledger, which the "
                "next leg would consume on the same failing case without producing the row; the scheduled "
                "tick is the wait that can actually help here"
            )
        gap = cron_delivery_gap(newest_schedule_run, now)
        print(
            "campaign re-arm: the ledger stand-down is lifted, because the tick it defers to has not "
            f"arrived - this workflow's newest scheduled sibling run was created "
            + (f"{gap} s ago, against a {DEFAULT_CRON_INTERVAL_SECONDS} s cron"
               if gap is not None else "not at all")
        )
    if chain_depth >= max_chain_depth:
        return False, (
            f"chain_depth={chain_depth} reached the cap of {max_chain_depth}; cron remains the only "
            "successor from here, and a human dispatch resets the count"
        )
    if not token_present:
        return False, "no GITHUB_TOKEN in the environment, so no dispatch can be authorized"
    if workflow_state not in (None, "active"):
        return False, (
            f"workflow state is {workflow_state!r}; GitHub will not start a run, and a refused "
            "dispatch here would be indistinguishable from a successful one"
        )
    if newest_run is None:
        if not run_list_readable:
            return False, "the workflow's run list could not be read; refusing to dispatch blind"
        # Readable, and empty once this leg is excluded from it: no sibling that could be busy, and no
        # finished leg whose age has to be sat out. That is the state of a lineage whose previous runs
        # have aged out of the list - or of a first leg - and answering it with "dispatch blind" is what
        # made a second run of a campaign require a human, which is the whole thing being fixed.
        return True, f"pause_reason={reason!r} with no other leg on record at chain_depth={chain_depth}"
    run_status = str(newest_run.get("status") or "")
    # A *queued* scheduled tick is not a leg that will continue the campaign. It carries no operator
    # inputs, so it can neither lift a marker nor raise a ceiling, and both workflows have been dying at
    # exactly this seam: Atria #27's re-arm declined at 18:09:34 because run 28 was queued; that queued
    # tick took the runner 6 s later, refused with exit 2 at 18:11:11 and wrote the marker that has
    # stopped every leg since. Mercury #43 and #40 declined the same way, at 18:14:34 and 07:39:20, for
    # a queued run that was in fact going to arrive. A run GitHub has not started cannot be "the leg
    # currently committing to the lineage", which is what this guard exists to detect, and the group
    # serialises whatever is dispatched anyway - so declining here buys nothing and can cost the chain.
    # The idle floor below still governs it, deliberately: dispatching inside `decide_tick`'s backoff
    # window produces a refused successor that does not re-arm, and a placeholder is no reason to skip
    # that wait - the exemption is about *busyness*, never about timing.
    placeholder = is_unstarted_scheduled_run(newest_run)
    if run_status in BUSY_RUN_STATUSES and not placeholder:
        return False, f"a leg is already {run_status}; the concurrency group would only queue another"
    started = _parse_timestamp(newest_run.get("updated_at")) or _parse_timestamp(newest_run.get("created_at"))
    if started is None:
        if placeholder:
            return True, (
                f"pause_reason={reason!r}; the workflow's newest other leg is queued scheduled run "
                f"{newest_run.get('id')}, which has never started, so this leg arms its own successor"
            )
        return False, "the most recent leg carries no readable timestamp"
    floor = effective_floor_seconds(reason, min_interval_seconds)
    age = int((now - started).total_seconds())
    if age < floor:
        governing = (
            "the supervisor's own resume backoff"
            if RESUME_BACKOFF_SECONDS >= cooldown_seconds_for(reason)
            else f"the cooldown for pause_reason={reason!r}"
        )
        wait = int(floor - age)
        capped = sleep_cap is not None and wait > int(sleep_cap)
        return False, (
            f"the most recent leg ended {age} s ago, below the {floor} s floor set by {governing}; "
            "a successor dispatched now would be refused with mode=none and would not re-arm"
            + (f" - and sitting it out is off: a {wait} s wait exceeds --sleep-cap={sleep_cap}" if capped else "")
        )
    if placeholder:
        return True, (
            f"pause_reason={reason!r}; the only other leg on the workflow's list is queued scheduled "
            f"run {newest_run.get('id')}, which has not started and carries no operator inputs, so this "
            f"leg arms its own successor instead of trusting it (idle {age} s, floor {floor} s, "
            f"chain_depth={chain_depth})"
        )
    return True, f"pause_reason={reason!r} after a {age} s idle gap at chain_depth={chain_depth}"


def _marker_decline(path: str) -> str:
    """Say what the terminal marker recorded, in the line the operator actually sees.

    The marker's contents otherwise live only inside the campaign's own state artifact, and an
    artifact's bytes are not readable from outside a runner: `archive_download_url` hands off to a
    host a diagnosing environment cannot reach (measured 2026-10-13: HTTP 404 from this sandbox for
    runs 38473650121 and 38473489396). So a decline that said only "stopped on purpose" left the
    cause unreadable - Mercury run 37 and Atria run 22 both declined that way, while the actionable
    fact, `wrapper_exception: campaign intent differs from the restored state (changed:
    gate_context_sha)`, sat in a zip nobody could open. The marker is written by
    `tools/atria_campaign.py` with `pause_reason` and a redacted `detail`, so both are quoted here
    and the phrase the chain stands down on is kept in every branch, unreadable file included.
    """
    name = os.path.basename(path)
    try:
        with open(path, encoding="utf-8") as handle:
            recorded = json.load(handle)
    except (OSError, ValueError):
        return f"terminal marker {name} is present but unreadable, so the campaign stopped on purpose"
    if not isinstance(recorded, Mapping):
        return f"terminal marker {name} is present but holds no record, so the campaign stopped on purpose"
    reason = str(recorded.get("pause_reason") or "unrecorded")
    # 240 characters is what hid the answer twice. Both Atria refusals of 2026-10-14 (run 25 at
    # 06:13Z, run 28 at 18:11Z) ended on `campaign intent differs from the restored state`, whose
    # message names the drifted field in a trailing `(changed: ...)` - and both annotations stop at
    # "...provider, model, mode, manifest, or code ", inside the sentence, before the part that says
    # which of those five moved. The campaign's own log line holds it, the state artifact holds it,
    # and neither is readable from outside a runner; this annotation is the only channel, so the
    # channel has to be wide enough to carry the diagnosis.
    detail = " ".join(str(recorded.get("detail") or "").split())[:1200]
    notes = " ".join(_state_diagnostics(path))
    return (
        f"terminal marker {name} is present (pause_reason={reason}"
        + (f"; {detail}" if detail else "")
        + "), so the campaign stopped on purpose"
        + ((" | " + notes) if notes else "")
    )


def _state_diagnostics(marker_path: str) -> list[str]:
    """What the campaign recorded beside the marker, in the order a reader needs it.

    A refusal that names the field it refused on writes it into the state directory (`tools/atria_
    campaign.py`, `campaign_intent_refusal.json`) and a refusal the campaign has already seen once
    writes `state_contract_stop.json` with a repeat count. Both files sit next to the marker, both
    are small, and neither is load-bearing - so reading them is wrapped in the same fail-open rule as
    everything else in this step: an unreadable diagnostic never changes the decision.
    """
    out: list[str] = []
    here = os.path.dirname(os.path.abspath(marker_path))
    for name in ("campaign_intent_refusal.json", "state_contract_stop.json"):
        try:
            with open(os.path.join(here, name), encoding="utf-8") as handle:
                record = json.load(handle)
        except (OSError, ValueError):
            continue
        if not isinstance(record, Mapping):
            continue
        picked = {key: record[key] for key in
                  ("changed", "count", "event", "expected", "recorded") if key in record}
        if picked:
            flat = " ".join(f"{k}={v}" for k, v in picked.items())
            out.append(f"{name}: {' '.join(flat.split())[:600]}")
    return out



def _request(url: str, token: str | None, *, data: bytes | None = None, method: str | None = None) -> tuple[int, Any]:
    request = urllib.request.Request(url, data=data, method=method or ("POST" if data else "GET"))
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("User-Agent", "campaign-rearm")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8", "replace")
            return response.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:  # a 403/422 is information, not a crash
        body = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(body) if body else {}
        except json.JSONDecodeError:
            return exc.code, {"message": body[:200]}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 0, {"message": f"{type(exc).__name__}: {exc}"}


def find_workflow(api: str, repo: str, token: str | None, name: str) -> tuple[dict | None, dict | None]:
    """Resolve the workflow by *name*, so the launcher needs no hardcoded file path or id."""
    status, body = _request(f"{api}/repos/{repo}/actions/workflows?per_page=100", token)
    if status != 200:
        return None, {"error": f"workflow list returned HTTP {status}: {str(body.get('message'))[:120]}"}
    for entry in body.get("workflows") or []:
        if str(entry.get("name")) == name:
            return entry, None
    return None, {"error": f"no workflow named {name!r} in {repo}"}


def successor_inputs(ref: str, chain_depth: int, rebase_ref: str = "") -> dict[str, Any]:
    """Exactly the manual click, plus the counter the cap reads. Nothing else.

    ``execution_mode`` is never passed, so a chained leg can only resume what is already authorized
    to bill, and ``clear_wrapper_stop`` is never passed, so an operator gate stays an operator's.
    ``rebase_ref`` is set only when the caller has *proved* the two trees agree on every
    verdict-producing file, which is the one case where moving the pin cannot change a measurement:
    see ``plan_landing``. It carries a full commit SHA rather than a branch name, so the successor
    runs the tree that was checked, not whatever the branch says an hour later.
    """
    inputs: dict[str, Any] = {"resume_previous": True, "chain_depth": str(int(chain_depth) + 1)}
    if ref:
        inputs["ref"] = ref
    if rebase_ref:
        inputs["rebase_onto_ref"] = rebase_ref
    return inputs


def dispatch_next_leg(api: str, repo: str, token: str | None, workflow_id: Any, ref: str,
                      chain_depth: int = 0, rebase_ref: str = "",
                      workflow_ref: str = "") -> tuple[bool, str]:
    """Ask GitHub for the successor leg. The payload needs BOTH refs, and they are not the same thing.

    ``inputs.ref`` is what the leg checks out and runs - the campaign's pin. The top-level ``ref`` is
    which copy of the *workflow file* GitHub runs, and the create-a-workflow-dispatch endpoint requires
    it; it is not one of the ``inputs``. It stays deliberately unrecorded here for as long as the tool
    never reached this call - 58 legs of the two pairwise workflows, every one of them declining before
    the dispatch (measured 2026-10-14 across all 28 Atria and 30 Mercury runs: no run of either was
    ever created by the workflow's own token) - and a required field is not something to discover on the
    leg that first gets here. So it is taken from the ref this leg itself runs on (``main`` for a cron
    tick and for a hand dispatch alike), which keeps the successor's operations on the newest workflow
    file while its measurement stays on the pin.
    """
    inputs = successor_inputs(ref, chain_depth, rebase_ref)
    payload = json.dumps({"ref": workflow_ref or "main", "inputs": inputs}).encode("utf-8")
    status, body = _request(
        f"{api}/repos/{repo}/actions/workflows/{workflow_id}/dispatches",
        token,
        data=payload,
        method="POST",
    )
    if status in (200, 201, 202, 204):
        return True, f"dispatch accepted (HTTP {status}) with inputs {sorted(inputs)}"
    return False, f"dispatch refused (HTTP {status}): {str(body.get('message'))[:180]}"



# --------------------------------------------------------------------- landing
#
# A campaign leg runs the code frozen in `campaign_ref.txt`, and that pin is the reason a fix has to
# be carried to the campaign by hand: on 2026-10-14 Mercury was parked at `ffcdc78` while the branch
# tip already held the rule that would have unblocked it, and the only lever the launcher offers is a
# `rebase_onto_ref` dispatch, which re-grades the exact-instance gate because the grading context
# changed with it. That cost is what makes the human in the loop, and it is only real when a
# *verdict-producing* file differs. This block measures the difference instead of assuming it: when
# the upstream tip changes nothing the gate depends on, re-pinning the successor is free and the
# re-arm does it; when it changes a verdict, the landing stays an operator's decision and the leg
# says so, with the count.

def confirm_successor(api: str, repo: str, token: str | None, workflow_id: Any, our_run: str,
                      *, attempts: int = 6, delay: int = 10, sleep=SLEEP) -> tuple[dict | None, str]:
    """Look for the run this leg just asked for, instead of trusting the accepted dispatch.

    A 204 means GitHub took the request, not that a run exists: a payload that validates can still
    produce nothing, and that is exactly how the chain stayed dead for 58 legs while every step around
    it looked healthy. The endpoint's own response carries no run id, so the only proof is the
    workflow's run list gaining a run that is not this one. Fail-open in both directions - an
    unreachable API says \"not verified\", never \"no successor\" - and the answer is printed either
    way, because the claim \"it resumes automatically\" is worth one API call and nothing else.
    """
    if not our_run:
        return None, "not verified: this leg has no run id to compare against"
    last: list = []
    for attempt in range(max(1, int(attempts))):
        status, body = _request(
            f"{api}/repos/{repo}/actions/workflows/{workflow_id}/runs?per_page=10", token
        )
        if status != 200:
            return None, f"not verified: the run list answered HTTP {status}"
        last = (body.get("workflow_runs") or []) if isinstance(body, dict) else []
        try:
            mine = int(our_run)
        except (TypeError, ValueError):
            return None, "not verified: this leg's run id is not a number"
        for run in last:
            if not isinstance(run, Mapping):
                continue
            try:
                newer = int(run.get("id") or 0) > mine
            except (TypeError, ValueError):
                continue
            if newer and str(run.get("event") or "") == "workflow_dispatch":
                return run, f"successor run #{run.get('run_number')} is {run.get('status')}"
        if attempt + 1 < max(1, int(attempts)):
            sleep(int(delay))
    return None, (
        f"dispatched and no run newer than {our_run} appeared on this workflow's list after "
        f"{int(attempts) * int(delay)} s, so the chain is NOT armed; cron remains the fallback"
    )


def _run(argv: list[str], cwd: str | None = None, timeout: int = 180) -> tuple[int, str]:
    """`git`/`python` without a shell, and never an exception: a failed check is information."""
    try:
        completed = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, f"{type(exc).__name__}: {exc}"
    return completed.returncode, ((completed.stdout or "") + (completed.stderr or "")).strip()


def grading_context(tree: str) -> tuple[dict[str, str] | None, str]:
    """The verdict-file digests of a working tree, asked of that tree's own `tools/gate_context.py`.

    Calling the tree's copy rather than importing this one is the point: `ROOT` is derived from the
    file's own location, so the digest of the tip is computed by the tip's rules, and a repository
    that changes what it considers verdict-relevant changes this check with it. It raises if a
    declared input is missing, so a partial tree reports itself as unavailable instead of as free.
    """
    script = os.path.join(tree, "tools", "gate_context.py")
    if not os.path.isfile(script):
        return None, f"no tools/gate_context.py under {tree}"
    code, out = _run([sys.executable or "python3", script, "--json"], cwd=tree)
    if code != 0:
        return None, (out[:200] or "gate_context exited non-zero")
    try:
        files = json.loads(out).get("files")
    except (ValueError, AttributeError):
        return None, "gate_context --json did not parse"
    if not isinstance(files, dict):
        return None, "gate_context --json carried no file inventory"
    return {str(k): str(v) for k, v in files.items()}, ""


def fetch_tree(cwd: str, revision: str, destination: str) -> tuple[bool, str]:
    """Materialise `revision` into `destination` from the checkout's own object store."""
    code, out = _run(["git", "-C", cwd, "archive", "--format=tar", "-o",
                      os.path.join(destination, "tip.tar"), revision])
    if code != 0:
        return False, f"git archive {revision[:12]}: {out[:180]}"
    tar_path = os.path.join(destination, "tip.tar")
    try:
        with tarfile.open(tar_path) as archive:
            # No `filter="data"`: that keyword is 3.12 and the runners install 3.11, where a
            # TypeError here would read as "the landing check is unavailable" forever. The
            # equivalent guard is explicit - refuse anything that would leave the directory.
            root = os.path.realpath(destination)
            for member in archive.getmembers():
                target = os.path.realpath(os.path.join(destination, member.name))
                if not target.startswith(root + os.sep) or member.issym() or member.islnk():
                    return False, f"archive carried an unsafe member: {member.name[:80]}"
            archive.extractall(destination)
    except (OSError, tarfile.TarError) as exc:
        return False, f"extract: {type(exc).__name__}: {exc}"
    return True, ""


def upstream_tip(api: str, repo: str, token: str | None, pin: str) -> tuple[dict | None, str]:
    """The branch whose tip contains this leg's commit and is ahead of it, if any.

    `status == "ahead"` is the ancestry authority the campaign already uses elsewhere: a branch that
    has diverged is not a landing, it is a merge, and a merge is not this leg's business.
    """
    if not (api and repo and token and pin):
        return None, "no API endpoint, repository, token or recorded pin"
    status, body = _request(f"{api}/repos/{repo}/branches?per_page=100", token)
    if status != 200:
        return None, f"branch list returned HTTP {status}"
    best: dict | None = None
    entries = body.get("branches") if isinstance(body, dict) else body
    for entry in entries or []:
        name = str(entry.get("name") or "")
        if not name or name == pin:
            continue
        cstatus, cmp = _request(
            f"{api}/repos/{repo}/compare/{urllib.parse.quote(pin, safe='')}"
            f"...{urllib.parse.quote(name, safe='')}", token)
        if cstatus != 200 or not isinstance(cmp, dict) or str(cmp.get("status")) != "ahead":
            continue
        ahead_by = int(cmp.get("ahead_by") or 0)
        if ahead_by < 1:
            continue
        sha = str(((cmp.get("merge_commit") or {}).get("sha"))
                  or ((entry.get("commit") or {}).get("sha")) or "")
        if not sha:
            continue
        if best is None or ahead_by > best["ahead_by"]:
            best = {"branch": name, "sha": sha, "ahead_by": ahead_by}
    if best is None:
        return None, "no branch contains this leg's commit and is ahead of it"
    return best, ""


def landing_verdict(local: dict | None, tip: dict | None, *, upstream: dict | None,
                    marker_present: bool, t1_incomplete: bool, carries_waiver: bool = True,
                    unavailable: str = "") -> dict[str, Any]:
    """Pure decision: what a re-pin to `upstream` would cost, and whether this leg may do it.

    `free` means the two trees' verdict inventories are byte-identical, so no banked gate row can be
    affected. Anything else is left alone: the withheld verdicts are the cases where the launcher's
    own rebase pre-flight would answer `mode=none` and the successor would run an empty leg.
    """
    if marker_present or t1_incomplete:
        why = ("a terminal marker is in this leg's state" if marker_present
               else "T1 was interrupted before its report")
        return {"verdict": "withheld", "why": f"the launcher would refuse a rebase because {why}"}
    if not carries_waiver:
        # `Decide fresh dispatch versus supervised resume` refuses a rebase onto a ref whose
        # `tools/run_suite.py` does not carry the manifest-commit waiver, and an accepted-looking
        # dispatch that lands in `mode=none` is a leg burned for nothing. Identical verdict
        # inventories usually make this true by construction; it is checked because the failure it
        # prevents is silent.
        return {"verdict": "withheld", "why": "the pinned run_suite.py carries no manifest-commit waiver, so the launcher would refuse the rebase"}
    if local is None or tip is None:
        return {"verdict": "unavailable", "why": unavailable or "the grading context could not be read"}
    if upstream is None:
        return {"verdict": "none", "why": "nothing to land"}
    differing = sorted(key for key in set(local) | set(tip) if local.get(key) != tip.get(key))
    if not differing:
        return {"verdict": "free", "sha": upstream["sha"], "branch": upstream["branch"],
                "commits": upstream["ahead_by"], "differing": []}
    return {"verdict": "costly", "sha": upstream["sha"], "branch": upstream["branch"],
            "commits": upstream["ahead_by"], "differing": differing}


def plan_landing(api: str, repo: str, token: str | None, pin: str, cwd: str,
                 state_dir: str | None = None) -> dict[str, Any]:
    """Ask the repository whether re-pinning the successor at the upstream tip is free.

    Fail-open by construction: every path that cannot prove equality returns `unavailable`, which the
    caller reads as "dispatch as before". A check that cannot run must never cost a campaign its
    successor.
    """
    if not (api and repo and token and pin):
        return {"verdict": "unavailable", "why": "no API endpoint, repository, credential or recorded pin"}
    state = state_dir or os.getcwd()
    marker_present = any(
        os.path.exists(os.path.join(state, name)) for name in ("wrapper_failed.json",)
    )
    t1_incomplete = (os.path.exists(os.path.join(state, "t1_started.json"))
                     and not os.path.exists(os.path.join(state, "t1_same_fact_presentation.json")))
    local, why = grading_context(cwd)
    if local is None:
        return landing_verdict(None, None, upstream=None, marker_present=marker_present,
                               t1_incomplete=t1_incomplete, unavailable=why)
    try:
        carried = open(os.path.join(cwd, "tools", "run_suite.py"), encoding="utf-8").read()
    except OSError:
        carried = ""
    waiver = "allow_manifest_commit_rebase" in carried
    upstream, why = upstream_tip(api, repo, token, pin)
    if upstream is None:
        return landing_verdict(local, None, upstream=None, marker_present=marker_present,
                               t1_incomplete=t1_incomplete, unavailable=why)
    with tempfile.TemporaryDirectory(prefix="campaign-landing-") as work:
        ok, detail = fetch_tree(cwd, upstream["sha"], work)
        if not ok:
            return landing_verdict(local, None, upstream=None, marker_present=marker_present,
                                   t1_incomplete=t1_incomplete, unavailable=detail)
        tip, why = grading_context(work)
    return landing_verdict(local, tip, upstream=upstream, marker_present=marker_present,
                           t1_incomplete=t1_incomplete, unavailable=why)



def recorded_manifest_commit(state_dir: str) -> str:
    """The commit the *next* leg will be told to run, as the checkpoint records it.

    A resume leg does not read `campaign_ref.txt`; `campaign_supervisor.decide_tick` answers with
    `run.manifest_commit` from `suite_checkpoint.json`, and the launcher checks that out. A leg that
    runs newer code than the checkpoint names only re-authors that field when the campaign is
    re-based, so today's rollback was silent and total: Mercury run 43 ran `6a24e77` and banked 75
    gate rows, its checkpoint kept saying `ffcdc78`, and run 44 therefore resumed `ffcdc78` - without
    the per-case closure rule, four attempts from a pause nothing may resume.
    """
    try:
        with open(os.path.join(state_dir, "suite_checkpoint.json"), encoding="utf-8") as handle:
            checkpoint = json.load(handle)
    except (OSError, ValueError):
        return ""
    run = checkpoint.get("run") if isinstance(checkpoint, Mapping) else None
    return str((run or {}).get("manifest_commit") or "")


def leg_head_sha(cwd: str, state_dir: str) -> str:
    """The commit this leg actually ran: what it wrote into its own state, else its checkout."""
    for candidate in (os.path.join(state_dir, "campaign_ref.txt"),):
        try:
            with open(candidate, encoding="utf-8") as handle:
                sha = handle.read().strip()
            if sha:
                return sha
        except OSError:
            pass
    code, out = _run(["git", "-C", cwd, "rev-parse", "HEAD"])
    return out.strip() if code == 0 else ""


def fast_forward(api: str, repo: str, token: str | None, recorded: str, head: str) -> tuple[bool, str]:
    """Is `head` a descendant of `recorded`? A repair may only ever fast-forward the lineage."""
    if not (api and repo and token and recorded and head):
        return False, "no API endpoint, repository, credential or one of the two commits"
    status, body = _request(
        f"{api}/repos/{repo}/compare/{urllib.parse.quote(recorded, safe='')}...{urllib.parse.quote(head, safe='')}",
        token)
    if status != 200 or not isinstance(body, dict):
        return False, f"compare returned HTTP {status}"
    state = str(body.get("status") or "")
    if state != "ahead":
        return False, f"`{head[:7]}` is {state or 'not ahead'} of `{recorded[:7]}`, and a diverged pair is a merge"
    return True, ""


def pin_repair_verdict(*, recorded: str, head: str, rec_ctx: dict | None, head_ctx: dict | None,
                       fast_forward_ok: bool, marker_present: bool, t1_incomplete: bool,
                       carries_waiver: bool = True) -> dict[str, Any]:
    """Whether re-pinning the successor at `head` repairs the lineage at zero grading cost.

    `rebase_onto_ref` is the one launcher path that writes `run.manifest_commit`, and it is free
    exactly when the two trees agree on every verdict-producing file - the same test `plan_landing`
    applies to the upstream tip, applied here to the pair the lineage is actually split across.
    Withheld for a terminal marker, an interrupted T1 or a tree whose `gate_context.py` cannot list a
    declared input: an unavailable check never buys a repair.
    """
    if not recorded or not head:
        return {"repair": False, "why": "no recorded commit or no leg sha to repair with", "differing": []}
    if recorded == head:
        return {"repair": False, "why": "the pin is already sticky", "differing": []}
    if marker_present or t1_incomplete:
        return {"repair": False, "why": "a terminal marker or an interrupted T1 is in the carried state",
                "differing": []}
    if not carries_waiver:
        return {"repair": False, "why": "the carried code cannot accept a re-authored intent",
                "differing": []}
    if not fast_forward_ok:
        return {"repair": False, "why": "the two commits are not a fast-forward", "differing": []}
    if rec_ctx is None or head_ctx is None:
        return {"repair": False, "why": "a verdict inventory could not be read at one of the two commits",
                "differing": []}
    differing = sorted(k for k in set(rec_ctx) | set(head_ctx) if rec_ctx.get(k) != head_ctx.get(k))
    if differing:
        return {"repair": False, "why": "verdict files differ, so a re-pin re-grades the gate",
                "differing": differing}
    return {"repair": True, "why": "no verdict-producing file differs between the two commits",
            "differing": []}


def plan_pin_repair(api: str, repo: str, token: str | None, cwd: str, state_dir: str) -> dict[str, Any]:
    """Measure the pin the successor would revert to, and whether it can be repaired for free."""
    state = state_dir or os.getcwd()
    recorded = recorded_manifest_commit(state)
    head = leg_head_sha(cwd, state)
    marker_present = os.path.exists(os.path.join(state, "wrapper_failed.json"))
    t1_incomplete = (os.path.exists(os.path.join(state, "t1_started.json"))
                     and not os.path.exists(os.path.join(state, "t1_same_fact_presentation.json")))
    if not recorded or not head or recorded == head:
        return pin_repair_verdict(recorded=recorded, head=head, rec_ctx=None, head_ctx=None,
                                  fast_forward_ok=False, marker_present=marker_present,
                                  t1_incomplete=t1_incomplete)
    head_ctx, why_head = grading_context(cwd)
    with tempfile.TemporaryDirectory(prefix="campaign-pin-") as work:
        ok, detail = fetch_tree(cwd, recorded, work)
        rec_ctx, why_rec = grading_context(work) if ok else (None, detail)
    ff, why_ff = fast_forward(api, repo, token, recorded, head)
    try:
        carried = open(os.path.join(cwd, "tools", "run_suite.py"), encoding="utf-8").read()
    except OSError:
        carried = ""
    verdict = pin_repair_verdict(recorded=recorded, head=head, rec_ctx=rec_ctx, head_ctx=head_ctx,
                                 fast_forward_ok=ff, marker_present=marker_present,
                                 t1_incomplete=t1_incomplete,
                                 carries_waiver="allow_manifest_commit_rebase" in carried)
    # Never report a repair as free on the strength of a comparison that did not run.
    if verdict["repair"] and (why_head or why_rec or why_ff):
        verdict = {"repair": False, "why": why_rec or why_ff or why_head, "differing": []}
    verdict["recorded"] = recorded
    verdict["head"] = head
    return verdict


def _newest_state_owner_for(args: Any, api: str, token: str | None) -> tuple[tuple[str, str, str], Any]:
    """`newest_state_owner` bound to the arguments this step was invoked with, with the workflow id
    resolved by name (the launcher passes a display name, never a file path)."""
    workflow, _ = find_workflow(api, args.repo, token, args.workflow)
    if workflow is None:
        return ("", "", "the workflow could not be resolved by name"), None
    owner, at, why = newest_state_owner(api, args.repo, token, workflow["id"], args.run_id)
    return (owner, at, why), workflow


def fork_verdict(our_run: str, newest_owner: str, newest_at: str) -> dict[str, Any]:
    """Was the newest committed state written by *this* leg?

    `Upload ... campaign state` runs just before this step, so in the normal case the newest
    state artifact belongs to this run and there is nothing to say. If it belongs to a different
    run of the same workflow, two legs were on one lineage and the other one committed state while
    this one ran: the checkpoint on `main` is no longer the one this leg produced, and a successor
    armed here would resume a state that has already been overwritten - which is how Mercury lost a
    finished gate on 2026-10-14 (run 39 banked `189 / 189` at 03:51:33Z, run 41 committed at
    07:57:37Z carrying `126 / 189` and the pre-rebase pin, so `Leg code` went backwards from
    `3b0cd0a` to `ffcdc78`). Chaining is declined and named; the scheduled tick reads whichever state
    is newest, and a human gets a sentence to act on instead of a silently diverging ledger.
    """
    if not our_run or not newest_owner:
        return {"forked": False, "why": "not checked"}
    if newest_owner == str(our_run):
        return {"forked": False, "why": "this leg owns the newest state"}
    return {
        "forked": True,
        "why": (
            f"the newest state artifact for this workflow belongs to run {newest_owner}, not this leg "
            f"({our_run}); it was committed at {newest_at or 'an unknown time'}, so another leg wrote "
            "state while this one ran and this leg's ledger is not the tip"
        ),
    }


def newest_state_owner(api: str, repo: str, token: str | None, workflow_id: Any,
                       our_run: str, *, state_marker: str = "-state-") -> tuple[str, str, str]:
    """The run id behind the newest state artifact that belongs to *this* workflow, if it can be read.

    Only up to five candidates are resolved through `/actions/runs/{id}`, because an artifact name is
    the only place the run id is recorded and the covering campaigns upload same-shaped names on
    purpose; their artifacts must not be mistaken for a fork of this lineage.
    """
    if not (api and repo and token):
        return "", "", "no API endpoint, repository or credential"
    status, body = _request(f"{api}/repos/{repo}/actions/artifacts?per_page=100", token)
    if status != 200 or not isinstance(body, dict):
        return "", "", f"artifact list returned HTTP {status}"
    candidates: list[tuple[str, str]] = []
    for entry in body.get("artifacts") or []:
        name = str(entry.get("name") or "")
        if state_marker not in name or entry.get("expired"):
            continue
        digits = ""
        for char in reversed(name):
            if char.isdigit():
                digits = char + digits
            else:
                break
        if len(digits) >= 6:
            candidates.append((str(entry.get("updated_at") or ""), digits))
    if not candidates:
        return "", "", "no state artifacts were listed"
    candidates.sort()
    for _at, owner in reversed(candidates[-5:]):
        if owner == str(our_run):
            return owner, _at, ""
        rstatus, run = _request(f"{api}/actions/runs/{owner}", token)
        if rstatus == 200 and isinstance(run, dict) and str(((run.get("workflow") or {}).get("id"))) == str(workflow_id):
            return owner, _at, ""
    return "", "", "no state artifact from this workflow could be attributed to a run"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", required=True, help="path to the leg's campaign_report.json")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""), help="owner/name")
    parser.add_argument("--workflow", default=os.environ.get("GITHUB_WORKFLOW", ""), help="workflow display name")
    parser.add_argument("--api-url", default=os.environ.get("GITHUB_API_URL", "https://api.github.com"))
    parser.add_argument("--ref", default="", help="ref to pin the successor run's checkout to (optional)")
    parser.add_argument(
        "--min-interval-seconds",
        type=int,
        default=None,
        help="override the reason-graded cooldown with a single floor",
    )
    parser.add_argument("--chain-depth", type=int, default=0, help="this leg's chain_depth input")
    parser.add_argument("--max-chain-depth", type=int, default=40, help="stop chaining after this many legs")
    parser.add_argument("--marker", action="append", default=[], dest="markers",
                        help="path whose presence means the campaign stopped on purpose (repeatable)")
    parser.add_argument("--stage-failed", action="store_true", help="the state upload was refused as a regression")
    parser.add_argument("--cancelled", action="store_true", help="this leg was cancelled")
    parser.add_argument("--sleep-cap", type=int, default=DEFAULT_SLEEP_CAP,
                        help="longest wait this leg will sit out so a successor is accepted (0 disables waiting)")
    parser.add_argument(
        "--exclude-run",
        default=os.environ.get("GITHUB_RUN_ID", ""),
        help="run id to leave out of the busy check; defaults to this leg, which is never a reason to stand down",
    )
    parser.add_argument("--workflow-ref", default=os.environ.get("GITHUB_REF_NAME", "") or "main",
                        help="the ref whose workflow file the successor runs; required by the "
                             "dispatch endpoint and distinct from --ref, which is the code pin")
    parser.add_argument("--verify-seconds", type=int, default=60,
                        help="how long to look for the successor run after an accepted dispatch")
    parser.add_argument("--dry-run", action="store_true", help="print the decision without dispatching")
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", ""),
                        help="this leg's run id; the newest state artifact must belong to it")
    args = parser.parse_args(argv)

    api = args.api_url.rstrip("/")
    token = os.environ.get("GITHUB_TOKEN") or ""
    report: Mapping[str, Any] | None = None
    try:
        with open(args.report, "r", encoding="utf-8") as handle:
            report = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"campaign re-arm skipped: report unreadable ({type(exc).__name__}: {exc})")
        report = None

    newest_run: Mapping[str, Any] | None = None
    newest_schedule_run: Mapping[str, Any] | None = None
    workflow: dict | None = None
    # Three states, and the difference between the last two is what this file exists to get right: the
    # list was never asked for (nothing to conclude), it was asked for and failed (refuse to dispatch
    # blind), or it came back with only this leg in it (idle, and free to arm a successor).
    run_list_readable = False
    if report and report.get("status") == "paused" and token:
        workflow, lookup_error = find_workflow(api, args.repo, token or None, args.workflow)
        if lookup_error:
            print(f"campaign re-arm skipped: {lookup_error['error']}")
        else:
            status, body = _request(
                    f"{api}/repos/{args.repo}/actions/workflows/{workflow['id']}/runs?per_page=20", token or None
                )
            listed = (body.get("workflow_runs") or []) if status == 200 else []
            run_list_readable = status == 200
            siblings = other_legs(listed, args.exclude_run)
            if listed and not siblings:
                print("campaign re-arm: the only leg on record is this one, so it does not count as busy")
            newest_run = siblings[0] if siblings else None
            newest_schedule_run = next(
                (run for run in siblings if str(run.get("event") or "") == "schedule"), None)

    now = datetime.now(timezone.utc)
    decision, reason = decide_rearm(
        report,
        newest_run=newest_run,
        now=now,
        sleep_cap=args.sleep_cap,
        min_interval_seconds=args.min_interval_seconds,
        workflow_state=(str(workflow["state"]) if workflow else None),
        token_present=bool(token),
        chain_depth=args.chain_depth,
        max_chain_depth=args.max_chain_depth,
        marker_paths=args.markers,
        stage_failed=args.stage_failed,
        was_cancelled=args.cancelled,
        run_list_readable=run_list_readable,
        newest_schedule_run=newest_schedule_run,
    )
    if not decision:
        # The refusal may be purely temporal, in which case the fix is to wait, not to hand the
        # campaign back to a schedule that delivered three ticks today.
        wait = handover_wait(report, newest_run, now, min_interval_seconds=args.min_interval_seconds,
                             sleep_cap=args.sleep_cap,
                             ledger_governs=cron_is_not_delivering(
                                 newest_schedule_run, now, readable=run_list_readable))
        if wait:
            print(f"campaign re-arm: a successor would be refused for another {wait} s, so this leg "
                  f"is sitting it out before dispatching", flush=True)
            SLEEP(wait + 1)
            decision, reason = decide_rearm(
                report,
                newest_run=newest_run,
                now=now + timedelta(seconds=wait + 1),
                sleep_cap=args.sleep_cap,
                min_interval_seconds=args.min_interval_seconds,
                workflow_state=(str(workflow["state"]) if workflow else None),
                token_present=bool(token),
                chain_depth=args.chain_depth,
                max_chain_depth=args.max_chain_depth,
                marker_paths=args.markers,
                stage_failed=args.stage_failed,
                was_cancelled=args.cancelled,
                run_list_readable=run_list_readable,
                newest_schedule_run=newest_schedule_run,
            )
    if not decision:
        # A decline is a decision, and it must not live only in a log nobody opens: like the refused-tick
        # announcement, this reaches the Checks UI and the jobs API.
        print(f"campaign re-arm skipped: {reason}")
        print(f"::warning::campaign re-arm declined: {reason}")
        return 0
    (tip_owner, tip_at, _tip_why), _workflow_for_tip = _newest_state_owner_for(args, api, token)
    fork = fork_verdict(args.run_id, tip_owner, tip_at)
    if fork["forked"]:
        print(f"campaign re-arm skipped: {fork['why']}")
        print(f"::warning::campaign re-arm declined: {fork['why']}")
        return 0
    landing = plan_landing(api, args.repo, token or None, args.ref, os.getcwd(),
                           state_dir=os.path.dirname(os.path.abspath(args.report)))
    rebase_ref = ""
    if landing["verdict"] == "free":
        rebase_ref = str(landing["sha"])
        print(f"campaign re-arm: the successor is re-pinned at {rebase_ref[:7]} "
              f"({landing['branch']} is {landing['commits']} commit(s) ahead and no verdict-producing "
              "file differs, so no banked gate row is re-graded)")
        print(f"::notice::campaign re-arm re-pinned the successor at {rebase_ref[:7]} for free: "
              f"{landing['commits']} commit(s) of campaign-control code, zero verdict files changed")
    elif landing["verdict"] == "costly":
        names = ", ".join(landing["differing"][:6])
        more = f" (+{len(landing['differing']) - 6} more)" if len(landing["differing"]) > 6 else ""
        print(f"campaign re-arm: {landing['branch']} is {landing['commits']} commit(s) ahead, but "
              f"{len(landing['differing'])} verdict-producing file(s) differ ({names}{more}), so "
              "re-pinning this campaign there re-grades the exact-instance gate. That landing is a "
              "human dispatch, and this leg will not spend the campaign's banked rows on it")
        print(f"::warning::campaign re-arm left the pin at {args.ref[:7] or 'this leg'}: a landing on "
              f"{landing['branch']} would re-grade the gate over {len(landing['differing'])} verdict "
              f"file(s){more}; dispatch rebase_onto_ref yourself if that is the trade you want")
    elif landing["verdict"] not in ("none",):
        print(f"campaign re-arm: no landing checked ({landing['why']}); the successor runs this leg's pin")
    if not rebase_ref:
        # The pin this leg actually ran has to reach the successor, or the lineage walks back to the
        # commit the checkpoint names and every fix carried by the leg is unlanded without a word.
        repair = plan_pin_repair(api, args.repo, token or None, os.getcwd(),
                                 os.path.dirname(os.path.abspath(args.report)))
        if repair.get("repair"):
            rebase_ref = str(repair["head"])
            print(f"campaign re-arm: the successor is re-pinned at {rebase_ref[:7]} to repair the pin - "
                  f"this leg ran {rebase_ref[:7]} while its checkpoint still recorded "
                  f"{str(repair.get('recorded') or '')[:7]}, and no verdict file differs between them, "
                  "so no banked row is re-graded")
            print(f"::notice::campaign re-arm repaired the pin at {rebase_ref[:7]}: the checkpoint named "
                  f"{str(repair.get('recorded') or '')[:7]}, the leg ran {rebase_ref[:7]}, "
                  "zero verdict files differ, so the successor keeps this leg's code for free")
        elif repair.get("recorded") and repair.get("head"):
            names = ", ".join(repair["differing"][:6])
            more = f" (+{len(repair['differing']) - 6} more)" if len(repair["differing"]) > 6 else ""
            print(f"campaign re-arm: the successor will revert the pin from {str(repair['head'])[:7]} to "
                  f"{str(repair['recorded'])[:7]} ({repair['why']}"
                  + (f"; differing: {names}{more}" if repair["differing"] else "") + ")")
            if repair["differing"]:
                print(f"::warning::campaign pin will revert to {str(repair['recorded'])[:7]} on the next "
                      f"leg: {len(repair['differing'])} verdict file(s) differ from the {repair['head'][:7]} "
                      f"this leg ran{more}; a rebase dispatch there re-grades the exact-instance gate")
    if args.dry_run:
        print(f"campaign re-arm would dispatch: {reason} (dry run)")
        return 0
    ok, detail = dispatch_next_leg(api, args.repo, token or None, workflow["id"], args.ref,
                                   args.chain_depth, rebase_ref,
                                   workflow_ref=args.workflow_ref)
    line = f"campaign re-arm {reason} -> {detail}"
    # A refused dispatch used to print as the literal text `warning: ...`, which is not a workflow
    # command, so it reached no annotation and no log anyone reads: the chain would have died
    # silently at the one step whose whole job is to keep it alive. Both outcomes are announced.
    print(f"::notice::{line}" if ok else f"::warning::{line}")
    if ok:
        successor, proof = confirm_successor(api, args.repo, token or None, workflow["id"],
                                             args.run_id, delay=args.verify_seconds // 6 or 10)
        if successor is not None:
            print(f"::notice::campaign re-arm confirmed: {proof} (id {successor.get('id')}, "
                  f"pinned at {str(successor.get('head_sha') or '')[:7]})")
        elif proof.startswith("not verified"):
            print(f"campaign re-arm: {proof}")
        else:
            print(f"::error::campaign re-arm {proof}")
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
