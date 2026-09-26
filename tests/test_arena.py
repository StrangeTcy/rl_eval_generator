"""Focused tests for the provider-neutral controller and Docker argv builder."""
from __future__ import annotations

import http.server
import io
import json
import subprocess
import sys
import threading
from pathlib import Path
from urllib import request
from urllib.error import HTTPError

import pytest

import arena.episode as episode_module
from arena.artifacts import _diff_directories
from arena.docker_backend import DockerBackend
from arena.episode import EpisodeOptions, run_episode
from arena.providers import (
    Completion,
    ProviderClient,
    ProviderError,
    chat_completions_url,
    open_no_redirect,
)

ROOT = Path(__file__).resolve().parents[1]  # noqa: E402


def _stub_passing_oracle(monkeypatch):
    # Controller/provider failure tests exercise a mocked episode; the real
    # three-variant gate is tested separately with an actual generated judge.
    monkeypatch.setattr("tools.instance_oracle_gate.validate_case", lambda *args, **kwargs: {"status": "passed"})
    monkeypatch.setattr("tools.instance_oracle_gate.verify_reset_matches_oracle", lambda *args: "mock-hash")


class _Response:
    headers = {"x-request-id": "req-1", "content-type": "application/json"}

    def read(self):
        return json.dumps(
            {
                "id": "chat-1",
                "model": "provider/model-version",
                "choices": [
                    {
                        "message": {"content": '{"type":"submit"}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 4, "completion_tokens": 3},
                "provider": "upstream",
            }
        ).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


def test_openrouter_completion_uses_chat_endpoint_and_safe_headers():
    calls = []

    def opener(req, timeout):
        calls.append((req.full_url, req.headers, json.loads(req.data)))
        return _Response()

    completion = ProviderClient("openrouter", "SECRET", opener=opener).complete(
        model="requested/model",
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=10,
        temperature=0,
        request_extra={"reasoning": {"effort": "high"}},
    )
    assert calls[0][0] == "https://openrouter.ai/api/v1/chat/completions"
    assert calls[0][1]["Authorization"] == "Bearer SECRET"
    assert calls[0][1]["X-openrouter-title"] == "rl_eval_generator arena"
    assert calls[0][2]["model"] == "requested/model"
    assert calls[0][2]["stream"] is False
    assert completion.resolved_model == "provider/model-version"
    assert completion.usage["completion_tokens"] == 3


def test_provider_endpoints_require_absolute_https():
    assert chat_completions_url("https://provider.example/v1") == (
        "https://provider.example/v1/chat/completions"
    )
    with pytest.raises(ValueError, match="HTTPS"):
        chat_completions_url("http://provider.example/v1")
    with pytest.raises(ValueError, match="HTTPS"):
        chat_completions_url("https://user:password@provider.example/v1")
    with pytest.raises(ValueError, match="HTTPS"):
        ProviderClient("custom", "SECRET", api_base="http://provider.example/v1")


def test_authenticated_redirect_never_reaches_destination():
    seen = []

    class RedirectHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            seen.append((self.path, self.headers.get("Authorization")))
            if self.path == "/start":
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/destination")
                self.end_headers()
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"data": []}')

        def log_message(self, *_args):
            return

    server = http.server.HTTPServer(("127.0.0.1", 0), RedirectHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        req = request.Request(
            f"http://127.0.0.1:{server.server_port}/start",
            headers={"Authorization": "Bearer REDIRECT_CANARY"},
        )
        with pytest.raises(HTTPError) as raised:
            open_no_redirect(req, timeout=2)
        assert raised.value.code == 302
        assert ("/start", "Bearer REDIRECT_CANARY") in seen
        assert not any(path == "/destination" for path, _authorization in seen)
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_provider_retries_429_but_not_bad_request():
    attempts = []

    def transient(req, timeout):
        attempts.append(1)
        if len(attempts) == 1:
            raise HTTPError(req.full_url, 429, "busy", {"Retry-After": "1"}, io.BytesIO(b"busy"))
        return _Response()

    completion = ProviderClient(
        "custom",
        "SECRET",
        api_base="https://example.invalid/v1",
        opener=transient,
        sleep=lambda _delay: None,
    ).complete(model="m", messages=[], max_tokens=1, temperature=0)
    assert completion.content == '{"type":"submit"}'
    assert len(attempts) == 2

    bad_attempts = []

    def bad_request(req, timeout):
        bad_attempts.append(1)
        raise HTTPError(
            req.full_url,
            401,
            "no",
            {"X-Canary": "SECRET"},
            io.BytesIO(b"SECRET"),
        )

    try:
        ProviderClient("custom", "SECRET", api_base="https://example.invalid/v1", opener=bad_request).complete(
            model="m", messages=[], max_tokens=1, temperature=0
        )
    except ProviderError as exc:
        assert exc.status_code == 401
        assert "SECRET" not in exc.body
        assert "SECRET" not in json.dumps(exc.response_headers)
    else:
        raise AssertionError("expected ProviderError")
    assert len(bad_attempts) == 1


def test_provider_retries_only_429_503_504_and_logs_each_attempt():
    statuses = [503, 504, 429]
    calls = []
    sleeps = []
    logs = []

    def opener(req, timeout):
        calls.append(json.loads(req.data))
        status = statuses.pop(0) if statuses else 200
        if status != 200:
            raise HTTPError(
                req.full_url,
                status,
                "transient",
                {"Retry-After": "1.25"},
                io.BytesIO(b"transient"),
            )
        return _Response()

    completion = ProviderClient(
        "custom",
        "SECRET",
        api_base="https://example.invalid/v1",
        max_retries=5,
        opener=opener,
        sleep=sleeps.append,
        error_logger=logs.append,
    ).complete(
        model="nvidia/nemotron-3-super-120b-a12b",
        messages=[],
        max_tokens=8,
        temperature=1.0,
        top_p=0.95,
        request_extra={"chat_template_kwargs": {"enable_thinking": False}},
    )
    assert completion.status_code == 200
    assert len(calls) == 4
    assert all(payload["temperature"] == 1.0 for payload in calls)
    assert all(payload["top_p"] == 0.95 for payload in calls)
    assert all(payload["stream"] is False for payload in calls)
    assert calls[0]["chat_template_kwargs"]["enable_thinking"] is False
    assert sleeps == [1.25, 1.25, 1.25]

    with pytest.raises(ValueError, match="stream"):
        ProviderClient(
            "custom",
            "SECRET",
            api_base="https://example.invalid/v1",
            opener=opener,
        ).complete(
            model="m",
            messages=[],
            max_tokens=1,
            temperature=1.0,
            request_extra={"stream": True},
        )
    assert [record["status_code"] for record in logs] == [503, 504, 429, 200]
    assert all(isinstance(record["elapsed_ms"], int) for record in logs)


def test_provider_http_budget_is_shared_across_logical_calls():
    calls = []

    def opener(req, timeout):
        calls.append(1)
        return _Response()

    client = ProviderClient(
        "custom",
        "SECRET",
        api_base="https://example.invalid/v1",
        max_retries=0,
        max_http_attempts=1,
        opener=opener,
    )
    client.complete(model="m", messages=[], max_tokens=1, temperature=0)
    with pytest.raises(ProviderError, match="attempt budget"):
        client.complete(model="m", messages=[], max_tokens=1, temperature=0)
    assert len(calls) == 1
    assert client.http_attempts_used == 1


def test_controller_rejects_legacy_unknown_failure_mode_as_judge_error():
    result = episode_module._submitted_final({"info": {"judge_result": {
        "verdict": "FAIL", "score": 0, "failure_mode": "unknown"
    }}})
    assert result["failure_mode"] == "judge_runtime_error"
    assert "unclassified" in result["notes"][0]


def test_upstream_502_stops_as_provider_error_without_judging(tmp_path, monkeypatch):
    _stub_passing_oracle(monkeypatch)
    episode_dir = tmp_path / "episode"
    episode_dir.mkdir()
    runner_calls = []
    provider_calls = []

    def bad_gateway(req, timeout):
        provider_calls.append(req.full_url)
        raise HTTPError(
            req.full_url, 502, "bad gateway", {},
            io.BytesIO(b'{"error":{"message":"bad_gateway_error"}}'),
        )

    def offline_runner(arguments):
        runner_calls.append(arguments[0])
        assert arguments[0] == "reset"
        return {"observation": "ready", "done": False, "info": {"episode_dir": str(episode_dir)}}

    def offline_client(provider, api_key, **kwargs):
        return ProviderClient(provider, api_key, opener=bad_gateway, **kwargs)

    monkeypatch.setattr(episode_module, "ProviderClient", offline_client)
    monkeypatch.setattr(episode_module, "_run_env_runner", offline_runner)
    result = run_episode(EpisodeOptions(
        provider="custom", model="offline/model", api_key="FAKE_OFFLINE_KEY",
        api_base="https://example.invalid/v1", env="glyph",
        difficulty="easy,easy,easy,easy,easy,easy", sandbox="local",
        max_steps=3, out=tmp_path / "runs",
    ))
    assert result["final"]["failure_mode"] == "api_error"
    assert result["final"]["verdict"] == "FAIL"
    assert runner_calls == ["reset"] and len(provider_calls) == 1
    assert "502" in (Path(result["run_dir"]) / "api_errors.jsonl").read_text()


def test_episode_exception_traceback_canary_is_absent_from_artifacts(tmp_path, monkeypatch, capsys):
    _stub_passing_oracle(monkeypatch)
    canary = "exception-header-credential-canary"
    episode_dir = tmp_path / "episode"
    episode_dir.mkdir()

    class ExplodingProvider:
        last_retry_count = 0
        last_attempts = []

        def __init__(self, provider, api_key, **kwargs):
            self.provider = provider

        def complete(self, **kwargs):
            raise RuntimeError(
                "upstream exception included Authorization: Bearer " + canary
            )

    def fake_env_runner(arguments):
        assert arguments[0] == "reset"
        return {
            "observation": "initial observation",
            "reward": 0.0,
            "done": False,
            "info": {"episode_dir": str(episode_dir)},
        }

    monkeypatch.setattr(episode_module, "ProviderClient", ExplodingProvider)
    monkeypatch.setattr(episode_module, "_run_env_runner", fake_env_runner)
    result = run_episode(
        EpisodeOptions(
            provider="custom",
            model="test/model",
            api_key=canary,
            api_base="https://example.invalid/v1",
            env="glyph",
            difficulty="easy,easy,easy,easy,easy,easy",
            sandbox="local",
            out=tmp_path / "runs",
            max_steps=1,
        )
    )

    run_dir = Path(result["run_dir"])
    captured = capsys.readouterr()
    assert canary not in json.dumps(result)
    assert canary not in captured.out + captured.err
    for path in run_dir.rglob("*"):
        if path.is_file():
            assert canary not in path.read_text(encoding="utf-8", errors="replace")


@pytest.mark.parametrize("explicit_submit", [True, False])
def test_missing_judge_response_is_controller_error_not_model_failure(
    tmp_path, monkeypatch, explicit_submit
):
    _stub_passing_oracle(monkeypatch)
    episode_dir = tmp_path / "episode"
    episode_dir.mkdir()
    provider_calls = []
    runner_calls = []

    class OfflineProvider:
        last_retry_count = 0
        last_http_attempts = 1
        http_attempts_used = 1

        def __init__(self, *_args, **_kwargs):
            pass

        def complete(self, **kwargs):
            provider_calls.append(kwargs)
            return Completion(
                content=json.dumps({"type": "submit", "confirm": True} if explicit_submit else {"cmd": "ls"}),
                requested_model="offline/model", resolved_model="offline/model", finish_reason="stop",
                usage={}, raw_response={}, latency_ms=0, request_id=None, response_headers={},
            )

    def offline_runner(arguments):
        runner_calls.append(arguments[0])
        if arguments[0] == "reset":
            return {"observation": "ready", "done": False, "info": {"episode_dir": str(episode_dir)}}
        if arguments[0] == "step":
            return {
                "observation": "Submission error: judge timed out" if explicit_submit else "ls output",
                "done": True, "info": {"error": "judge timed out"} if explicit_submit else {},
            }
        assert arguments[0] == "submit"
        return {"observation": "Submission error: judge timed out", "done": True,
                "info": {"error": "judge timed out"}}

    monkeypatch.setattr(episode_module, "ProviderClient", OfflineProvider)
    monkeypatch.setattr(episode_module, "_run_env_runner", offline_runner)
    result = run_episode(EpisodeOptions(
        provider="custom", model="offline/model", api_key="FAKE_OFFLINE_KEY",
        api_base="https://example.invalid/v1", env="glyph",
        difficulty="easy,easy,easy,easy,easy,easy", sandbox="local",
        max_steps=1, out=tmp_path / "runs",
    ))
    assert result["final"]["failure_mode"] == "controller_error"
    assert result["final"]["score"] == 0
    assert runner_calls == (["reset", "step"] if explicit_submit else ["reset", "step", "submit"])
    assert len(provider_calls) == 1  # no paid retry after a judge failure
    final = json.loads((Path(result["run_dir"]) / "final.json").read_text())
    assert final["failure_mode"] == "controller_error"


def test_agent_sandbox_failure_stops_before_auto_submit_or_more_provider_calls(
    tmp_path, monkeypatch
):
    _stub_passing_oracle(monkeypatch)
    episode_dir = tmp_path / "episode"
    episode_dir.mkdir()
    requests = []
    commands = []

    class OfflineProvider:
        last_retry_count = 0
        http_attempts_used = 1

        def __init__(self, *_args, **_kwargs):
            pass

        def complete(self, **_kwargs):
            requests.append(1)
            return Completion(
                content='{"cmd":"ls"}', requested_model="offline/model",
                resolved_model="offline/model", finish_reason="stop", usage={},
                raw_response={}, latency_ms=0, request_id=None, response_headers={},
            )

    def offline_runner(args):
        commands.append(args[0])
        if args[0] == "reset":
            return {"observation": "ready", "done": False, "info": {"episode_dir": str(episode_dir)}}
        assert args[0] == "step"  # any auto-submit would be an infrastructure retry
        return {"observation": "[stderr] Docker command timed out", "done": True,
                "info": {"infrastructure_failure": "agent_container_error", "returncode": 125}}

    monkeypatch.setattr(episode_module, "ProviderClient", OfflineProvider)
    monkeypatch.setattr(episode_module, "_run_env_runner", offline_runner)
    result = run_episode(EpisodeOptions(
        provider="custom", model="offline/model", api_key="FAKE_OFFLINE_KEY",
        api_base="https://example.invalid/v1", env="glyph",
        difficulty="easy,easy,easy,easy,easy,easy", sandbox="local",
        max_steps=3, out=tmp_path / "runs",
    ))
    assert result["final"]["failure_mode"] == "controller_error"
    assert commands == ["reset", "step"] and requests == [1]


def test_docker_image_tags_are_lowercase_for_timestamped_episode_ids(tmp_path):
    commands = []

    def runner(command, **kwargs):
        commands.append(command)
        if command[1] == "version":
            return subprocess.CompletedProcess(command, 0, stdout="28.0.0\n", stderr="")
        if command[1] == "build":
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[1] == "image":
            return subprocess.CompletedProcess(
                command, 0, stdout=json.dumps({"Id": "sha256:test"}), stderr=""
            )
        raise AssertionError(f"unexpected Docker command: {command}")

    (tmp_path / "agent").mkdir()
    (tmp_path / "judge").mkdir()
    backend = DockerBackend(command_runner=runner)
    agent, judge = backend.build_environment(
        tmp_path,
        "arena_regex_state_machine_20260923T084312Z_accc8832",
    )
    assert agent.name == agent.name.lower()
    assert judge.name == judge.name.lower()
    assert "20260923t084312z" in agent.name
    assert "20260923t084312z" in judge.name
    assert all("-t" not in command or command[command.index("-t") + 1] == command[command.index("-t") + 1].lower() for command in commands)


def test_docker_argv_has_no_network_or_api_key_environment(tmp_path):
    backend = DockerBackend()
    argv = backend.agent_command("agent-image", ROOT / ".episodes", ROOT / "shared", "echo hi")
    assert "--network" in argv and argv[argv.index("--network") + 1] == "none"
    assert "--cap-drop" in argv and argv[argv.index("--cap-drop") + 1] == "ALL"
    assert "--read-only" in argv
    assert "echo hi" in argv
    assert not any("API_KEY" in part or "TOKEN" in part for part in argv)

    judge_argv = backend.trajectory_judge_command(
        "trajectory-judge:local",
        tmp_path / "cases.jsonl",
        tmp_path / "answers.jsonl",
        tmp_path / "judge-output",
    )
    assert "--network" in judge_argv and judge_argv[judge_argv.index("--network") + 1] == "none"
    assert "--read-only" in judge_argv
    assert "--tmpfs" in judge_argv
    assert not any("API_KEY" in part or "TOKEN" in part for part in judge_argv)


def test_workspace_diff_handles_added_and_deleted_files(tmp_path):
    original = tmp_path / "original"
    current = tmp_path / "current"
    original.mkdir()
    current.mkdir()
    (original / "kept.txt").write_text("before\n", encoding="utf-8")
    (original / "deleted.txt").write_text("removed\n", encoding="utf-8")
    (current / "kept.txt").write_text("after\n", encoding="utf-8")
    (current / "added.txt").write_text("new\n", encoding="utf-8")

    diff = _diff_directories(original, current)

    assert "before/added.txt" in diff
    assert "after/added.txt" in diff
    assert "before/deleted.txt" in diff
    assert "after/deleted.txt" in diff
    assert "before/kept.txt" in diff


def test_recurrent_depth_generation_is_registered():
    output_name = "smoke_rd_registered"
    output = ROOT / output_name
    subprocess.run(["rm", "-rf", output_name], cwd=ROOT, check=False)
    result = subprocess.run(
        [
            sys.executable,
            "generate_env.py",
            "--env",
            "rd_state_carry",
            "--name",
            output_name,
            "--difficulty",
            "hard,hard,hard,hard,hard",
            "--seed",
            "9",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (output / "agent/workspace/recurrent_block.py").is_file()
    assert "%%" not in "\n".join(p.read_text(errors="ignore") for p in output.rglob("*") if p.is_file())
    subprocess.run(["rm", "-rf", str(output)], cwd=ROOT, check=False)
