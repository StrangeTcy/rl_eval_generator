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
from arena.docker_backend import DockerBackend
from arena.episode import EpisodeOptions, run_episode
from arena.providers import ProviderClient, ProviderError, chat_completions_url, open_no_redirect

ROOT = Path(__file__).resolve().parents[1]  # noqa: E402


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


def test_episode_exception_traceback_canary_is_absent_from_artifacts(tmp_path, monkeypatch, capsys):
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
