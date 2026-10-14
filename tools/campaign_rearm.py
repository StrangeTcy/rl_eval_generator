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
                  sleep_cap: int | None = DEFAULT_SLEEP_CAP) -> int:
    """Seconds this leg should sit before asking, or 0 when no wait could make a successor acceptable."""
    state = _floor_state(report, newest_run, now, min_interval_seconds)
    if state is None:
        return 0
    reason = str(report.get("pause_reason") or "")
    if reason in LEDGER_GOVERNING_REASONS:
        return 0
    floor, age = state
    wait = int(floor - age)
    if wait <= 0:
        return 0
    if sleep_cap is not None and wait > int(sleep_cap):
        return 0
    return wait


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
        return False, (
            f"pause_reason={reason!r} is metered by the campaign's per-case attempt ledger, which the next "
            "leg would consume on the same failing case without producing the row; the scheduled tick is "
            "the wait that can actually help here"
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
    if run_status in BUSY_RUN_STATUSES:
        return False, f"a leg is already {run_status}; the concurrency group would only queue another"
    started = _parse_timestamp(newest_run.get("updated_at")) or _parse_timestamp(newest_run.get("created_at"))
    if started is None:
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
    detail = " ".join(str(recorded.get("detail") or "").split())[:240]
    return (
        f"terminal marker {name} is present (pause_reason={reason}"
        + (f"; {detail}" if detail else "")
        + "), so the campaign stopped on purpose"
    )



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
                      chain_depth: int = 0, rebase_ref: str = "") -> tuple[bool, str]:
    inputs = successor_inputs(ref, chain_depth, rebase_ref)
    payload = json.dumps({"inputs": inputs}).encode("utf-8")
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
    parser.add_argument("--dry-run", action="store_true", help="print the decision without dispatching")
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
    )
    if not decision:
        # The refusal may be purely temporal, in which case the fix is to wait, not to hand the
        # campaign back to a schedule that delivered three ticks today.
        wait = handover_wait(report, newest_run, now, min_interval_seconds=args.min_interval_seconds,
                             sleep_cap=args.sleep_cap)
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
            )
    if not decision:
        # A decline is a decision, and it must not live only in a log nobody opens: like the refused-tick
        # announcement, this reaches the Checks UI and the jobs API.
        print(f"campaign re-arm skipped: {reason}")
        print(f"::warning::campaign re-arm declined: {reason}")
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
    if args.dry_run:
        print(f"campaign re-arm would dispatch: {reason} (dry run)")
        return 0
    ok, detail = dispatch_next_leg(api, args.repo, token or None, workflow["id"], args.ref,
                                   args.chain_depth, rebase_ref)
    line = f"campaign re-arm {reason} -> {detail}"
    print(f"::notice::{line}" if ok else f"warning: {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
