"""Compile-only campaign episodes must not be refused by the episode gate."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from arena import episode  # noqa: E402
from tools import instance_oracle_gate  # noqa: E402

ORACLE_FAILED = "Exact-instance judge oracle failed before provider access"


class _PastTheGate(RuntimeError):
    pass


def _options(tmp_path: Path) -> episode.EpisodeOptions:
    return episode.EpisodeOptions(
        provider="custom", model="m", env="batchnorm_ema", difficulty="easy",
        out=tmp_path, api_key_env="NO_SUCH_KEY_FOR_TEST",
    )


def _stub_gate(monkeypatch: pytest.MonkeyPatch, result: dict) -> None:
    monkeypatch.setattr(instance_oracle_gate, "validate_case", lambda *a, **k: result)

    def _stop(*_a, **_k):
        raise _PastTheGate

    # First thing run_episode does after the gate is resolve credentials.
    monkeypatch.setattr(episode, "resolve_credentials", _stop)


def test_unreferenced_env_is_refused_without_the_campaign_opt_in(tmp_path, monkeypatch):
    monkeypatch.delenv("ARENA_ALLOW_COMPILE_ONLY", raising=False)
    _stub_gate(monkeypatch, {"status": "blocked", "reason": "reference_not_configured"})
    with pytest.raises(ValueError, match=ORACLE_FAILED):
        episode.run_episode(_options(tmp_path))


def test_unreferenced_env_proceeds_with_the_campaign_opt_in(tmp_path, monkeypatch):
    monkeypatch.setenv("ARENA_ALLOW_COMPILE_ONLY", "1")
    _stub_gate(monkeypatch, {"status": "blocked", "reason": "reference_not_configured"})
    with pytest.raises(_PastTheGate):
        episode.run_episode(_options(tmp_path))


@pytest.mark.parametrize(
    "reason", ["slow_reference_not_run", "root_mismatch", "pinned_config_drift", None]
)
def test_opt_in_never_bypasses_any_other_gate_failure(tmp_path, monkeypatch, reason):
    monkeypatch.setenv("ARENA_ALLOW_COMPILE_ONLY", "1")
    _stub_gate(monkeypatch, {"status": "blocked", "reason": reason})
    with pytest.raises(ValueError, match=ORACLE_FAILED):
        episode.run_episode(_options(tmp_path))


def test_suite_opts_in_only_the_compile_only_episode(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    from tests import test_exhaustive_campaign_recovery as recovery
    from tools import run_suite

    manifest = recovery._manifest()
    manifest["case_count"] = 2
    manifest["cases"] = [
        {"case_id": "referenced", "environment": "epistemic_games",
         "difficulty": "report,ambiguous,paired,balanced,bare_table", "seed": 0},
        {"case_id": "unreferenced", "environment": "batchnorm_ema",
         "difficulty": "easy", "seed": 0},
    ]
    monkeypatch.setenv("ATRIA_API_KEY", "non-secret-test-value")
    monkeypatch.setenv("ARENA_ALLOW_COMPILE_ONLY", "1")  # must not leak to referenced cases
    recovery._install_provider_free_gate_stubs(monkeypatch)
    seen: dict[str, str | None] = {}
    payload = json.dumps({"final": {"verdict": "PASS", "score": 1.0, "failure_mode": "pass"},
                          "http_attempts": 1, "run_dir": "x"})

    def fake_run(command, **kwargs):
        case = "unreferenced" if "batchnorm_ema" in command else "referenced"
        seen[case] = kwargs["env"].get("ARENA_ALLOW_COMPILE_ONLY")
        return SimpleNamespace(returncode=0, stdout=payload, stderr="")

    monkeypatch.setattr(run_suite.subprocess, "run", fake_run)
    kwargs = recovery._kwargs(tmp_path / "out")
    kwargs.update(max_http_attempts=10, max_api_calls=10, max_tokens_total=10 * 8)
    run_suite.run_suite(manifest, **kwargs)
    assert seen == {"referenced": None, "unreferenced": "1"}
