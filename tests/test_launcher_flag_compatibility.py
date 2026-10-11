"""Launcher/controller flag compatibility, across the revision a campaign is pinned to.

An Atria tick died in one second with `atria_campaign.py: error: unrecognized arguments:
--allow-cross-revision-t1` - exit 2, nothing billed, and the same for its successor. The flag
itself is fine; the *placement* was wrong on the deployed launcher copy, and a resumed campaign
runs the code recorded in its own state artifact rather than the branch the operator dispatched
from. Those two facts combine into a class of failure that no amount of testing the current
revision catches: a flag that moves between tools is understood by neither side for as long as
any campaign is pinned to a revision on the other side of the move.

So the rules checked here are (1) every flag a launcher passes to a tool must be declared by
that tool at HEAD, (2) a launcher must not pass a flag the controller merely swallows, and (3)
a flag once tolerated may never be dropped as unused, because dropping it is what re-arms the
trap for every lineage pinned to an older revision.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_DIRS = (ROOT / "handoff", ROOT / ".github" / "workflows")
LAUNCHER_GLOB = re.compile(r".*campaign.*\.yml$")
TOOL_CALL = re.compile(r"python[\d.]*\s+(\S*tools/[A-Za-z0-9_]+\.py)((?:[^\n|&;]|\n\s*\\)*)")
FLAG = re.compile(r"--[a-z0-9][a-z0-9-]*")


def _launchers() -> list[Path]:
    found: list[Path] = []
    for directory in LAUNCHER_DIRS:
        if directory.is_dir():
            found.extend(p for p in sorted(directory.glob("*.yml")) if LAUNCHER_GLOB.match(p.name))
    assert found, "no campaign launchers found - this test would be vacuous"
    return found


def _declared_flags(tool: Path) -> set[str]:
    """Flag names the tool's own argparse block declares, read from source.

    Parsing `--help` would be the honest route, but these controllers import provider and
    container dependencies that a review sandbox does not have, and a test that needs Docker to
    say whether a word is spelled right is a test that gets skipped.
    """
    return set(re.findall(r'add_argument\(\s*"(--[a-z0-9][a-z0-9-]*)"', tool.read_text(encoding="utf-8")))


def _invocations() -> list[tuple[str, str, str]]:
    """(launcher, tool, flag) triples for every flag a launcher hands a tools/ script."""
    rows: list[tuple[str, str, str]] = []
    for launcher in _launchers():
        text = re.sub(r"\\\s*\n\s*", " ", launcher.read_text(encoding="utf-8"))
        for match in TOOL_CALL.finditer(text):
            tool_name = Path(match.group(1)).name
            tool = ROOT / "tools" / tool_name
            if not tool.is_file():
                rows.append((launcher.name, tool_name, "<missing tool>"))
                continue
            for flag in sorted(set(FLAG.findall(match.group(2)))):
                if flag not in _declared_flags(tool):
                    rows.append((launcher.name, tool_name, flag))
    return rows


def test_no_launcher_hands_a_tool_a_flag_it_does_not_declare() -> None:
    """The forward half: a flag invented for a tool that has not grown it yet."""
    offenders = _invocations()
    assert not offenders, (
        "launchers pass flags their target tool does not declare (each line is "
        "launcher, tool, flag): " + "; ".join(f"{a} -> {b} {c}" for a, b, c in offenders)
    )


def test_no_launcher_relies_on_the_controllers_tolerance() -> None:
    """The half that actually broke: tolerance is a safety net for a lineage already pinned to a
    revision that carries the flag, not a license to keep passing a swallowed flag. A campaign
    resumes at the revision recorded in its own state artifact, so a launcher flag that only
    *some* revisions tolerate is a trap that springs hours later at whichever revision the pin
    happens to name - and the failing tick re-uploads that same pin, so it never heals on its own.
    """
    controller = ROOT / "tools" / "atria_campaign.py"
    source = controller.read_text(encoding="utf-8")
    swallowed = set(re.findall(r'"(--[a-z0-9-]+)":\s*"allow', source))
    assert swallowed, "the controller's compatibility-flag list disappeared from where this test reads it"
    offenders: list[str] = []
    for launcher in _launchers():
        lines = launcher.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if not re.search(r"python\S*\s+\S*tools/" + controller.name + r"\b", line):
                continue
            window = [line]
            for follow in lines[index + 1 :]:
                if not window[-1].rstrip().endswith("\\"):
                    break
                window.append(follow)
            flags = sorted(set(FLAG.findall(" ".join(window))) & swallowed)
            if flags:
                offenders.append(
                    f"{launcher.relative_to(ROOT)}:{index + 1} passes {', '.join(flags)} to {controller.name}"
                )
    assert not offenders, "; ".join(offenders)


@pytest.mark.parametrize("tool", ["tools/atria_campaign.py", "tools/inherit_campaign_state.py"])
def test_a_moved_flag_stays_declared_where_it_used_to_live(tool: str) -> None:
    """`--allow-cross-revision-t1` belongs to the inheritance tool; the campaign controller only
    has to not crash on it. That tolerance is load-bearing for any campaign pinned to the
    revision before the launcher stopped passing the flag: deleting it as dead code makes every
    one of those lineages exit 2 one second into a tick, which is the outage this file is about.
    """
    assert "--allow-cross-revision-t1" in _declared_flags(ROOT / tool), (
        f"{tool} must keep --allow-cross-revision-t1: a campaign resumed at a revision that "
        "predates the launcher's removal of the flag would otherwise be rejected by argparse"
    )


def test_the_tolerance_is_recorded_in_the_manifest_not_swallowed() -> None:
    """A flag accepted and ignored must say so where an auditor will look, or a campaign reads as
    having run with an option it never had."""
    source = (ROOT / "tools" / "atria_campaign.py").read_text(encoding="utf-8")
    assert "COMPATIBILITY_FLAGS" in source
    assert "ignored_launcher_arguments" in source
