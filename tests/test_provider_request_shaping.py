"""Offline checks for provider-specific request shaping.

These never touch the network: a fake opener captures the JSON body that
``ProviderClient.complete`` would POST, so per-provider request shaping
(completion-size key, reasoning passthrough, protected-field guard) is
asserted deterministically.
"""
from __future__ import annotations

import json

import pytest

from arena.providers import ProviderClient


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")
        self.status = 200
        self.headers: dict[str, str] = {}

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


class _FakeOpener:
    def __init__(self) -> None:
        self.captured: dict | None = None

    def __call__(self, req, timeout=None):
        self.captured = json.loads(req.data.decode("utf-8"))
        return _FakeResponse(
            {
                "model": self.captured.get("model"),
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"total_tokens": 1},
            }
        )


def _body(provider: str, **kwargs) -> dict:
    opener = _FakeOpener()
    client = ProviderClient(provider, "test-key-not-a-real-secret", opener=opener)
    params: dict = {
        "model": "m",
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 8192,
        "temperature": 0.7,
    }
    params.update(kwargs)
    client.complete(**params)
    assert opener.captured is not None
    return opener.captured


def test_mercury_uses_max_completion_tokens_and_passes_reasoning_effort():
    body = _body("mercury", model="mercury-2.5", request_extra={"reasoning_effort": "high"})
    assert body["max_completion_tokens"] == 8192
    assert "max_tokens" not in body
    assert body["reasoning_effort"] == "high"
    assert body["model"] == "mercury-2.5"
    assert body["stream"] is False


def test_other_providers_keep_max_tokens():
    for provider in ("atria", "groq", "nvidia", "openrouter"):
        body = _body(provider, model="m")
        assert body["max_tokens"] == 8192, provider
        assert "max_completion_tokens" not in body, provider


def test_request_extra_still_cannot_override_protected_max_tokens():
    with pytest.raises(ValueError):
        _body("mercury", request_extra={"max_tokens": 10})


# --- Responses-API surface (Atria controlled reasoning) -----------------


class _FakeResponsesResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")
        self.status = 200
        self.headers: dict[str, str] = {}

    def __enter__(self) -> "_FakeResponsesResponse":
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


class _FakeResponsesOpener:
    def __init__(self, output=None) -> None:
        self.captured: dict | None = None
        self.url: str | None = None
        self._output = output if output is not None else [
            {"type": "message", "content": [{"type": "output_text", "text": "2:3"}]}
        ]

    def __call__(self, req, timeout=None):
        self.url = req.full_url
        self.captured = json.loads(req.data.decode("utf-8"))
        return _FakeResponsesResponse(
            {
                "model": self.captured.get("model"),
                "status": "completed",
                "output": self._output,
                "usage": {"input_tokens": 11, "output_tokens": 7},
            }
        )


def _responses_call(provider: str, output=None, **kwargs):
    opener = _FakeResponsesOpener(output=output)
    client = ProviderClient(provider, "test-key-not-a-real-secret", opener=opener)
    completion = client.complete_responses(**kwargs)
    return opener, completion


def test_atria_responses_sends_nested_reasoning_effort_and_uses_responses_url():
    opener, _completion = _responses_call(
        "atria",
        input_text=[{"role": "user", "content": "hi"}],
        model="Atria-Dawn-Preview",
        reasoning_effort="high",
        max_output_tokens=1024,
    )
    assert opener.url is not None and opener.url.endswith("/v1/responses")
    assert opener.captured is not None
    assert opener.captured["model"] == "Atria-Dawn-Preview"
    assert opener.captured["reasoning"] == {"effort": "high"}
    assert opener.captured["max_output_tokens"] == 1024
    assert opener.captured["input"] == [{"role": "user", "content": "hi"}]
    assert opener.captured["stream"] is False
    # Chat-Completions-only shapes must not leak into the Responses body.
    assert "messages" not in opener.captured
    assert "max_tokens" not in opener.captured
    assert "reasoning_effort" not in opener.captured  # flat form is Chat-Completions only


def test_atria_responses_parses_output_text_status_and_usage():
    _opener, completion = _responses_call(
        "atria", input_text="hi", model="Atria-Dawn-Preview", reasoning_effort="high"
    )
    assert completion.content == "2:3"
    assert completion.finish_reason == "completed"
    assert completion.usage == {"prompt_tokens": 11, "completion_tokens": 7}
    assert completion.resolved_model == "Atria-Dawn-Preview"


def test_atria_responses_skips_reasoning_items_and_keeps_only_message_text():
    output = [
        {"type": "reasoning", "content": [{"type": "reasoning_text", "text": "private chain"}]},
        {"type": "message", "content": [{"type": "output_text", "text": "answer"}]},
    ]
    _opener, completion = _responses_call(
        "atria", output=output, input_text="hi", model="Atria-Dawn-Preview"
    )
    assert completion.content == "answer"
    assert "private chain" not in completion.content
