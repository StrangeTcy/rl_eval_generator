# Reporter fix — the campaigns are running; the comment describing them is not

Date: 2026-10-15. Status: **patches built and priced; they need a push and a click, neither of which this session's credential can do.**

## 1. What is actually wrong

Both pairwise campaigns are alive. Their legs chain, their state artifacts upload,
their re-arms succeed. What is broken is the **live status comment**, and it is
broken in three separate ways, all in one file: `tools/campaign_status_sidecar.py`.

| # | Defect | What a reader sees | Why |
|---|---|---|---|
| 1 | The compatibility probe is invisible | `Campaign state: paused`, `provider_infrastructure_error_compatibility`, and no explanation | A leg that pauses in the Phase 2 READY probe banks no row and writes no `campaign_progress.json`, so every counter in the comment stays where the last *banking* leg left it |
| 2 | `Updated` is not the comment's clock | Reasoning-Atria frozen at `Updated: 2026-10-15T05:00:05Z` for eleven hours while six legs chained behind it | `Updated` prints the *checkpoint's* `updated_at`. Nothing in the comment proves a reporter ran at all, so "nothing banked" and "the reporter died" are indistinguishable |
| 3 | The pause reads as terminal | `Campaign state: paused` next to `Leg code: 87f08b5 @ main`, while legs self-chain every ~23 min | The comment reports persisted metadata only; it has no line saying a leg is currently running and will re-arm |

Defects 1 and 2 are fixed by the patches here. Defect 3 is a wording problem the
same file can carry, and it is listed in
`docs/decisions/2026-10-15-the-reporter-is-not-the-measurement.md` as the durable
fix: stop making the reporter part of the pin at all.

## 2. Why this is free

`tools/campaign_status_sidecar.py` is **not** in `gate_context.verdict_relevant_files()`.
Measured on this branch:

```
tools/campaign_status_sidecar.py           False
tools/campaign_progress.py                 True      # imported by the sidecar, but unchanged here
tools/campaign_rearm.py                    False
tools/campaign_supervisor.py               False
tools/atria_campaign.py                    True
```

So a pin whose **only** difference from a campaign's current pin is the reporter
moves no verdict-producing file, and `tools/campaign_rearm.py` says so itself:

```
campaign rebase check: `e0a1bcc…` -> free at e0a1bcc
campaign rebase check: no verdict-producing file differs, so no banked gate row is re-graded
```

All four pairings, priced with the repo's own instrument (exit 0 each):

| Target | Pin | Price | Verdict files re-graded |
|---|---|---|---|
| `78294edc2a80fb4e154ce7da794633795ee629fa` (Mercury pin + reporter) | `87f08b5` | **free** | none |
| `e0a1bccefd69d6895af9312e609078df264c8594` (Atria pin + reporter) | `3d6e743` | **free** | none |
| `668dc13f9d5392f3753d95fa87ea71e7902ef9cc` (lineage tip + reporter) | `87f08b5` | costly | 4 — `arena/episode.py`, `envs/epistemic_silence/files/core.py`, `envs/epistemic_type_games/files/core.py`, `tools/run_suite.py` |
| `668dc13f9d5392f3753d95fa87ea71e7902ef9cc` (lineage tip + reporter) | `3d6e743` | costly | same 4 |

The two `costly` rows are the **judge fix** (`truth_correct`), not the reporter:
`668dc13` is the lineage tip `7eca038` with the reporter on top, so it carries the
epistemic-judge repair too. Adding the reporter to it costs nothing extra.

Each candidate differs from its base in exactly two files, and all 28 sidecar tests
pass at each one:

```
tests/test_campaign_status_sidecar.py
tools/campaign_status_sidecar.py
```

## 3. The patches

Three `git format-patch` files in this directory, one per base. Each is a **single
commit whose parent is the base**, so `git am` onto that base reproduces the exact
SHA in the table above (`git apply` also works; it just drops the message).

| Patch | Applies onto | Produces |
|---|---|---|
| `reporter-fix-on-lineage-tip-7eca038.patch` | `7eca038` | `668dc13f9d5392f3753d95fa87ea71e7902ef9cc` |
| `reporter-fix-on-atria-pin-3d6e743.patch` | `3d6e743` | `e0a1bccefd69d6895af9312e609078df264c8594` |
| `reporter-fix-on-mercury-pin-87f08b5.patch` | `87f08b5` | `78294edc2a80fb4e154ce7da794633795ee629fa` |

## 4. What to run

### 4.1 Reasoning-Atria (issue #20) — free, do this one first

`e0a1bcc`'s parent is Atria's pin `3d6e743`, which is *not* the lineage tip, so it
needs its own branch (pushing it to the lineage would not fast-forward):

```bash
git fetch origin arena/b060c411-rl-eval-generator
git checkout -b reporting-fix-atria 3d6e743
git am handoff/reporter-fix-on-atria-pin-3d6e743.patch
git rev-parse HEAD          # must print e0a1bccefd69d6895af9312e609078df264c8594
git push origin reporting-fix-atria
```

Then re-pin the campaign to it (Actions → Reasoning-Atria pairwise campaign → Run
workflow → branch `main`), or:

```bash
gh workflow run reasoning-atria-pairwise-campaign.yml --ref main \
  -f rebase_onto_ref=e0a1bccefd69d6895af9312e609078df264c8594 \
  -f ref=e0a1bccefd69d6895af9312e609078df264c8594 \
  -F resume_previous=true -f chain_depth=0
```

Leave `execution_mode` at its default: the rebase branch reads the mode back out of
the carried `campaign_intent.json`, so the dropdown cannot promote billing.

This does **not** cancel the probe legs and does not disturb the standing "leave it
probing" decision. It changes what the next leg *says*. The 170 banked rows and the
plan are untouched; the pause stays until the provider answers the READY probe.

### 4.2 Mercury (issue #21) — rides the re-pin you already authorised

You chose `rebase` onto the lineage tip `7eca038`. Apply the reporter on top first,
so the one costly re-grade buys both fixes:

```bash
git fetch origin arena/b060c411-rl-eval-generator
git checkout -b reporting-fix-mercury 7eca038
git am handoff/reporter-fix-on-lineage-tip-7eca038.patch
git rev-parse HEAD          # must print 668dc13f9d5392f3753d95fa87ea71e7902ef9cc
```

`668dc13`'s parent *is* the lineage tip, so this can go straight onto that branch
instead of a new one, if you prefer to keep the lineage linear:

```bash
git push origin 668dc13f9d5392f3753d95fa87ea71e7902ef9cc:arena/b060c411-rl-eval-generator
```

Then dispatch with the reporter included — the only change from the command handed
over earlier is the SHA:

```bash
gh workflow run mercury-pairwise-campaign.yml --ref main \
  -f rebase_onto_ref=668dc13f9d5392f3753d95fa87ea71e7902ef9cc \
  -f ref=668dc13f9d5392f3753d95fa87ea71e7902ef9cc \
  -f execution_mode=paid -F resume_previous=true -f chain_depth=0
```

Price, unchanged from `7eca038`: the 189-row exact-instance gate is re-graded over
the 4 verdict files above; the 369 banked episode rows ride along; `experiments/`
is byte-identical pin → target, so provider, model, endpoint, effort, ceilings and
profile did not move.

If you would rather **not** pay that re-grade yet but still want Mercury's comment
to tell the truth, `reporter-fix-on-mercury-pin-87f08b5.patch` is the free
interim: it produces `78294ed` on a branch off `87f08b5`, priced `free`. The judge
fix then stays outstanding, and Mercury keeps destroying the ~5 remaining
`epistemic_silence` / `epistemic_type_games` rows it has not reached.

## 5. One click is enough — nothing needs cancelling

Both launchers set `concurrency: {group: <campaign>, cancel-in-progress: false}`, so
a dispatch **queues** behind the in-flight leg instead of racing it. When that leg
reaches its re-arm step, `tools/campaign_rearm.py:other_legs()` excludes only its own
run id and treats a `queued` sibling as busy (`BUSY_RUN_STATUSES`), so it declines to
arm a successor — the old chain ends there, and the re-pinned leg arms the next one.
The chain hands over cleanly; two chains do not run in parallel.

This session's credential gets **HTTP 403** on `actions/workflows/*/dispatches`, on
`actions/runs/*/cancel`, and on pushes to any branch other than
`arena/70337724-rl-eval-generator`, which is why the fix arrives as patches rather
than as a dispatched run.

## 6. What the fixed comment will say

Two new facts, both already on the machine and neither previously in the body:

```
- **Updated:** 2026-10-15T05:00:05Z
- **Comment rendered:** 2026-10-15T19:45:56Z, rendered by leg run 38758437040 attempt 1
```

plus, for a leg paused in the probe: the probe's name, its refusal class, its attempt
count, the age of `compatibility.json`, and an explicit line saying why the episode
counter cannot move. `Updated` keeps reporting the checkpoint — that is a real fact —
but it is no longer the only clock in the comment.
