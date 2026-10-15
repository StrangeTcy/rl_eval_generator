"""The one invariant that costs a campaign its continuation when it breaks: the re-arm tool must run from
where the launcher puts it.

Step 16 of both pairwise launchers fetches `tools/campaign_rearm.py` to `$RUNNER_TEMP/campaign_rearm.py`
and executes *that* file - or, when the fetch is empty, copies the pinned checkout's there and executes
that - so the script is never run from inside a package, and it is wrapped in
`|| { echo "campaign re-arm declined: the tool exited non-zero"; }`. A traceback and a considered refusal
therefore print the same line, which is how a module-level `from tools.campaign_supervisor import ...`
stranded every campaign in this repository for a day: `ModuleNotFoundError: No module named 'tools'`,
reported as a decision, at every pin, in every tree, for as long as the file was imported that way.

These tests reproduce the launcher's arrangement exactly - a copy of the shipped file in a directory with
no `tools` package, run from that directory with no credential - and they belong in whatever tree the
launcher will fetch, because that is the copy that has to satisfy them.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "campaign_rearm.py"

CLEAN_ENV = {k: v for k, v in os.environ.items() if k not in ("GITHUB_TOKEN", "GH_TOKEN", "PYTHONPATH")}


def _run(workdir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(workdir / "campaign_rearm.py"), *args],
        cwd=str(workdir), capture_output=True, text=True, env=CLEAN_ENV, timeout=120,
    )


def _staged(tmp_path: Path, report: dict | None) -> Path:
    """The launcher's `$RUNNER_TEMP`: the file alone, no package, nothing on PYTHONPATH."""
    work = tmp_path / "runner_temp"
    work.mkdir()
    shutil.copyfile(TOOL, work / "campaign_rearm.py")
    if report is not None:
        import json

        (work / "campaign_report.json").write_text(json.dumps(report), encoding="utf-8")
    return work


def test_the_shipped_copy_compiles_wherever_it_lies(tmp_path: Path) -> None:
    """A pasted or truncated copy is the other way this died: main's copy was deleted after turning out to
    be an unparseable paste, and the launcher's `base64 -d` cannot tell that from a good file."""
    import py_compile

    py_compile.compile(str(TOOL), doraise=True, cfile=str(tmp_path / "campaign_rearm.pyc"))


def test_it_runs_from_the_temp_directory_the_launcher_executes_it_in(tmp_path: Path) -> None:
    work = _staged(tmp_path, None)
    done = _run(work, "--report", str(tmp_path / "absent.json"), "--repo", "x/y", "--dry-run")
    assert done.returncode == 0, (done.returncode, done.stderr[-1200:])
    assert "Traceback" not in done.stderr, done.stderr[-800:]
    assert "campaign re-arm skipped: report unreadable" in done.stdout, done.stdout


def test_it_declines_without_a_credential_instead_of_reaching_for_one(tmp_path: Path) -> None:
    """No token in the job means no dispatch attempted - and no crash, no traceback, no red leg."""
    paused = {"status": "paused", "pause_reason": "max_wall_seconds", "resumable": True}
    work = _staged(tmp_path, paused)
    done = _run(work, "--report", "campaign_report.json", "--repo", "StrangeTcy/rl_eval_generator",
                "--workflow", "Mercury pairwise campaign", "--chain-depth", "1", "--dry-run")
    assert done.returncode == 0, (done.returncode, done.stderr[-1200:])
    assert "Traceback" not in done.stderr, done.stderr[-800:]
    assert "no GITHUB_TOKEN" in done.stdout, done.stdout


def test_the_arrangement_under_test_is_the_one_the_launcher_builds() -> None:
    """Pinned from the deployed files, so these tests cannot quietly become about a hypothetical.

    The launcher must still stage the tool into `$RUNNER_TEMP`, still treat an empty fetch as absent and
    fall back to the checkout, and still report a non-zero exit as a decline. That last part is why the
    crash survived a day: the wrapper makes a traceback indistinguishable from a decision, so the only
    defence is a file that cannot crash.
    """
    candidates = sorted((ROOT / ".github" / "workflows").glob("*.yml")) if (ROOT / ".github" / "workflows").is_dir() else []
    candidates += sorted((ROOT / "docs" / "workflows").glob("*.example")) if (ROOT / "docs" / "workflows").is_dir() else []
    launchers = [path for path in candidates if "campaign_rearm.py" in path.read_text(encoding="utf-8")]
    if not launchers:
        # A tree without the launchers (a trimmed branch, a docs-only checkout) has no arrangement to
        # contradict, and saying so is the honest result - it must not read as a passing guarantee.
        import pytest

        pytest.skip("no launcher file in this tree declares the staged re-arm step", allow_module_level=False)
    for path in launchers:
        text = path.read_text(encoding="utf-8")
        assert 'REARM="$RUNNER_TEMP/campaign_rearm.py"' in text, path.name
        assert "campaign re-arm declined: the tool exited non-zero" in text, path.name
        # The fallback, in whichever shape the copy declares it: this branch's example gates the fetch on
        # `ast.parse` before executing it (main's copies `base64 -d` and only check the file is non-empty),
        # because a mangled upload at main@e72ec43 made a SyntaxError read as "the re-arm declined".
        assert 'cp tools/campaign_rearm.py "$REARM"' in text, path.name
