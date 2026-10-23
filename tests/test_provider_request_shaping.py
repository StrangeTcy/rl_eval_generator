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


def test_chat_retries_explicit_internal_fetch_failure_within_attempt_cap():
    transient = {
        "error": {
            "message": "fetch failed",
            "type": "api_error",
            "code": "internal",
            "param": None,
        }
    }
    success = {
        "model": "openai/gpt-6.1-sol",
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 2, "completion_tokens": 1},
    }

    class _QueueOpener:
        def __init__(self):
            self.payloads = [transient, success]
            self.calls = 0

        def __call__(self, req, timeout=None):
            self.calls += 1
            return _FakeResponse(self.payloads.pop(0))

    opener = _QueueOpener()
    client = ProviderClient(
        "synapse_garden",
        "offline-test-key",
        opener=opener,
        max_retries=3,
        max_http_attempts=2,
        backoff_base=0,
        jitter=0,
        sleep=lambda _seconds: None,
    )
    completion = client.complete(
        model="openai/gpt-6.1-sol",
        messages=[{"role": "user", "content": "offline"}],
        max_tokens=256,
        temperature=0.0,
    )

    assert completion.content == "ok"
    assert opener.calls == 2
    assert client.last_http_attempts == 2
    assert client.last_retry_count == 1
    assert client.last_attempt_logs[0]["error_type"] == "api_error"
    assert client.last_attempt_logs[0]["retryable"] is True


def test_chat_does_not_retry_quota_errors():
    quota_error = {
        "error": {
            "message": "insufficient quota",
            "type": "insufficient_quota",
            "code": "insufficient_quota",
        }
    }

    class _QueueOpener:
        calls = 0

        def __call__(self, req, timeout=None):
            self.calls += 1
            return _FakeResponse(quota_error)

    opener = _QueueOpener()
    client = ProviderClient(
        "synapse_garden",
        "offline-test-key",
        opener=opener,
        max_retries=3,
        backoff_base=0,
        jitter=0,
        sleep=lambda _seconds: None,
    )
    from arena.providers import ProviderError

    with pytest.raises(ProviderError) as exc:
        client.complete(
            model="openai/gpt-6.1-sol",
            messages=[{"role": "user", "content": "offline"}],
            max_tokens=256,
            temperature=0.0,
        )
    assert opener.calls == 1
    assert client.last_http_attempts == 1
    assert exc.value.retryable is False


def test_chat_retries_http_500_but_not_payment_or_auth_errors():
    from io import BytesIO
    from urllib.error import HTTPError
    from arena.providers import ProviderError

    success = {
        "model": "openai/gpt-6.1-sol",
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }

    class _ServerErrorThenSuccess:
        calls = 0

        def __call__(self, req, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise HTTPError(
                    req.full_url, 500, "upstream fetch failed", {},
                    BytesIO(b'{"error":{"message":"fetch failed","type":"api_error","code":"internal"}}'),
                )
            return _FakeResponse(success)

    opener = _ServerErrorThenSuccess()
    client = ProviderClient(
        "synapse_garden", "offline-test-key", opener=opener, max_retries=1,
        max_http_attempts=2, backoff_base=0, jitter=0, sleep=lambda _seconds: None,
    )
    completion = client.complete(
        model="openai/gpt-6.1-sol",
        messages=[{"role": "user", "content": "offline"}],
        max_tokens=256,
        temperature=0.0,
    )
    assert completion.content == "ok"
    assert opener.calls == 2
    assert client.last_http_attempts == 2

    for status in (401, 402):
        class _NonRetryableError:
            calls = 0

            def __call__(self, req, timeout=None):
                self.calls += 1
                raise HTTPError(
                    req.full_url, status, "auth or quota denied", {},
                    BytesIO(b'{"error":{"message":"denied"}}'),
                )

        opener = _NonRetryableError()
        client = ProviderClient(
            "synapse_garden", "offline-test-key", opener=opener, max_retries=3,
            backoff_base=0, jitter=0, sleep=lambda _seconds: None,
        )
        with pytest.raises(ProviderError) as exc:
            client.complete(
                model="openai/gpt-6.1-sol",
                messages=[{"role": "user", "content": "offline"}],
                max_tokens=256,
                temperature=0.0,
            )
        assert opener.calls == 1
        assert client.last_http_attempts == 1
        assert exc.value.retryable is False


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


def test_responses_reads_item_level_text_field():
    output = [{"type": "message", "text": "direct-text"}]
    _opener, completion = _responses_call(
        "atria", output=output, input_text="hi", model="Atria-Dawn-Preview"
    )
    assert completion.content == "direct-text"


def test_responses_reads_string_content():
    output = [{"type": "message", "content": "string-content"}]
    _opener, completion = _responses_call(
        "atria", output=output, input_text="hi", model="Atria-Dawn-Preview"
    )
    assert completion.content == "string-content"


def test_responses_prefers_output_text_convenience_field():
    class _Opener:
        def __call__(self, req, timeout=None):
            return _FakeResponsesResponse(
                {
                    "model": "Atria-Dawn-Preview",
                    "status": "completed",
                    "output_text": "convenience-answer",
                    "output": [],
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                }
            )

    client = ProviderClient("atria", "test-key-not-a-real-secret", opener=_Opener())
    completion = client.complete_responses("hi", model="Atria-Dawn-Preview")
    assert completion.content == "convenience-answer"


def test_responses_raises_a_diagnostic_error_when_reasoning_ate_the_budget():
    from arena.providers import ProviderError

    class _Opener:
        def __call__(self, req, timeout=None):
            # status=incomplete + a reasoning-only output: the visible answer was
            # truncated away because max_output_tokens went to reasoning.
            return _FakeResponsesResponse(
                {
                    "model": "Atria-Dawn-Preview",
                    "status": "incomplete",
                    "output": [{"type": "reasoning", "summary": []}],
                    "usage": {"input_tokens": 10, "output_tokens": 1024},
                }
            )

    client = ProviderClient("atria", "test-key-not-a-real-secret", opener=_Opener())
    with pytest.raises(ProviderError) as exc:
        client.complete_responses(
            "hi", model="Atria-Dawn-Preview", reasoning_effort="high", max_output_tokens=1024
        )
    message = str(exc.value)
    assert "no text" in message
    assert "incomplete" in message          # status surfaced for diagnosis
    assert "max_output_tokens" in message   # the truncation hint is in the log


# --- Responses-API budget and attempt accounting (Atria) ------------------


def test_responses_counts_physical_attempts_and_records_them():
    """The global HTTP-attempt budget must bound the Responses wire too.

    ``complete`` enforces ``max_http_attempts`` and fills ``last_attempt_logs``;
    ``complete_responses`` is the same client against a different endpoint, so a
    dispatch that declared a physical-attempt ceiling has to see the same
    accounting on the Atria path or the controller's trace reports zero
    attempts for a request that really happened.
    """

    class _Success:
        def __call__(self, req, timeout=None):
            return _FakeResponsesResponse(
                {
                    "model": "Atria-Dawn-Preview",
                    "status": "completed",
                    "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}],
                    "usage": {"input_tokens": 3, "output_tokens": 2},
                }
            )

    client = ProviderClient(
        "atria", "test-key-not-a-real-secret", opener=_Success(), max_http_attempts=4
    )
    completion = client.complete_responses("hi", model="Atria-Dawn-Preview", reasoning_effort="high")
    assert completion.content == "ok"
    assert client.http_attempts_used == 1
    assert client.last_http_attempts == 1
    assert client.last_attempt_logs[-1]["error_type"] == "success"
    assert client.last_attempt_logs[-1]["status_code"] == 200


def test_responses_retries_are_logged_and_counted():
    from io import BytesIO
    from urllib.error import HTTPError

    class _ServerErrorThenSuccess:
        calls = 0

        def __call__(self, req, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise HTTPError(
                    req.full_url, 500, "upstream fetch failed", {},
                    BytesIO(b'{"error":{"message":"fetch failed","type":"api_error","code":"internal"}}'),
                )
            return _FakeResponsesResponse(
                {
                    "model": "Atria-Dawn-Preview",
                    "status": "completed",
                    "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}],
                    "usage": {"input_tokens": 3, "output_tokens": 2},
                }
            )

    opener = _ServerErrorThenSuccess()
    client = ProviderClient(
        "atria", "test-key-not-a-real-secret", opener=opener, max_retries=2,
        max_http_attempts=4, backoff_base=0, jitter=0, sleep=lambda _seconds: None,
    )
    completion = client.complete_responses("hi", model="Atria-Dawn-Preview", reasoning_effort="high")
    assert completion.content == "ok"
    assert opener.calls == 2
    assert client.last_http_attempts == 2
    assert client.last_retry_count == 1
    assert client.last_attempt_logs[0]["status_code"] == 500
    assert client.last_attempt_logs[0]["retryable"] is True
    assert client.last_attempt_logs[-1]["error_type"] == "success"


def test_responses_stops_retrying_when_the_physical_budget_is_spent():
    from io import BytesIO
    from urllib.error import HTTPError
    from arena.providers import ProviderError

    class _AlwaysServerError:
        calls = 0

        def __call__(self, req, timeout=None):
            self.calls += 1
            raise HTTPError(
                req.full_url, 429, "rate limited", {"Retry-After": "0"},
                BytesIO(b'{"error":{"message":"rate limited","type":"rate_limit"}}'),
            )

    opener = _AlwaysServerError()
    client = ProviderClient(
        "atria", "test-key-not-a-real-secret", opener=opener, max_retries=5,
        max_http_attempts=2, backoff_base=0, jitter=0, sleep=lambda _seconds: None,
    )
    with pytest.raises(ProviderError) as exc:
        client.complete_responses("hi", model="Atria-Dawn-Preview", reasoning_effort="high")
    # Two physical attempts were authorised; the client must not issue a third.
    assert opener.calls == 2
    assert client.http_attempts_used == 2
    assert exc.value.retryable is True
    assert exc.value.status_code == 429


def test_responses_refuses_a_request_once_the_budget_is_already_spent():
    from arena.providers import ProviderError

    client = ProviderClient(
        "atria", "test-key-not-a-real-secret",
        opener=lambda req, timeout=None: pytest.fail("no request may be issued"),
        max_http_attempts=1,
    )
    client.http_attempts_used = 1
    with pytest.raises(ProviderError) as exc:
        client.complete_responses("hi", model="Atria-Dawn-Preview", reasoning_effort="high")
    assert "attempt budget exhausted" in str(exc.value)
    assert exc.value.retryable is False
    assert client.last_attempt_logs[-1]["error_type"] == "attempt_budget_exhausted"
