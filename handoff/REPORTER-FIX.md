# Reporter fix — the campaigns are running; the comment describing them is not

Date: 2026-10-15. Status: **two UI edits on `main`, no re-pin, no dispatch, no spend, no shell.**
Route B (re-pin a campaign's own code) is kept in §6 for anyone who wants it.

## 1. What is actually wrong

Both pairwise campaigns are alive. Their legs chain, their state artifacts upload, their
re-arms succeed. What is broken is the **live status comment**, and it is broken in three
separate ways, all in one file: `tools/campaign_status_sidecar.py`.

| # | Defect | What a reader sees | Why |
|---|---|---|---|
| 1 | The compatibility probe is invisible | `Campaign state: paused`, `provider_infrastructure_error_compatibility`, and no explanation | A leg that pauses in the Phase 2 READY probe banks no row and writes no `campaign_progress.json`, so every counter stays where the last *banking* leg left it |
| 2 | `Updated` is not the comment's clock | Reasoning-Atria frozen at `Updated: 2026-10-15T05:00:05Z` for ~15 h while six legs chained behind it | `Updated` prints the *checkpoint's* `updated_at`. Nothing in the body proves a reporter ran, so "nothing banked" and "the reporter died" are indistinguishable |
| 3 | The pause reads as terminal | `Campaign state: paused` beside `Leg code: 87f08b5 @ main`, while legs self-chain | The comment reports persisted metadata only; it has no line saying a leg is running now |

Live evidence, both polled at 19:50Z on 2026-10-15 — same code, two symptoms, one cause:

| | issue #20 (Atria, pin `3d6e743`) | issue #21 (Mercury, pin `87f08b5`) |
|---|---|---|
| `Updated` | `2026-10-15T05:00:05Z` — frozen ~15 h | `2026-10-15T19:50:03Z` — live |
| episodes | 170 / 416 | 371 / 416 (+2 since 16:25Z) |
| phase | `exact-instance gate` although the gate reads 189 / 189 | `episodes` |
| pause | `provider_infrastructure_error_compatibility` | `infrastructure_error` |

Mercury's clock moves because its legs bank rows and so write a newer checkpoint.
Atria's does not, because a probe leg banks nothing. Neither comment says why it paused,
or that a leg is running.

## 2. Why this costs nothing, and why it needs no re-pin

Two measurements, both with the repo's own instruments.

**The reporter is not verdict-relevant.** `tools/campaign_status_sidecar.py` is not in
`gate_context.verdict_relevant_files()`:

```
tools/campaign_status_sidecar.py           False
tools/campaign_progress.py                 True    # imported by the reporter; unchanged here
tools/campaign_rearm.py                    False
tools/atria_campaign.py                    True
```

So moving the reporter cannot re-grade a banked gate row, which is why every price in
this document is `free` and none of the campaigns' state has to move.

**The repo already refreshes a non-measurement tool this way.** The launchers' own
re-arm step does not run the pin's `tools/campaign_rearm.py`; it fetches it from the ref
the workflow file came from, under the comment *"The re-arm is operations, not
measurement, so it runs from the ref this workflow file came [from]"*, with a fail-open
`cp` of the pinned copy if the fetch fails. The reporter is operations in exactly that
sense — it renders the checkpoint, it does not produce it — so §4 gives it the same
treatment. That is the whole change: one step, copied from a step that already ships.

## 3. The payloads

Everything below is on the Arena session branch `arena/70337724-rl-eval-generator`
(`main` never carried these files). Read every `handoff/…` path here as "on that branch",
or use the links, which are commit-pinned where the content is frozen:

| What | Where | Size |
|---|---|---|
| The reporter to paste | https://raw.githubusercontent.com/StrangeTcy/rl_eval_generator/09d82c1eee1dca9f62390f577254f6972a90ed44/handoff/paste/campaign_status_sidecar.py | 747 lines, 35038 bytes, sha256 `dfbd9eb110edcec6…` |
| Atria launcher with the step | `handoff/paste/reasoning-atria-pairwise-campaign.yml` on the branch | 698 lines, sha256 `0ce85039d0d4bc78…` |
| Mercury launcher with the step | `handoff/paste/mercury-pairwise-campaign.yml` on the branch | 675 lines, sha256 `5b6c4ebc5928d3ab…` |
| This document | `handoff/REPORTER-FIX.md` on the branch | — |

Copy from the **raw** link (Ctrl+A, Ctrl+C). On a `blob/` page, selecting all also selects
the line-number gutter, and pasting that writes `1`, `2`, `3` … into the file — the
insertion counts in §4 catch it, but copy raw and skip the problem. Or switch the branch
dropdown from `main` to `arena/70337724-rl-eval-generator` and open `handoff/paste/`.

Each launcher payload is its live counterpart **plus exactly the step in §4.2 and nothing
else** — 23 insertions, 0 deletions, verified with `diff` against
`.github/workflows/`. The two launchers are byte-identical to `main`'s copies at the time
of writing, so a whole-file paste is safe; §4.2 also gives the block if you would rather
insert it.

## 4. What to click

### 4.0 Order matters, and it is the only rule here

**Land 4.1 before 4.2.** `main`'s copy of the reporter is currently *older* than the
pins' — it is missing 66 lines they carry, including the `infrastructure_unscored`
handling that Mercury's comment needs for its three closed-unscored `expedition` rows.
Until 4.1 merges, a launcher that reads from `main` would install that older reporter.
Between the two merges the campaigns are unaffected (nothing reads `main`'s reporter
until 4.2 is in), so do 4.1 first and 4.2 a minute later.

### 4.1 Put the reporter on `main` (one paste, one merge)

1. Open https://github.com/StrangeTcy/rl_eval_generator/blob/main/tools/campaign_status_sidecar.py
   — `main` is a branch, so the pencil works here (unlike at a pin, which GitHub refuses
   to edit: *"You must be on a branch to make or propose changes to this file"*).
2. Pencil → select all → delete → paste the raw payload from §3.
3. **Commit changes…** → *Create a new branch for this commit and start a pull request* →
   name it `reporter-heartbeat` → Propose changes → **Merge the pull request**.
4. Verify before or after merging, on the compare page: **1 file changed, 211
   additions(+), 6 deletions(−)**. The deletions are the 6 lines of `main`'s older copy
   that the newer reporter replaces; 145 of the 211 additions are the two fixes, the rest
   is content `main` was missing from the lineage.

Nothing reads this file yet, so this step is invisible to the campaigns. It is also what
makes the file discoverable on `main` instead of only on a session branch.

### 4.2 Teach each launcher to read it (two pastes, one merge each)

For each of the two workflows, in the GitHub web editor on `main` (Actions sidebar →
the workflow → the pencil on the file, or open the file and pencil):

| Launcher | Path |
|---|---|
| Reasoning-Atria pairwise campaign | `.github/workflows/reasoning-atria-pairwise-campaign.yml` |
| Mercury pairwise campaign | `.github/workflows/mercury-pairwise-campaign.yml` |

Either paste the whole payload from §3 over the file, or insert this block — the block is
the entire difference, so both routes end at the same 23-line diff:

```yaml
      # The live-status reporter is not the measurement: it only renders the checkpoint the
      # pinned controller writes, so it is read from main instead of from the pin. This is what
      # lets a reporting fix reach a running campaign without re-pinning it -- and it is why
      # `Updated` alone could not be trusted, since the pin's copy froze whenever a leg banked
      # nothing, which read exactly like a reporter that had died.
      # Fail-open by construction: if main's copy is missing or does not compile, the pin's copy
      # runs and the campaign is unaffected. `--out`, `--pin-file`, the reader the sidecar
      # imports and the interpreter all stay the pin's; the grading digest is computed from a
      # `git archive` of the revision, so editing this one worktree file cannot move it.
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

The block goes **immediately before** the step named
`Run T1 and pairwise campaign with live Issue status` — Ctrl+F that string, and insert
directly above it. If you paste the whole file instead, skip the search: the step is
already in place.

Verification, on the commit or pull-request page for each file: **1 file changed, 23
insertions(+), 0 deletions(−)**. Then merge. Nothing else to change: the two existing
sidecar invocations keep pointing at `tools/campaign_status_sidecar.py`, so the reporter
is replaced *in place* and it still imports the pin's own `tools/campaign_progress.py`,
still writes to the pin's `--out`, and still resolves the pin's `--pin-file`. The state,
the Issue number and the interpreter never move.

### 4.3 Then wait for the next tick — no dispatch, no cancel

`on:` is `workflow_dispatch` plus `schedule: "13,43 * * * *"`, and scheduled runs execute
the workflow file **from the default branch**, as do the self-dispatched successors. So
the very next leg of both campaigns picks the step up on its own. Nothing is re-pinned,
nothing is queued, no state moves, no provider call is made and no banked row is touched.
Atria keeps probing, as decided; its comment simply starts telling the truth about it.

## 5. What the fixed comment will say

Two facts that were already on the machine and were never in the body:

```
- **Updated:** 2026-10-15T05:00:05Z
- **Comment rendered:** 2026-10-15T19:45:56Z, rendered by leg run 38758437040 attempt 1
```

plus, for a leg paused in the probe: the probe's name, its refusal class, its attempt
count, the age of `compatibility.json`, and an explicit line saying why the episode
counter cannot move. `Updated` keeps reporting the checkpoint, because that is a real
fact — it is no longer the only clock in the comment.

## 6. Route B — if you would rather the pin itself carry the reporter

This is the surgical alternative: a **free** re-pin of each campaign to a branch that is
its own pin plus the reporter. No re-graded rows, but it does move campaign state and it
does need a dispatch. GitHub cannot edit a file at a commit SHA, so this route runs in
**github.dev**: open `https://github.dev/StrangeTcy/rl_eval_generator`, Command Palette →
*Git: Checkout to…* → the pin's full SHA → paste the payload over
`tools/campaign_status_sidecar.py` → *Git: Create Branch…* → `reporting-fix-atria` →
Source Control → commit → *Publish Branch*.

Prices, measured with `campaign_rearm.py --check-rebase-target … --check-rebase-against …`
(exit 0, `handoff/reporter-fix-on-*.patch` carry the same change in `git am` form):

| Target | Pin | Price |
|---|---|---|
| `3d6e743` + reporter (`c7b7a66`) | `3d6e743` | **free** — "no verdict-producing file differs, so no banked gate row is re-graded" |
| `7eca038` + reporter (`8446d56`) | `7eca038` | **free** |
| `87f08b5` + reporter | `87f08b5` | **free** |

Then dispatch with `ref` and `rebase_onto_ref` both set to the new branch, `resume_previous`
true, `chain_depth` 0, overrides empty — and mind two field rules that are easy to get
wrong: `ref` is required and defaults to a stale arena branch, and `execution_mode` cannot
promote billing on the rebase path because the mode is read back from the carried intent.

One click is enough for the handover: both launchers set
`concurrency: {group: <campaign>, cancel-in-progress: false}`, so a dispatch queues behind
the in-flight leg; when that leg reaches its re-arm step, `other_legs()` counts the queued
sibling as busy and declines to arm a successor, so the chain hands over rather than
forking.

## 7. What this does not do

* It does not fix either provider problem. Atria still pauses in the Phase 2 READY probe
  until the provider answers, and Mercury still pauses on `infrastructure_error` with 54
  infrastructure retries and two rows sitting at their retry bound.
* It does not fix Mercury's epistemic judge. That is the authorised re-pin to
  `7eca038340cf8638cd12b159d621406003c05d6b` (or to its reporter-bearing descendant
  `668dc13f9d5392f3753d95fa87ea71e7902ef9cc`), which re-grades the 189-row gate over 4
  verdict files and carries the 369-371 banked episode rows forward. Route B's patch for
  that base is `handoff/reporter-fix-on-lineage-tip-7eca038.patch`, so the paid re-pin can
  pick the reporter up for free at the same time.
* It does not re-grade anything, so no banked row is destroyed by doing it.

## 8. Why this is the right shape, not just the cheap one

`docs/decisions/2026-10-15-the-reporter-is-not-the-measurement.md` records the decision:
reporting must not be part of the pin, because a pin is exactly what a campaign cannot
change without re-pricing, and that priced a one-line heartbeat as if it were a judge fix.
The refresh step makes the reporter's home `main` — a ref no campaign pins to — while
leaving every input that defines the measurement in the pin. `vars.CAMPAIGN_REPORTING_REF`
is the escape hatch if the reporter ever needs to come from somewhere else; unset or
unreadable, each leg falls back to its own pinned copy and nothing changes.
