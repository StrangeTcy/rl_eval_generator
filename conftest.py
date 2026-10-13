"""Repository-wide pytest configuration.

One hook here is load-bearing for the campaigns, and it is not a test fixture: `pytest_sessionfinish`
consults `tools/campaign_kick.py`, which is how a campaign leg can be started by a push when GitHub is
not creating scheduled runs and the dispatch API refuses the only credential this workspace holds. See
that module's docstring for the measurements; the guards there fail closed, and with no
`campaign_kick.json` on the branch this hook does nothing at all - including on every local run.

The suite's own result is deliberately not a condition: the leg a kick starts checks out the ref the
campaign's own state pins, not the commit being tested, so a red run here cannot make a campaign leg
unsafe and a green one cannot make it safe.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ANN001 - pytest's signature
    # Guarded by hand: a conftest that raises would take the suite down with it, which would turn an
    # optional nudge at the scheduler into a way to break CI.
    try:
        from tools.campaign_kick import maybe_kick_from_ci

        note = maybe_kick_from_ci(ROOT)
    except BaseException as exc:  # noqa: BLE001 - the suite must survive any of this
        note = f"skipped, the check itself failed ({type(exc).__name__}: {exc})"
    in_ci = bool(os.environ.get("GITHUB_RUN_ID")) or (ROOT / "campaign_kick.json").exists()
    if note and in_ci:
        # ::warning:: because a log line from a CI job whose endpoints are closed is not readable by
        # anyone; an annotation is. The verdict of a kick - dispatched, refused, or declined - has to
        # reach the person who pushed the instruction, and this is the only channel that reaches them.
        print(f"\n::warning::campaign kick: {note}")
