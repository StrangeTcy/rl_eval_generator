"""Repository-wide pytest configuration.

Two hooks here are load-bearing for the campaigns and neither is a test fixture.

``pytest_sessionfinish`` consults ``tools/campaign_kick.py``: a committed ``campaign_kick.json`` can ask the
run that validates the push to start one campaign leg. The guards live there and they fail closed; the
hook exists because CI is the only place this repository's own code is guaranteed to execute, and it is
silent outside a CI run so no local ``pytest`` ever reaches for the network.

``pytest_runtest_logreport`` plus ``pytest_terminal_summary`` turn a red suite into an annotation. The
reason is a measurement, not a preference: CI on this branch failed ``pytest -q`` with exit code 1 for
three runs and the failing test could not be recovered from anywhere readable - the log endpoints are
closed to this credential, and the only output that arrives is a check annotation. A suite that can fail
silently is a suite nobody can diagnose, so a failure now names itself.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_FAILING: list[str] = []


def pytest_runtest_logreport(report) -> None:  # noqa: ANN001 - pytest's signature
    if report.failed and report.when in ("call", "setup"):
        _FAILING.append(str(report.nodeid))


def pytest_terminal_summary(terminalreporter) -> None:  # noqa: ANN001 - pytest's signature
    if not _FAILING or not os.environ.get("GITHUB_RUN_ID"):
        return
    names = sorted(_FAILING)
    shown = ", ".join(names[:12])
    extra = "" if len(names) <= 12 else f" (+{len(names) - 12} more)"
    print(f"\n::warning::failing tests: {shown}{extra}")


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ANN001 - pytest's signature
    # Guarded by hand: a conftest that raises would take the suite down with it, which would turn an
    # optional nudge at the scheduler into a way to break CI.
    try:
        from tools.campaign_kick import maybe_kick_from_ci

        note = maybe_kick_from_ci(ROOT)
    except BaseException as exc:  # noqa: BLE001 - the suite must survive any of this
        note = f"skipped, the check itself failed ({type(exc).__name__}: {exc})"
    if note and os.environ.get("GITHUB_RUN_ID"):
        # ::warning:: because a log line from a CI job whose endpoints are closed is not readable by
        # anyone; an annotation is. The verdict of a kick - dispatched, refused, or declined - has to
        # reach the person who pushed the instruction, and this is the only channel that reaches them.
        print(f"\n::warning::campaign kick: {note}")
