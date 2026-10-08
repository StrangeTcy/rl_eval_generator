from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from arena.providers import Completion, ProviderClient
from arena.secrets import ProviderCreds
from tools import model_preflight


class _Response:
    status = 200

    def __init__(self, payload: dict):
        self.payload = payload
        self.headers = {"x-request-id": "req-test"}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def test_anthropic_client_uses_messages_protocol_and_parses_response():
    seen = {}

    def opener(request, timeout):
        seen["url"] = request.full_url
        seen["headers"] = dict(request.header_items())
        seen["payload"] = json.loads(request.data)
        seen["timeout"] = timeout
        return _Response(
            {
                "id": "msg_test",
                "model": "claude-test",
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "READY"}],
                "usage": {"input_tokens": 4, "output_tokens": 1},
            }
        )

    client = ProviderClient(
        "anthropic",
        "secret-value",
        api_base="https://api.anthropic.example/v1",
        opener=opener,
        max_retries=0,
    )
    completion = client.complete(
        model="claude-test",
        messages=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "hello"},
        ],
        max_tokens=8,
        temperature=0.0,
    )

    assert seen["url"] == "https://api.anthropic.example/v1/messages"
    headers = {key.lower(): value for key, value in seen["headers"].items()}
    assert headers["x-api-key"] == "secret-value"
    assert headers["anthropic-version"] == "2023-06-01"
    assert seen["payload"]["system"] == "system"
    assert seen["payload"]["messages"] == [{"content": "hello", "role": "user"}]
    assert completion.content == "READY"
    assert completion.finish_reason == "end_turn"
    assert completion.request_id == "req-test"


def test_model_preflight_stops_after_first_failed_probe(monkeypatch, tmp_path: Path):
    class FakeClient:
        def __init__(self, *_args, **_kwargs):
            self.http_attempts_used = 0
            self.last_http_attempts = 0
            self.last_attempt_logs = []

        def complete(self, **_kwargs):
            self.http_attempts_used += 1
            self.last_http_attempts = 1
            return Completion(
                content="not READY",
                requested_model="model",
                resolved_model="model",
                finish_reason="stop",
                usage={"total_tokens": 2},
                raw_response={},
                latency_ms=1,
                request_id="id",
                response_headers={},
                status_code=200,
            )

    monkeypatch.setattr(model_preflight, "ProviderClient", FakeClient)
    monkeypatch.setattr(
        model_preflight,
        "resolve_provider",
        lambda *args, **kwargs: ProviderCreds(
            name="openai",
            api_key="secret-value",
            api_base="https://api.example/v1",
            source="env:OPENAI_API_KEY",
        ),
    )

    result = model_preflight.run_model_preflight(
        provider="openai",
        model="model",
        env_family="weird_machine",
        calls=3,
        out=tmp_path / "preflight.json",
    )

    assert result["status"] == "unavailable"
    assert result["completed_calls"] == 1
    artifact = json.loads((tmp_path / "preflight.json").read_text())
    assert artifact["api_key_exposed"] is False
    assert "secret-value" not in (tmp_path / "preflight.json").read_text()
