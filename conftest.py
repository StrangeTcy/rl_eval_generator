"""Repository-wide pytest configuration.

Neither hook here is a test fixture; both exist because CI on the default branch
was red and unreadable, and both were measured before they were written.

``sys.path``: CI runs ``pytest -q``, the console script, which does not put the
working directory on ``sys.path`` the way ``python -m pytest`` does. The fourteen
modules under ``tests/epistemic_semantics/`` import ``shared.epistemic_semantics``
at module level and carry no path bootstrap of their own, so every CI run on this
branch died in about twelve seconds with exit code 2 and
``ModuleNotFoundError: No module named 'shared'`` - measured on runs 38686356340
(main, 05:21:36Z) and 38713221525 (this branch, 09:28:44Z), and invisible locally
to anyone who ran ``python -m pytest`` instead. A collection error is not a
failing test: it stops the suite before a single assertion runs, so nothing else
in CI was being verified at all.

``pytest_runtest_logreport`` plus ``pytest_terminal_summary`` turn a red suite
into a check annotation. The reason is the same measurement that made the
campaigns' own status sidecar grow a heartbeat: the Actions log endpoints are
closed to the credential that can read everything else about a run
(``results-receiver.actions.githubusercontent.com`` and the artifact blob host
both answer EOF), so the only output of a failed job that anybody can read
afterwards is an annotation. A suite that can fail silently is a suite nobody can
diagnose, so a failure now names itself.

The pairwise lineage's conftest also carries a ``pytest_sessionfinish`` hook that
consults ``tools/campaign_kick.py``, so a committed instruction can ask the CI run
to start one campaign leg. That tool is not in this tree, and a hook that failed
its own import on every run would spend the annotation channel on noise, so it is
deliberately absent here rather than guarded into silence.
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
