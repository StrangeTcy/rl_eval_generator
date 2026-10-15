# Reporter fix — the campaigns are running; the comment describing them is not

Date: 2026-10-15. Status: **one file to paste, priced `free`; every step below is browser-only — no `git`, no `gh`.**

## 1. What is actually wrong

Both pairwise campaigns are alive. Their legs chain, their state artifacts upload,
their re-arms succeed. What is broken is the **live status comment**, and it is
broken in three separate ways, all in one file: `tools/campaign_status_sidecar.py`.

| # | Defect | What a reader sees | Why |
|---|---|---|---|
| 1 | The compatibility probe is invisible | `Campaign state: paused`, `provider_infrastructure_error_compatibility`, and no explanation | A leg that pauses in the Phase 2 READY probe banks no row and writes no `campaign_progress.json`, so every counter in the comment stays where the last *banking* leg left it |
| 2 | `Updated` is not the comment's clock | Reasoning-Atria frozen at `Updated: 2026-10-15T05:00:05Z` for ~15 h while legs chained behind it | `Updated` prints the *checkpoint's* `updated_at`. Nothing in the comment proves a reporter ran at all, so "nothing banked" and "the reporter died" are indistinguishable |
| 3 | The pause reads as terminal | `Campaign state: paused` next to `Leg code: 87f08b5 @ main`, while legs self-chain | The comment reports persisted metadata only; it has no line saying a leg is running right now |

Defects 1 and 2 are fixed by the file in §3. Defect 3 is wording the same file can
carry later, and the durable shape — stop making the reporter part of the pin at all —
is `docs/decisions/2026-10-15-the-reporter-is-not-the-measurement.md`.

Live evidence, both polled at 19:50Z on 2026-10-15. Same code, two symptoms, one cause:

| | issue #20 (Atria, pin `3d6e743`) | issue #21 (Mercury, pin `87f08b5`) |
|---|---|---|
| `Updated` | `2026-10-15T05:00:05Z` — frozen ~15 h | `2026-10-15T19:50:03Z` — live |
| episodes | 170 / 416 | 371 / 416 (+2 since 16:25Z) |
| phase | `exact-instance gate` although the gate reads 189 / 189 | `episodes` |
| pause | `provider_infrastructure_error_compatibility` | `infrastructure_error` |

Mercury's clock moves because its legs bank rows and so write a newer checkpoint.
Atria's does not, because a probe leg banks nothing. Neither comment says why it
paused, or that a leg is running.

## 2. Why this is free

`tools/campaign_status_sidecar.py` is **not** in `gate_context.verdict_relevant_files()`.
Measured on this branch:

```
tools/campaign_status_sidecar.py           False
tools/campaign_progress.py                 True      # imported by the sidecar, unchanged here
tools/campaign_rearm.py                    False
tools/campaign_supervisor.py               False
tools/atria_campaign.py                    True
```

So a pin whose **only** difference from a campaign's current pin is the reporter moves
no verdict-producing file, and `tools/campaign_rearm.py` says so itself:

```
campaign rebase check: `c7b7a66…` -> free at c7b7a66
campaign rebase check: no verdict-producing file differs, so no banked gate row is re-graded
```

Prices, measured with the repo's own instrument, for the **single-file** change you
will actually make (`--check-rebase-target <target> --check-rebase-against <pin>`, exit 0):

| Target tree | Pin | Price | Verdict files re-graded |
|---|---|---|---|
| `3d6e743` + reporter (`c7b7a66`) | `3d6e743` | **free** | none |
| `7eca038` + reporter (`8446d56`) | `7eca038` | **free** | none |
| `87f08b5` + reporter | `87f08b5` | **free** | none |
| lineage tip + reporter | `87f08b5` (Mercury's pin) | costly | 4 — `arena/episode.py`, `envs/epistemic_silence/files/core.py`, `envs/epistemic_type_games/files/core.py`, `tools/run_suite.py` |
| lineage tip + reporter | `3d6e743` (Atria's pin) | costly | same 4 |

Read the last two rows carefully: the cost there is the **judge fix** (`truth_correct`)
that already sits in the lineage tip, not the reporter. Adding the reporter to that tip
is free; re-pinning a campaign *to* that tip is what re-grades the gate.

At each of the three bases, changing only this one file leaves the base's own
sidecar-touching tests green — 38 tests across
`test_campaign_status_sidecar.py`, `test_campaign_status_issue_selection.py`,
`test_campaign_status_t1_progress.py`, `test_paid_campaign_safety.py`. So the test file
does **not** have to travel with it.

## 3. The one file

`handoff/paste/campaign_status_sidecar.py`

```
747 lines
sha256 dfbd9eb110edcec66ac33f016ab587f063d68489675cfac9d2a8ce68cd040cb2
```

It is byte-identical for all three bases — the reporter never diverged across
`87f08b5`, `3d6e743` and `7eca038`, so one paste serves any of them. Whichever base
you paste it onto, the result is **1 file changed, 145 additions(+), 0 deletions(−)**,
and that number is your verification in §4 step 5.

The three `handoff/reporter-fix-on-*.patch` files are the same change in `git am`
form, kept for a future session that does have a shell. They are not needed here.

## 4. What to click

### 4.1 Reasoning-Atria (issue #20) — free, about four minutes

1. Open the reporter **at Atria's pin**:
   `https://github.com/StrangeTcy/rl_eval_generator/blob/3d6e743/tools/campaign_status_sidecar.py`
2. Click the pencil (edit). In the editor: select all, delete, then paste the whole of
   `handoff/paste/campaign_status_sidecar.py`.
3. **Commit changes…** — because you are viewing a commit rather than a branch,
   GitHub's only offer is *Create a new branch for this commit and start a pull
   request*. Name it `reporting-fix-atria`, then Propose changes.
   This step is what guarantees the base: the new branch is `3d6e743` plus your one
   commit, which is exactly the tree priced `free` above.
4. **Close the pull request it opens. Do not merge it.** The branch is the artifact;
   the campaign reads the branch, never the PR.
5. Verify on
   `https://github.com/StrangeTcy/rl_eval_generator/compare/3d6e743...reporting-fix-atria?expand=1`
   — it must read **1 file changed, 145 additions(+), 0 deletions(−)**. Anything else
   means the paste gained or lost text: don't dispatch, redo step 2.
6. Copy the 40-character commit SHA shown at the top of that page.
7. Actions sidebar → **Reasoning-Atria pairwise campaign** → **Run workflow** →
   Branch: `main`, then fill exactly this:

   | Field | Value |
   |---|---|
   | `ref` | the SHA — required field, and its default is a stale arena branch, so overwrite it |
   | `rebase_onto_ref` | the same SHA |
   | `execution_mode` | leave `paid`. The rebase path reads the mode back out of the carried `campaign_intent.json`, so this dropdown can neither promote nor demote what is authorised to bill |
   | `resume_previous` | leave `true` |
   | `clear_wrapper_stop` | leave `false` — it lifts a harness-crash stop only, never a compatibility refusal |
   | `chain_depth` | leave `0` |
   | `max_tokens_total_override`, `max_api_calls_override` | leave empty |

   Then **Run workflow**.
8. Within about two minutes of the new leg starting, issue #20 gains the
   `Comment rendered:` line and the probe section. The pause itself stays until the
   provider answers the READY probe — that is the standing "leave it probing"
   decision, and this does not disturb it, cancel a leg, or touch the 170 banked rows.

No-paste alternative for steps 1–4: press `.` on the repo page to open github.dev,
open commit `3d6e743`, create branch `reporting-fix-atria`, drag
`campaign_status_sidecar.py` onto the `tools/` folder, commit from Source Control.
Same tree, same price.

### 4.2 Mercury (issue #21) — same file, two destinations

**B1 — free interim (reporter only).** Repeat 4.1 starting from
`https://github.com/StrangeTcy/rl_eval_generator/blob/87f08b5/tools/campaign_status_sidecar.py`,
branch `reporting-fix-mercury`, and dispatch **Mercury pairwise campaign** with the
same field values. Price vs `87f08b5`: free. The judge fix stays outstanding, so
Mercury keeps destroying the ~5 `epistemic_silence` / `epistemic_type_games` rows it
has not reached yet.

**B2 — the re-pin you already authorised (judge fix + reporter).** Open the file on the
lineage branch instead:
`https://github.com/StrangeTcy/rl_eval_generator/blob/arena/b060c411-rl-eval-generator/tools/campaign_status_sidecar.py`
→ pencil → paste → **Commit directly to the `arena/b060c411-rl-eval-generator`
branch**. No new branch is needed: the lineage tip is this file's base, so the commit
fast-forwards. If branch protection refuses a direct commit, fall back to the 4.1 flow
starting from `7eca038` and naming the branch `reporting-fix-mercury`.

Then Actions → **Mercury pairwise campaign** → Run workflow → Branch `main` →
`ref` and `rebase_onto_ref` = the new lineage tip SHA, `execution_mode` = `paid`,
everything else default.

The reporter's own delta on that tip is free (`8446d56` vs `7eca038`, measured). What
you are paying for is the judge fix already in the tip: the 189-row exact-instance gate
re-graded over the 4 verdict files, with the 371 banked episode rows carried forward.
`experiments/` is byte-identical pin → target, so provider, model, endpoint, effort,
ceilings and profile did not move.

## 5. One click is enough — nothing needs cancelling

Both launchers set `concurrency: {group: <campaign>, cancel-in-progress: false}`, so a
dispatch **queues** behind the in-flight leg instead of racing it. When that leg reaches
its re-arm step, `tools/campaign_rearm.py:other_legs()` excludes only its own run id and
counts a `queued` sibling as busy (`BUSY_RUN_STATUSES`), so it declines to arm a
successor: the old chain ends there and the re-pinned leg arms the next one. The chain
hands over cleanly; two chains never run in parallel.

For reference, the shell routes (`git am`, `git push`, `gh workflow run`) all return
**HTTP 403** for this session's credential, which is why the fix is a paste and a
dropdown rather than a pushed branch.

## 6. What the fixed comment will say

Two facts that were already on the machine and were never in the body:

```
- **Updated:** 2026-10-15T05:00:05Z
- **Comment rendered:** 2026-10-15T19:45:56Z, rendered by leg run 38758437040 attempt 1
```

plus, for a leg paused in the probe: the probe's name, its refusal class, its attempt
count, the age of `compatibility.json`, and an explicit line saying why the episode
counter cannot move. `Updated` keeps reporting the checkpoint, because that is a real
fact — it is just no longer the only clock in the comment.

## 7. After this: make the reporter unpinnable

The durable fix is also browser-only, because it is one workflow file: add the
`reporting_ref` input and the second `actions/checkout@v4` with `path: reporting` from
`docs/decisions/2026-10-15-the-reporter-is-not-the-measurement.md` §3 to both pairwise
launchers on `main`, editing them in the same web editor. After that, a reporting fix is
a dropdown instead of a re-pin — and this document stops being necessary.
