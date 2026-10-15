# The reporter is not the measurement: stop pinning `campaign_status_sidecar.py`

Date: 2026-10-15. Status: **proposed; needs a workflow-file push, which this session's credential cannot make (HTTP 403 on workflow paths).**

## 1. The problem this ends

Both pairwise launchers check out the pin **over the workspace root**:

```yaml
      - name: Check out pinned campaign code
        if: steps.mode.outputs.mode != 'none'
        uses: actions/checkout@v4
        with:
          ref: ${{ steps.mode.outputs.ref }}
          fetch-depth: 0
```

and then start the reporter from that root, twice — a background loop and a final
`--once` in the `cleanup` trap:

```bash
          .venv/bin/python tools/campaign_status_sidecar.py \
            --out "$OUT" --label "Reasoning-Atria pairwise campaign" \
            --pin-file experiments/reasoning_atria_pairwise_status_issue.txt \
            --interval-seconds 30 &
```

There is no `path:` on the checkout, so `tools/campaign_status_sidecar.py` **is the
pin's copy**. Every consequence follows from that one line:

- A reporting bug can only be fixed by re-pinning the campaign, and a re-pin is the
  most expensive operation the campaign has: it re-grades the 189-row exact-instance
  gate over every verdict-producing file that moved.
- The fix is unreachable while a campaign is mid-flight, because the pin is what the
  legs are running. Reasoning-Atria's comment sat frozen at
  `Updated: 2026-10-15T05:00:05Z` for eleven hours across six chained legs, and the
  code that would have explained why was one commit away and could not be reached.
- Reporting regressions are coupled to measurement risk. They should not be: the
  sidecar is fail-open by design ("its failure cannot affect the campaign") and it is
  **not** in `gate_context.verdict_relevant_files()`, so it cannot change a verdict
  even in principle.

## 2. Decision

The reporter runs from a **reporting ref**, checked out beside the pin, never from
the pin itself. The pin stays the sole source of measurement: gates, episodes,
verdicts, ceilings, the issue number.

## 3. The change

Add one checkout, after the pinned one:

```yaml
      - name: Check out reporting code
        if: steps.mode.outputs.mode != 'none'
        uses: actions/checkout@v4
        with:
          ref: ${{ inputs.reporting_ref }}
          path: reporting
          fetch-depth: 1
        continue-on-error: true
```

with a new `workflow_dispatch` input next to `rebase_onto_ref`:

```yaml
      reporting_ref:
        description: >-
          Ref the live Issue comment is rendered from. Reporting only: it cannot
          change a gate row, an episode row, a ceiling or the pin. Defaults to the
          pinned ref, which is today's behaviour.
        required: false
        default: ""
```

and resolve it, failing open to the pin, in the step that launches the reporter:

```bash
          REPORTER=tools/campaign_status_sidecar.py
          REPORTING_REF="${{ inputs.reporting_ref }}"
          if [ -n "$REPORTING_REF" ] && [ -f reporting/tools/campaign_status_sidecar.py ]; then
            REPORTER=reporting/tools/campaign_status_sidecar.py
          fi
          .venv/bin/python "$REPORTER" \
            --out "$OUT" --label "Reasoning-Atria pairwise campaign" \
            --pin-file experiments/reasoning_atria_pairwise_status_issue.txt \
            --interval-seconds 30 &
```

The same substitution in the `cleanup` trap's `--once` call. Note what deliberately
does **not** move:

- `--out "$OUT"` and `--pin-file experiments/…` stay relative to the working
  directory, i.e. the **pinned** root. The state being reported and the Issue being
  written to remain the pin's.
- `.venv/bin/python` stays the pinned interpreter. Measured: the sidecar is
  stdlib-only (`argparse`, `json`, `os`, `sys`, `time`, `urllib`, `datetime`,
  `pathlib`, `typing`) and posts via `urllib.request`, so the reporting copy needs no
  dependencies of its own.
- `continue-on-error: true` plus the `[ -f … ]` test keep the whole thing fail-open:
  a missing or broken reporting ref degrades to today's behaviour, never to a leg
  that fails.

## 4. The one real coupling, and its guard

The sidecar resolves its own root from `__file__` and imports
`tools.campaign_progress.read_progress` from there, so a reporting checkout brings
its **own reader**. `tools/campaign_progress.py` is verdict-relevant — but only
through its writer, which the campaign calls from the pinned tree. The reporter's
reader cannot alter a verdict; the honest risk is narrower and worth stating: a
schema skew between the pinned writer and a newer reader silently blanks fields in
the comment, which is the exact failure mode this decision exists to remove.

Guard it with a test rather than with discipline: render a state directory written by
the pinned `write_progress` using the newest `read_progress`, and assert no field goes
missing. `tests/test_campaign_status_sidecar.py` already builds state directories
through `write_progress`, so the assertion is a small addition to an existing file.

## 5. Why the reporting ref cannot simply be `main`

Measured: `main`'s `experiments/` contains no pairwise files at all — only
`atria_*`, `mercury_covering_*`, `reasoning_atria_covering_*`, `nim_first5`,
`rehearsal*` and `t1_*`. The pairwise campaigns' `*_pairwise_campaign.yaml` and
`*_pairwise_status_issue.txt` exist **only** on the lineage
(`refs/arena/b060c411` → `7eca038`). A `main` checkout therefore has the reporter but
not the pin file it is told to read, and the launchers' `test -f` gate checks would be
checking a tree that is missing the campaign's own configuration.

Two ways out, either acceptable:

1. Point `reporting_ref` at a lineage-tracking branch (or a small branch kept current
   with the reporter only). Costs nothing today.
2. Mirror the pairwise `experiments/` files to `main` first, then `main` becomes a
   valid reporting ref. This is the better long-term shape — it also removes the
   asymmetry that made this session's diagnosis depend on fetching a private ref — but
   it is a separate change with its own review.

Until one of those lands, the reporting fix ships as a re-pin, which for a
reporter-only delta is measured `free`: `campaign_rearm.py --check-rebase-target`
answers *"no verdict-producing file differs, so no banked gate row is re-graded"*.
See `handoff/REPORTER-FIX.md` for the patches and the exact commands.

## 6. Consequences

- Reporting fixes stop costing a re-pin and stop being blocked by an in-flight
  campaign. The next frozen-comment incident is a dispatch input, not a re-grade.
- The comment becomes attributable: which reporter rendered it is a workflow input
  recorded in the run, instead of an inference from the pin.
- The pin's meaning sharpens. It is the measurement contract and nothing else; a
  file that cannot change a verdict does not belong inside it.
- Nothing about gates, episodes, ceilings, billing or re-arm cadence changes. The
  reporter is already fail-open, and this keeps it that way.
