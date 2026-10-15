# The reporter is not the measurement

Date: 2026-10-15. Status: accepted. Supersedes the `path: reporting` sketch in the first
revision of this record, which is preserved under *Alternatives* because it was rejected
for a reason worth keeping.

## Context

A campaign checks out a pinned ref, and the live-status sidecar is invoked from that
checkout. So the reporter that describes a campaign is the reporter its pin happened to
ship — and a pin is precisely what a campaign cannot change without re-pricing. On
2026-10-15 that made a one-line heartbeat look like a judge fix:

* Reasoning-Atria's comment sat at `Updated: 2026-10-15T05:00:05Z` for ~15 hours while
  six legs chained behind it. `Updated` renders the *checkpoint's* timestamp, and a leg
  that pauses inside the Phase 2 READY probe banks no row and writes no
  `campaign_progress.json`, so the frozen clock was correct and still read as a dead
  reporter. Nothing in the body distinguished "nothing new happened" from "the observer
  stopped running" — the one condition an operator must act on.
* Mercury's clock moved (its legs bank rows) but said nothing about *why* it had paused,
  which is the same information gap with a healthier-looking symptom.

The rendering fix is 145 lines in one file, `tools/campaign_status_sidecar.py`. Measured
with `tools/campaign_rearm.py --check-rebase-target`, that file is **not** in
`gate_context.verdict_relevant_files()`, so a pin differing only in the reporter moves no
verdict-producing file and re-grades no banked row. Free or not, a re-pin still moves
campaign state, still needs a dispatch slot inside a chain that guards its own slot, and
still needs a branch based on a commit SHA — which GitHub's web UI refuses to create
("You must be on a branch to make or propose changes to this file"). A fix that is free
but unreachable is not a fix.

The repository already answered this shape of question once. The launchers' re-arm step
does not run the pin's `tools/campaign_rearm.py`; it fetches that file from the ref the
*workflow* came from, with a fail-open `cp` of the pinned copy as the fallback, under the
comment *"The re-arm is operations, not measurement, so it runs from the ref this workflow
file came [from]"*. Reporting is operations in exactly that sense: it renders the
checkpoint, it does not produce it.

## Decision

Each leg refreshes the reporter **in place** from a *reporting ref* before the campaign
step runs, and falls back to the pin's own copy if that fetch fails:

```yaml
      - name: Refresh the live-status reporter from main
        if: steps.mode.outputs.mode != 'none'
        continue-on-error: true
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          set -euo pipefail
          REPORTER="$RUNNER_TEMP/campaign_status_sidecar.py"
          if gh api "repos/${{ github.repository }}/contents/tools/campaign_status_sidecar.py?ref=${{ vars.CAMPAIGN_REPORTING_REF || 'main' }}" --jq '.content' | base64 -d > "$REPORTER" 2>/dev/null && [ -s "$REPORTER" ] && .venv/bin/python -m py_compile "$REPORTER"; then
            cp "$REPORTER" tools/campaign_status_sidecar.py
            echo "reporter refreshed from main: $(sha256sum tools/campaign_status_sidecar.py | cut -c1-12)"
          else
            echo "reporter stays the pin's copy: main's copy unreadable or not valid Python"
          fi
```

The reporting ref defaults to `main` and can be repointed with the repository variable
`CAMPAIGN_REPORTING_REF` without touching a workflow again.

## Why in place, rather than checked out beside the pin

The first revision of this record proposed a second `actions/checkout` of a reporting ref
at `path: reporting`, and invoking `reporting/tools/campaign_status_sidecar.py`. It has
one disqualifying property: the sidecar's `ROOT` is derived from its own file location and
it imports `tools.campaign_progress.read_progress` from there. A reporting checkout brings
its **own reader**, so the reader would leave the pin — a schema-skew risk between "the
code that wrote the state" and "the code that interprets it", in exchange for nothing.

Replacing the file in the pinned worktree keeps every input that defines the measurement
where it was:

| Stays the pin's | Because |
|---|---|
| `--out` (the state directory) | still resolved relative to the workspace root, which is the pin's |
| `--pin-file` (the Issue number) | same; and `main` has no pairwise `experiments/` files at all |
| `tools/campaign_progress.py` (the reader) | byte-identical at `3d6e743`, `87f08b5`, `7eca038` and the session branch, and now structurally guaranteed to stay so |
| `.venv/bin/python` (the interpreter) | unchanged invocation |
| the checked-out commit | the pin is still the pin; only one file's *content* is newer, which is why §5 of the handover can still say `Leg code: <sha>` |

Two further reasons the separate checkout loses: it puts a nested `.git` inside the
campaign worktree (state artifacts come from `$RUNNER_TEMP/..._upload`, so nothing else
depends on the worktree being clean — but there is no reason to invite the question), and
it requires editing two invocation sites per launcher where this requires editing none.

## Why `main`, rather than the workflow's own ref

`campaign_rearm.py` is fetched from `${{ github.sha }}` because the re-arm is dispatched
by the workflow itself, so that ref is always the one that carried the dispatch. A human
operator may dispatch from anywhere — the `ref` input's default is a months-old arena
branch — and the reporter must be at least as new as the oldest pin in play. An explicit,
variable-backed reporting ref makes that choice visible instead of incidental.

## Invariants

1. **The reporting ref must be at least as new as any pin.** Otherwise the refresh is a
   downgrade. This is a deployment ordering rule, not something the step can detect: it
   verifies that the fetched file is non-empty and compiles, which catches a 404 body or
   an HTML error page, but cannot tell an older reporter from a newer one. At the time of
   writing, `main`'s copy is 66 lines behind the pins', so the reporter lands on `main`
   **before** any launcher starts reading it.
2. **Nothing that defines the measurement moves.** `--out`, `--pin-file`, the reader, the
   interpreter and the pinned commit are all the pin's. `tests/test_reporter_refresh_handoff.py`
   asserts that the refresh step runs immediately before the campaign step, that both
   sidecar invocations still call `tools/campaign_status_sidecar.py` in place, and that no
   `reporting/` path appears in them.
3. **The refresh can never fail a leg.** `continue-on-error: true`, and the worktree copy
   is replaced only inside the guarded branch; the else-branch keeps the pin's copy.
4. **The grading digest cannot move.** `campaign_rearm.grading_context()` computes it by
   extracting a revision with `git archive` into a temporary tree and running *that tree's*
   `tools/gate_context.py` — never the live worktree. The reporter is also not in
   `verdict_relevant_files()`, so even a digest taken from the worktree would not include it.

## Alternatives

* **Re-pin the campaign to a branch that is the pin plus the reporter.** Measured `free`
  for all three pins, and kept in the handover as Route B, with `git am`-ready patches.
  Rejected as the primary route because it needs a branch based on an unreferenced SHA
  (not creatable in the GitHub UI), a dispatch that competes with the chain's own busy
  guard, and a state handover — for a change that is definitionally not part of the
  measurement. It remains the right move when a *verdict* fix must reach a pin, which is
  exactly what Mercury's authorised re-pin does.
* **Check the reporter out beside the pin (`path: reporting`).** Rejected above: it moves
  the reader out of the pin.
* **Leave the reporter in the pin and hand-run the fix.** Rejected: it makes every future
  reporting improvement cost a re-grade decision, which is how the heartbeat came to look
  like a judge fix in the first place.
* **Have the reporter render its own provenance** (e.g. a `REPORTER_VERSION` constant the
  refresh compares against the pin's copy, turning invariant 1 into a check rather than a
  promise). Deferred, not rejected: it changes the payload, and the ordering rule is
  cheap to honour. It is the natural next step if a second reporting fix ever appears.

## Consequences

* A reporting fix is now a paste to `main`; no re-pin, no dispatch, no spend, no movement
  of banked rows, and no dependence on an operator having a shell.
* The comment can be newer than the code it describes, by design. The render line names
  the leg that produced it, and `Leg code: <sha>` continues to name the pin.
* The reason `main` could not be a reporting ref in the first revision — no pairwise
  `experiments/` files — turns out not to apply to this design, because the refresh
  fetches one file by path rather than checking out a tree. Mirroring those configs to
  `main` is still outstanding if anyone wants to *pin* a campaign to `main`, and is no
  longer on the critical path for reporting.
