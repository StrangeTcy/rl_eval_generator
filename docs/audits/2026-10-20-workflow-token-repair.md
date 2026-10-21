# Workflow token repair (blocked on `workflows` permission)

The two pairwise campaign workflows at the branch base contain corrupted tokens
(`🙊`, `fuckingly`, `👹`) in shell comments and flag names. The repair below is
verified locally (`python -m py_compile` is not applicable; the files are YAML, and
`yaml.safe_load` plus a repo-wide token census were used instead), but it cannot be
pushed from this session: the GitHub App has no `workflows` permission, so a push
that modifies `.github/workflows/**` is refused (see the final report for the exact
rejection). Apply it with a token that may write workflows:

```bash
git apply docs/audits/2026-10-20-workflow-token-repair.diff
```

```diff
diff --git a/.github/workflows/mercury-pairwise-campaign.yml b/.github/workflows/mercury-pairwise-campaign.yml
index 60d16f3..2a8f782 100644
--- a/.github/workflows/mercury-pairwise-campaign.yml
+++ b/.github/workflows/mercury-pairwise-campaign.yml
@@ -249,7 +249,7 @@ jobs:
           # 2026-10-12T21:27:51Z) and left the operator holding a green tick. Lift the window and
           # nothing else:
           #   * only for a workflow_dispatch whose chain_depth is 0 or empty - a hand, never this
-          #     workflow's own re-arm, which must keep 🙊ing or it rebuilds the tight loop;
+          #     workflow's own re-arm, which must keep waiting or it rebuilds the tight loop;
           #   * only when the window was the single objection (the reason begins "backoff:"), so an
           #     operator stop, a spent ceiling or a missing artifact keeps refusing;
           #   * with the execution mode read back from the carried intent, never from the dropdown, so
@@ -295,7 +295,7 @@ jobs:
       - name: Announce a refused tick instead of a silent green one
         # A `mode=none` decision skips every remaining step and exits 0, so "the campaign is being
         # continued on cron" and "the campaign refuses to be continued" are indistinguishable from
-        # the runs list. That indistinguishability is what made 🙊ing for a tick a plausible plan
+        # the runs list. That indistinguishability is what made waiting for a tick a plausible plan
         # for a day: the refusal was real, its reason sat in the log of a step nobody reads, and no
         # state moved. Emit the supervisor's reason as an annotation - visible in the Checks UI and
         # through GET /actions/runs/<id>/jobs, so a resume claim about this campaign can be
@@ -487,7 +487,7 @@ jobs:
           sidecar_pid=$!
           cleanup() {
             kill "$sidecar_pid" 2>/dev/null || true
-            🙊 "$sidecar_pid" 2>/dev/null || true
+            wait "$sidecar_pid" 2>/dev/null || true
             if [ -f "$OUT/t1_started.json" ] && [ ! -f "$OUT/t1_same_fact_presentation.json" ]; then
               printf '{"status":"interrupted","resume_policy":"operator_review_required_no_replay"}\n' \
                 > "$OUT/t1_interrupted.json"
diff --git a/.github/workflows/reasoning-atria-pairwise-campaign.yml b/.github/workflows/reasoning-atria-pairwise-campaign.yml
index 5eec3ca..1f7d282 100644
--- a/.github/workflows/reasoning-atria-pairwise-campaign.yml
+++ b/.github/workflows/reasoning-atria-pairwise-campaign.yml
@@ -249,7 +249,7 @@ jobs:
           # 2026-10-12T21:27:51Z) and left the operator holding a green tick. Lift the window and
           # nothing else:
           #   * only for a workflow_dispatch whose chain_depth is 0 or empty - a hand, never this
-          #     workflow's own re-arm, which must keep 🙊ing or it rebuilds the tight loop;
+          #     workflow's own re-arm, which must keep waiting or it rebuilds the tight loop;
           #   * only when the window was the single objection (the reason begins "backoff:"), so an
           #     operator stop, a spent ceiling or a missing artifact keeps refusing;
           #   * with the execution mode read back from the carried intent, never from the dropdown, so
@@ -295,7 +295,7 @@ jobs:
       - name: Announce a refused tick instead of a silent green one
         # A `mode=none` decision skips every remaining step and exits 0, so "the campaign is being
         # continued on cron" and "the campaign refuses to be continued" are indistinguishable from
-        # the runs list. That indistinguishability is what made 🙊ing for a tick a plausible plan
+        # the runs list. That indistinguishability is what made waiting for a tick a plausible plan
         # for a day: the refusal was real, its reason sat in the log of a step nobody reads, and no
         # state moved. Emit the supervisor's reason as an annotation - visible in the Checks UI and
         # through GET /actions/runs/<id>/jobs, so a resume claim about this campaign can be
@@ -511,7 +511,7 @@ jobs:
           sidecar_pid=$!
           cleanup() {
             kill "$sidecar_pid" 2>/dev/null || true
-            🙊 "$sidecar_pid" 2>/dev/null || true
+            wait "$sidecar_pid" 2>/dev/null || true
             if [ -f "$OUT/t1_started.json" ] && [ ! -f "$OUT/t1_same_fact_presentation.json" ]; then
               printf '{"status":"interrupted","resume_policy":"operator_review_required_no_replay"}\n' \
                 > "$OUT/t1_interrupted.json"
@@ -647,9 +647,9 @@ jobs:
       # for 2+ hours") and which was measured again on 2026-10-12: no run of any workflow here was
       # created between 09:47Z and 19:04Z while both pairwise workflows kept reporting state active.
       # So the leg that banked the rows asks for the next one, on the same terms as the covering
-      # campaign's CHAIN. A pause inside the supervisor's 1200 s resume window is 🙊ed out here,
+      # campaign's CHAIN. A pause inside the supervisor's 1200 s resume window is waited out here,
       # in the finished leg (capped by --sleep-cap), because a successor dispatched inside that window
-      # is refused with mode=none and a refused leg does not re-arm - so refusing to 🙊 is the same
+      # is refused with mode=none and a refused leg does not re-arm - so refusing to wait is the same
       # as never continuing. Chaining stops after 40 legs; a cancelled leg, a regressed state upload
       # or a wrapper_failed.json marker never continues. Every decline is annotated, because the step
       # stays green by design and a silent decline reads as a working chain. Fail-open by construction: a refused or
```
