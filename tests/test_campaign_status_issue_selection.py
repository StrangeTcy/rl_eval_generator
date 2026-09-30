"""The status sidecar must report into one Issue, not a new one per leg.

A campaign restores its state artifact before the sidecar starts, and the
artifact records the Issue the sidecar last used. The sidecar used to create a
fresh Issue whenever that record was absent, so every leg whose restored state
predated a given Issue opened another one. Four status Issues exist for one
campaign (#3 through #6) for exactly that reason, and the one an operator was
following went silent while the campaign kept running.

Selection is now a ladder: an explicitly pinned Issue, then the newest open
live-status Issue, then a new one. The pin lives in the checked-out ref rather
than the state artifact, so it is usable precisely when the restored state is
too old to name the Issue.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import campaign_status_sidecar  # noqa: E402


def _run(tmp_path: Path, monkeypatch, api, listing=None) -> tuple[object, str | None]:
    def fake_api_any(_token, method, path, payload=None):
        if method == "GET" and "/issues?" in path:
            if listing is None:
                raise AssertionError(f"unexpected list call: {path}")
            return listing
        return api(_token, method, path, payload)

    monkeypatch.setattr(campaign_status_sidecar, "_api_any", fake_api_any)
    monkeypatch.setattr(campaign_status_sidecar, "_api", api)
    return campaign_status_sidecar._ensure_comment(
        tmp_path, "owner/repository", "non-secret-test-value"
    )


def _issue_and_comment(issue: int) -> dict:
    def api(_token, method, path, payload=None):
        if method == "POST" and path == "/repos/owner/repository/issues":
            raise AssertionError("created a new Issue instead of reusing one")
        if method == "POST" and path.endswith("/comments"):
            return {"id": 900 + issue}
        raise AssertionError(f"unexpected call {method} {path}")

    return api


def test_a_pinned_issue_wins_over_creating_one(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(campaign_status_sidecar, "_pinned_issue_number", lambda: 3)

    target, error = _run(tmp_path, monkeypatch, _issue_and_comment(3))

    assert error is None
    assert target == (3, 903), "must post into the pinned Issue, not create a new one"


def test_without_a_pin_the_newest_open_status_issue_is_reused(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(campaign_status_sidecar, "_pinned_issue_number", lambda: None)
    listing = [
        {"number": 9, "title": "unrelated issue"},
        {"number": 6, "title": campaign_status_sidecar.STATUS_ISSUE_TITLE},
        {"number": 3, "title": campaign_status_sidecar.STATUS_ISSUE_TITLE},
        {"number": 8, "title": "a pull request",
         "pull_request": {"url": "https://example.invalid"}},
    ]

    target, error = _run(tmp_path, monkeypatch, _issue_and_comment(6), listing=listing)

    assert error is None
    # 6, not 3: the listing is requested newest-first, so the first match is the
    # newest open Issue. Reusing the newest is what keeps a campaign's later legs
    # in the Issue its operator is already watching.
    assert target == (6, 906)


def test_a_creation_still_happens_when_there_is_nothing_to_reuse(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(campaign_status_sidecar, "_pinned_issue_number", lambda: None)

    def api(_token, method, path, payload=None):
        if method == "POST" and path == "/repos/owner/repository/issues":
            return {"number": 12}
        if method == "POST" and path.endswith("/comments"):
            return {"id": 912}
        raise AssertionError(f"unexpected call {method} {path}")

    target, error = _run(tmp_path, monkeypatch, api, listing=[])

    assert (target, error) == ((12, 912), None)


def test_the_reused_issue_is_persisted_for_the_watchdog_to_find(
    tmp_path: Path, monkeypatch
) -> None:
    """The workflow-level watchdog reads .issue_number out of this file to decide
    which Issue body to rewrite. If the sidecar reused an Issue without recording
    it, the comment would go to the right place and the body to a stale one."""
    monkeypatch.setattr(campaign_status_sidecar, "_pinned_issue_number", lambda: 3)

    _run(tmp_path, monkeypatch, _issue_and_comment(3))

    state = json.loads(
        (tmp_path / campaign_status_sidecar.COMMENT_STATE).read_text(encoding="utf-8")
    )
    assert state["issue_number"] == 3
    assert state["comment_id"] == 903


def test_the_pinned_issue_is_read_from_the_checked_out_ref(
    tmp_path: Path, monkeypatch
) -> None:
    """The pin must come from the code, not the state artifact, so it still
    applies when the restored state is older than the Issue it names."""
    pin = ROOT / campaign_status_sidecar.STATUS_ISSUE_PIN
    assert pin.is_file(), f"the repository must ship {pin.name}"
    monkeypatch.setattr(campaign_status_sidecar, "ROOT", tmp_path)
    (tmp_path / "experiments").mkdir()
    (tmp_path / campaign_status_sidecar.STATUS_ISSUE_PIN).write_text("#7\n")
    assert campaign_status_sidecar._pinned_issue_number() == 7

    (tmp_path / campaign_status_sidecar.STATUS_ISSUE_PIN).write_text("not a number\n")
    assert campaign_status_sidecar._pinned_issue_number() is None


def test_a_listing_that_is_not_a_list_does_not_break_the_sidecar(
    tmp_path: Path, monkeypatch
) -> None:
    """The sidecar is fail-open: an unexpected API shape must not raise."""
    monkeypatch.setattr(campaign_status_sidecar, "_pinned_issue_number", lambda: None)

    def api(_token, method, path, payload=None):
        if method == "POST" and path == "/repos/owner/repository/issues":
            return {"number": 4}
        if method == "POST" and path.endswith("/comments"):
            return {"id": 904}
        raise AssertionError(f"unexpected call {method} {path}")

    target, error = _run(tmp_path, monkeypatch, api, listing={"message": "nope"})

    assert (target, error) == ((4, 904), None)
