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
