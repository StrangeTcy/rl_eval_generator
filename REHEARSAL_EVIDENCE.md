# Autonomous Rehearsal Evidence

See previous version for full details. This branch now has:
- Fixed main (7b3565f) restores full repo so atria-campaign workflow can run 2-day campaign with one button
- Arena branch has rehearsal mode in tools/atria_campaign.py and rehearsal profile in experiments/atria_campaign.yaml
- Local evidence: job A paused after 3 cases with provider outage survived, job B completed 5 cases retained

Run links:
- CI: https://github.com/StrangeTcy/rl_eval_generator/actions/runs/36390527535
- Atria covering campaign (real, on main): https://github.com/StrangeTcy/rl_eval_generator/actions/runs/36382969318 (shows supervisor + artifact transport, but fails due to missing profile before fix)

After main fix, new atria-campaign runs should last 2 days.

Blocker: GitHub App cannot push .github/workflows or dispatch workflows via API (403). Need user with workflows permission to copy docs/workflows examples to .github/workflows via web UI.

Pinned manifest: 5 cases, see experiments/atria_campaign.yaml (rehearsal) and runs/rehearsal_evidence.

Final report: runs/rehearsal_evidence/jobB/campaign_report.json status completed.
