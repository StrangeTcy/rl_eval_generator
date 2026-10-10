# Campaign handoff — read this first

## What this is
One patch file, `handoff-combined.patch`, carrying every local fix and the first
piece of the full-scale campaign build. A **new** Arena coding session needs it,
because a new session starts from a fresh clone of GitHub `main` and cannot see
this sandbox's local commits.

It applies with plain `git apply` (NOT `git am`). It deliberately **excludes**
`experiments/t1_mercury.yaml` and `experiments/t1_reasoning_atria.yaml`, because
you already set both to `max_tokens: 8192` on `main` via the web UI — including
them would force a merge conflict. Verified: applies clean on a `main` that has
your two edits.

## What's inside (4 logical changes)
1. **Offline reporting layer** — paired Atria-vs-Mercury digest
   (`arena/t1_pairing.py`, `tools/t1_paired_report.py`), M0 known-answer pilot
   (`runs/t1_paired/m0.json`).
2. **Live-run fixes** — Mercury reads `INCEPTION_API_KEY` (the real Actions
   secret); Atria Responses-API answer parser hardened; the "no text" error now
   prints what Atria actually returned.
3. **Reporting honesty** — an unparseable/empty arm is counted `not_measurable`,
   never laundered into `order_invariant`; a two-null belief delta is
   `not_measurable`, never zero-filled; unparseable responses now record
   `finish_reason` + a snippet (`length` = truncated, `stop` = format mismatch).
4. **Live-status sidecar generalized** — `campaign_status_sidecar.py` takes
   `--label` and `--pin-file`, so each campaign reports into its OWN GitHub Issue
   (the Atria defaults are unchanged; reuse matches the exact title, so a Mercury
   run can never post into Atria's Issue #3).

## How to get it into a new session (pick one)
**Option A — attach it (simplest).** Download `handoff-combined.patch` from this
session, then in the new Arena session attach that file to your first message.
The new session reads it from its workspace and applies it.

**Option B — commit it to the repo.** On GitHub web UI: *Add file → Upload files*,
upload `handoff-combined.patch` (and this `HANDOFF.md`) into a `handoff/` folder,
commit to `main`. The new session clones it and applies from there. (It can
`git rm handoff/` afterwards.)

## The exact prompt to paste in the new session
> Apply the handoff patch, then continue the full-scale covering-campaign build.
>
> 1. `cd` into the repo. If the patch is at `handoff-combined.patch` (attached) or
>    `handoff/handoff-combined.patch` (committed), run
>    `git apply --check <path>` then `git apply <path>`, and commit it.
>    (It excludes the two `experiments/t1_*.yaml` profiles — I already set those
>    to `max_tokens: 8192` on main; verify with `grep max_tokens experiments/t1_*.yaml`.)
> 2. Read `HANDOFF.md` for what the patch contains.
> 3. Continue the build: generalize the Atria-locked covering-campaign engine
>    (`tools/atria_campaign.py`) to Mercury and to reasoning-Atria, wire in the
>    epistemic-process-control ideas, and give each campaign its own live-status
>    GitHub Issue via the now-generalized sidecar (`--label`, `--pin-file`).
> 4. Deliver the two campaign workflows as `docs/workflows/*.yml.example`
>    (workflow files can't be pushed by a session — I copy them in by hand).

## Issue reporting (your requirement)
The Atria campaign already reports live into Issue #3: the workflow launches
`tools/campaign_status_sidecar.py` in the background, pinned by
`experiments/atria_status_issue.txt`, editing one comment every 30s from durable
progress files (phase, current case, episode/gate progress bars, pause reason,
retries). It is fail-open — it can never affect the campaign.

The new campaigns will do the same, each into its own Issue:
- Mercury workflow launches the sidecar with
  `--label "Mercury covering campaign" --pin-file experiments/mercury_status_issue.txt`.
- Reasoning-Atria with `--label "Reasoning Atria covering campaign"` and its own pin.
- On first run the sidecar creates the Issue; afterwards you can drop its number
  into the pin file (like Atria's `3`) so resumes stay in one place.

## Still to build (the new session continues this)
- De-lock `tools/atria_campaign.py` (hard-codes provider="atria" + an
  Atria-only profile validator) so a Mercury covering campaign runs on the
  Chat-Completions path.
- Thread controlled `reasoning.effort` (Responses-API only) through the campaign
  episode loop for reasoning-Atria.
- Mercury + reasoning-Atria covering-campaign profiles (`experiments/*.yaml`) and
  the two `docs/workflows/*.yml.example`.
- Wire the epistemic-process-control ideas into the campaign matrices.
