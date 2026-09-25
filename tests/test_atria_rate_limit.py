from __future__ import annotations

import io
import json
from urllib.error import HTTPError

import pytest

from arena.providers import ProviderClient, ProviderError


class _Response:
    status = 200

    def __init__(self, *, remaining: str = "59", limit: str = "60"):
        self.headers = {
            "x-request-id": "rate-request",
            "x-rpm-limit": limit,
            "x-rpm-remaining": remaining,
        }

    def read(self):
        return json.dumps(
            {
                "id": "chat-rate",
                "model": "Atria-Dawn-Preview",
                "choices": [
                    {
                        "message": {"content": "READY"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }
        ).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


def test_shared_client_paces_and_records_atria_rate_headers():
    sleeps: list[float] = []

    def opener(req, timeout):
        return _Response(limit="30")

    client = ProviderClient(
        "atria",
        "offline-fake-secret",
        api_base="https://api.atria-asi.ai/v1",
        max_retries=0,
        min_interval_seconds=1.1,
        opener=opener,
        sleep=sleeps.append,
    )
    first = client.complete(model="Atria-Dawn-Preview", messages=[], max_tokens=2, temperature=0)
    second = client.complete(model="Atria-Dawn-Preview", messages=[], max_tokens=2, temperature=0)
    assert first.response_headers["x-rpm-limit"] == "30"
    assert first.response_headers["x-rpm-remaining"] == "59"
    assert second.request_id == "rate-request"
    assert client.min_interval_seconds == 2.0
    assert len(sleeps) == 1
    assert sleeps[0] == pytest.approx(2.0, abs=0.01)
    assert client.last_attempt_logs[-1]["response_headers"]["x-rpm-remaining"] == "59"


def test_retry_after_is_used_for_transient_atria_response_and_headers_are_safe():
    sleeps: list[float] = []
    calls = 0

    def opener(req, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise HTTPError(
                req.full_url,
                429,
                "rate limited",
                {
                    "Retry-After": "3.5",
                    "x-rpm-limit": "60",
                    "x-rpm-remaining": "0",
                    "Authorization": "Bearer offline-fake-secret",
                },
                io.BytesIO(b"rate limited"),
            )
        return _Response()

    client = ProviderClient(
        "atria",
        "offline-fake-secret",
        api_base="https://api.atria-asi.ai/v1",
        max_retries=1,
        min_interval_seconds=0,
        opener=opener,
        sleep=sleeps.append,
    )
    completion = client.complete(model="Atria-Dawn-Preview", messages=[], max_tokens=2, temperature=0)
    assert completion.status_code == 200
    assert sleeps == [3.5]
    assert all("offline-fake-secret" not in json.dumps(item) for item in client.last_attempt_logs)
    assert client.last_attempt_logs[0]["response_headers"]["x-rpm-remaining"] == "0"


def test_shared_client_rejects_negative_pacing():
    try:
        ProviderClient(
            "atria",
            "offline-fake-secret",
            api_base="https://api.atria-asi.ai/v1",
            min_interval_seconds=-0.1,
        )
    except ValueError as exc:
        assert "min_interval_seconds" in str(exc)
    else:
        raise AssertionError("negative pacing must be rejected")
