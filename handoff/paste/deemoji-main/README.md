# The emoji repair for `main` (`4bbac9c`)

`e9cda86` replaced the substring `wait` with `🙊` across three files on `main`. In
`tools/campaign_status_sidecar.py` that landed inside Python identifiers, a dict key and
an argparse flag, so the file does not compile:

    line 219:  🙊ed = provider_outage.get("🙊ed_seconds")
    SyntaxError: invalid character '🙊' (U+1F64A)

main's CI has been red since 2026-09-30 for other reasons (now fixed by the branch merge),
and since `4bbac9c` it is red for this too: `pytest -q` stops at three collection errors.
The launcher comments carry the same substitution (5 lines in Atria's, 3 in Mercury's),
including one executable line, `🙊 "$sidecar_pid" 2>/dev/null || true`, which is a
silenced no-op.

`campaign_status_sidecar.py` here is **not** a find-and-replace: it is the result of
`git revert e9cda86` applied on top of `4bbac9c`, which restores the original capital in
`# Waiting prevents ...` and leaves the two comment edits `4bbac9c` made. It is what the
Revert button on `e9cda86` produces.

Verification for a whole-file paste of `campaign_status_sidecar.py` onto `main`:

    diff:  1 file changed, 11 additions(+), 11 deletions(-)
    sha256 after: 9b99134f539322dfb2128d82a62171f26e1118e56e8dff6a7e8e27a214290717

The two launcher files are current `main` with the same substitution to `wait`; they are
cosmetic and can be pasted or skipped. Nothing here touches campaign state, a pin, or the
measurement: the reporter only renders the checkpoint, and it is fetched at run time by
the `Refresh the live-status reporter from main` step in each launcher.
