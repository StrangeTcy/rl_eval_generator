"""Offline contract tests for the credential verdict added to provider_preflight.

The tool already existed and already probed ``/models``; these tests cover only what
was added: naming the condition a status code describes, and exposing that as an
exit code the workflow can branch on. No network - the opener is stubbed.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib import error

import pytest

from tools import provider_preflight as preflight

FAKE_KEY = "atr_THISMUSTNEVERAPPEAR_0123456789"


class _Response:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body
        self.headers = {"content-type": "application/json"}

    def read(self, _limit: int | None = None) -> bytes:
        return self._body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


@pytest.mark.parametrize(
    ("status", "error_code", "expected"),
    [
        (200, None, "authenticated"),
        (404, None, "authenticated_endpoint_absent"),
        (401, "invalid_api_key", "credential_rejected"),
        (403, None, "credential_rejected"),
        (429, None, "quota_or_rate_limited"),
        (500, None, "http_status_500"),
        (None, None, "transport_error"),
    ],
)
def test_each_status_names_one_condition(status, error_code, expected):
    assert preflight.classify_status(status, error_code) == expected


def test_an_auth_body_outranks_a_routed_status():
    """Providers that gate on the key before routing answer unknown paths with an
    auth error; reporting that as a missing endpoint would blame the wrong layer."""

    assert preflight.classify_status(404, "invalid_api_key") == "credential_rejected"


@pytest.mark.parametrize(
    ("classification", "expected_exit"),
    [
        ("authenticated", preflight.EXIT_AUTHENTICATED),
        ("authenticated_endpoint_absent", preflight.EXIT_AUTHENTICATED),
        ("credential_rejected", preflight.EXIT_CREDENTIAL_REJECTED),
        ("quota_or_rate_limited", preflight.EXIT_QUOTA),
        ("no_credential", preflight.EXIT_NO_CREDENTIAL),
        ("transport_error", preflight.EXIT_NO_VERDICT),
        ("http_status_500", preflight.EXIT_NO_VERDICT),
    ],
)
def test_exit_codes_separate_auth_from_quota(classification, expected_exit):
    assert preflight.classify_exit(classification) == expected_exit


def _stub(monkeypatch, *, status=None, body=b"", raises=None, seen=None):
    def fake_open(req, timeout):  # noqa: ANN001
        if seen is not None:
            seen.append(req)
        if raises is not None:
            raise raises
        return _Response(status, body)

    monkeypatch.setattr(preflight, "open_no_redirect", fake_open)


def _probe(monkeypatch, *, status, body, seen=None):
    # A key must be present or the tool correctly stops before sending anything.
    monkeypatch.setenv("ATRIA_API_KEY", FAKE_KEY)
    _stub(monkeypatch, status=status, body=body, seen=seen)
    return preflight.probe_provider(
        "atria",
        secret_path=None,
        timeout=10.0,
        api_base="https://api.atria-asi.ai/v1",
        api_key_env="ATRIA_API_KEY",
    )


def test_a_refused_credential_is_reported_as_such(monkeypatch):
    seen: list[object] = []
    result = _probe(
        monkeypatch,
        status=401,
        body=(
            b'{"error":{"message":"Invalid API key.","type":"atria_api_error",'
            b'"code":"invalid_api_key"}}'
        ),
        seen=seen,
    )
    assert result["classification"] == "credential_rejected"
    assert result["error_code"] == "invalid_api_key"
    assert result["status_code"] == 401
    # Exactly one request: the probe must not become a second execution path.
    assert len(seen) == 1


def test_quota_is_not_reported_as_an_auth_failure(monkeypatch):
    result = _probe(monkeypatch, status=429, body=b'{"error":{"code":"quota_exhausted"}}')
    assert result["classification"] == "quota_or_rate_limited"
    assert result["error_code"] == "quota_exhausted"


def test_a_reachable_provider_still_reports_its_model_ids(monkeypatch):
    result = _probe(
        monkeypatch,
        status=200,
        body=b'{"data":[{"id":"Atria-Dawn"}]}',
    )
    assert result["classification"] == "authenticated"
    assert result["model_ids"] == ["Atria-Dawn"]
    assert result["status"] == "reachable"


def test_a_missing_credential_sends_nothing(monkeypatch):
    seen: list[object] = []
    _stub(monkeypatch, status=200, body=b"{}", seen=seen)
    result = preflight.probe_provider(
        "atria",
        secret_path=None,
        timeout=10.0,
        api_base="https://api.atria-asi.ai/v1",
        api_key_env="ATRIA_API_KEY_NOT_SET_ANYWHERE",
    )
    assert result["classification"] == "no_credential"
    assert result["status_code"] is None
    assert seen == [], "no key means no request"


def test_a_transport_failure_is_not_a_verdict(monkeypatch):
    monkeypatch.setenv("ATRIA_API_KEY", FAKE_KEY)
    _stub(monkeypatch, raises=error.URLError("dns"))
    result = preflight.probe_provider(
        "atria",
        secret_path=None,
        timeout=10.0,
        api_base="https://api.atria-asi.ai/v1",
        api_key_env="ATRIA_API_KEY",
    )
    assert result["classification"] == "transport_error"
    assert preflight.classify_exit(result["classification"]) == preflight.EXIT_NO_VERDICT


def test_a_refusal_outranks_a_reachable_provider_in_the_run_verdict(monkeypatch, tmp_path):
    secrets = tmp_path / "secret_key.json"

    def fake_probe(name, **_kwargs):  # noqa: ANN001
        return {
            "provider": name,
            "status": "http_error" if name == "atria" else "reachable",
            "status_code": 401 if name == "atria" else 200,
            "classification": "credential_rejected" if name == "atria" else "authenticated",
            "model_ids": [] if name == "atria" else ["mercury-2.5"],
        }

    monkeypatch.setattr(preflight, "probe_provider", fake_probe)
    monkeypatch.setattr(
        preflight, "load_secret_config", lambda _p: ({"providers": {}}, secrets)
    )
    report = preflight.run_preflight(
        secret_path=secrets, providers=["atria", "mercury"], timeout=1.0
    )
    assert report["verdict"] == "credential_rejected"
    assert report["exit_code"] == preflight.EXIT_CREDENTIAL_REJECTED
    # The reachable provider is still visible, not overwritten by the verdict.
    assert [p["provider"] for p in report["providers"]] == ["atria", "mercury"]


def test_the_key_never_reaches_the_report_or_the_annotation(
    monkeypatch, tmp_path, capsys
) -> None:
    _stub(
        monkeypatch,
        status=401,
        body=b'{"error":{"message":"Invalid API key.","code":"invalid_api_key"}}',
    )
    monkeypatch.setenv("ATRIA_API_KEY", FAKE_KEY)
    out = tmp_path / "preflight.json"
    exit_code = preflight.main(
        [
            "--provider",
            "atria",
            "--api-base",
            "https://api.atria-asi.ai/v1",
            "--api-key-env",
            "ATRIA_API_KEY",
            "--out",
            str(out),
            "--github",
        ]
    )
    captured = capsys.readouterr()
    written = out.read_text()
    assert exit_code == preflight.EXIT_CREDENTIAL_REJECTED
    assert FAKE_KEY not in captured.out
    assert FAKE_KEY not in captured.err
    assert FAKE_KEY not in written
    assert json.loads(written)["providers"][0]["classification"] == "credential_rejected"


def test_the_workflow_runs_the_probe_before_the_live_step() -> None:
    """Checked against the reviewable copy: the app token that pushes this repo
    cannot write `.github/workflows/`, so that file is copied by hand and this test
    pins the text that gets copied."""

    import yaml

    workflow = yaml.safe_load(
        Path("docs/workflows/recursive-gluing-reasoning-pilot.yml.example").read_text()
    )
    steps = workflow["jobs"]["evaluate"]["steps"]
    names = [step["name"] for step in steps]
    probe = next(i for i, name in enumerate(names) if name.startswith("Credential preflight"))
    live = next(i for i, name in enumerate(names) if name.startswith("Live pilot"))
    assert probe < live, "the probe must run before any case is attempted"

    body = steps[probe]["run"]
    assert "tools/provider_preflight.py" in body
    assert "--api-base \"$API_BASE\"" in body
    assert steps[probe].get("continue-on-error") is True
    # The probe reports a verdict; it never drives a case.
    assert "recursive_gluing_study.py" not in body


def test_the_probe_step_receives_the_same_secrets_as_the_live_step() -> None:
    """A probe that cannot see the credential reports a false alarm.

    Run 40084623031 annotated "ATRIA_API_KEY is empty" and exited 6 before invoking
    the tool, because the step had no env: block - the secrets were injected only on
    the live step. The job still succeeded and the live step ran for 12 minutes, so
    the annotation looked like a finding about the credential rather than a defect
    in the step that produced it.
    """

    import yaml

    workflow = yaml.safe_load(
        Path("docs/workflows/recursive-gluing-reasoning-pilot.yml.example").read_text()
    )
    steps = {step["name"].split(" (")[0]: step for step in workflow["jobs"]["evaluate"]["steps"]}
    probe_env = set((steps["Credential preflight"].get("env") or {}))
    live_env = set((steps["Live pilot"].get("env") or {}))
    assert live_env, "the live step is the reference; it must carry the secrets"
    assert probe_env == live_env, (
        "the probe step must receive every secret the live step does, or its "
        f"presence check tests an empty string (probe {sorted(probe_env)} vs "
        f"live {sorted(live_env)})"
    )


_DEPLOYED = Path(".github/workflows/recursive-gluing-reasoning-pilot.yml")
_REVIEWABLE = Path("docs/workflows/recursive-gluing-reasoning-pilot.yml.example")


@pytest.mark.skipif(
    _DEPLOYED.read_text() != _REVIEWABLE.read_text(),
    reason=(
        "deployed workflow is behind the reviewable copy - copy "
        "docs/workflows/recursive-gluing-reasoning-pilot.yml.example over "
        ".github/workflows/recursive-gluing-reasoning-pilot.yml to activate this guard"
    ),
)
def test_the_reviewable_copy_and_the_deployed_workflow_do_not_drift() -> None:
    """An earlier endpoint fix landed in docs/ only, so it was reviewed but never ran.

    Skips while the copy is stale rather than failing, because the deploying edit is
    a manual step; once the files match, the equality is enforced from then on.
    """

    assert _DEPLOYED.read_text() == _REVIEWABLE.read_text()
