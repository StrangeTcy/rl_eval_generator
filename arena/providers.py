"""Provider-neutral OpenAI-compatible chat completion clients.

The arena deliberately keeps the provider client on the host.  Generated agent
containers never receive the API key and only execute the actions returned by the
client.
"""
from __future__ import annotations

import json
import random
import socket
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import error, request
from urllib.parse import urlsplit

from .secrets import (
    PROVIDER_DEFAULT_BASE,
    PROVIDER_ENV,
    ProviderCreds,
    redact_text,
    resolve_provider,
)

PROVIDERS: dict[str, dict[str, str | None]] = {
    name: {
        "api_base": base,
        "key_env": env_names[0],
    }
    for name, base in PROVIDER_DEFAULT_BASE.items()
    for env_names in [PROVIDER_ENV[name]]
}

# Keep this alias available to callers that want the resolved profile type
# without importing the secrets module directly.
ResolvedProvider = ProviderCreds


class _RejectRedirectHandler(request.HTTPRedirectHandler):
    """Do not forward authenticated requests to any redirected destination."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        raise error.HTTPError(req.full_url, code, "authenticated redirects are disabled", headers, None)


_NO_REDIRECT_OPENER = request.build_opener(_RejectRedirectHandler)


def open_no_redirect(req: request.Request, timeout: float):
    """Open an authenticated request without following any HTTP redirect."""

    return _NO_REDIRECT_OPENER.open(req, timeout=timeout)


def require_https(url: str) -> None:
    """Require an absolute HTTPS endpoint for provider traffic."""

    parsed = urlsplit(url)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("provider endpoints must use an absolute HTTPS URL without URL credentials")


@dataclass
class Completion:
    """The provider-independent portion of a chat completion response."""

    content: str
    requested_model: str
    resolved_model: str | None
    finish_reason: str | None
    usage: dict[str, Any]
    raw_response: dict[str, Any]
    latency_ms: int
    request_id: str | None
    response_headers: dict[str, str]
    provider: str = ""
    upstream_provider: str | None = None


class ProviderError(RuntimeError):
    """A sanitized provider failure.

    ``body`` is intentionally capped and sanitized before it is stored.  The
    exception never includes the Authorization header or the supplied key.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: str = "",
        request_id: str | None = None,
        response_headers: Mapping[str, str] | None = None,
        retryable: bool = False,
        attempts: int = 1,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body
        self.request_id = request_id
        self.response_headers = dict(response_headers or {})
        self.retryable = retryable
        self.attempts = attempts


@dataclass
class ProviderAttempt:
    """A sanitized record of one failed HTTP attempt."""

    attempted_at: str
    status_code: int | None
    error_type: str
    body: str
    request_id: str | None
    retryable: bool
    attempt: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "attempted_at": self.attempted_at,
            "status_code": self.status_code,
            "error_type": self.error_type,
            "body": self.body,
            "request_id": self.request_id,
            "retryable": self.retryable,
            "attempt": self.attempt,
        }


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _redact_text(text: str, secret: str | None = None, limit: int = 4000) -> str:
    """Return a bounded provider error body without credentials."""

    return redact_text(text[:limit], [secret] if secret else None)


def _safe_headers(
    headers: Mapping[str, str], secret: str | None = None
) -> dict[str, str]:
    unsafe = {"authorization", "proxy-authorization", "cookie", "set-cookie", "x-api-key"}
    return {
        str(key): redact_text(str(value), [secret] if secret else None)
        for key, value in headers.items()
        if str(key).lower() not in unsafe and "token" not in str(key).lower()
    }


def resolve_credentials(
    provider: str,
    *,
    api_key: str | None = None,
    api_key_env: str | None = None,
    api_base: str | None = None,
    secret_path: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    """Resolve ``(api_key, environment_name)`` without ever printing it."""

    env = environ if environ is not None else __import__("os").environ
    credentials = resolve_provider(
        provider,
        api_key=api_key,
        api_key_env=api_key_env,
        api_base=api_base,
        secret_path=secret_path,
        environ=env,
    )
    if api_key:
        selected_env = api_key_env or PROVIDER_ENV[credentials.name][0]
    elif api_key_env and env.get(api_key_env):
        selected_env = api_key_env
    else:
        selected_env = next(
            (name for name in PROVIDER_ENV[credentials.name] if env.get(name)),
            api_key_env or PROVIDER_ENV[credentials.name][0],
        )
    return credentials.api_key, selected_env


def resolve_api_base(
    provider: str,
    api_base: str | None = None,
    *,
    secret_path: Path | None = None,
) -> str:
    # require_key=False lets planning and review code resolve a file/profile
    # endpoint without requiring a credential until the live request starts.
    credentials = resolve_provider(
        provider,
        api_base=api_base,
        secret_path=secret_path,
        require_key=False,
    )
    require_https(credentials.api_base)
    return credentials.api_base


def chat_completions_url(api_base: str) -> str:
    """Normalize a base URL to the required OpenAI-compatible endpoint."""

    base = api_base.rstrip("/")
    url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
    require_https(url)
    return url


def _content_from_message(message: Any) -> str:
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    # Some OpenAI-compatible providers return a list of typed content parts.
    if isinstance(content, list):
        pieces: list[str] = []
        for part in content:
            if isinstance(part, str):
                pieces.append(part)
            elif isinstance(part, dict) and isinstance(part.get("text"), str):
                pieces.append(part["text"])
        return "".join(pieces)
    if content is None:
        return ""
    return str(content)


def _request_id(headers: Mapping[str, str], data: Mapping[str, Any]) -> str | None:
    for key, value in headers.items():
        if key.lower() in {"x-request-id", "request-id", "openrouter-request-id"}:
            return str(value)
    value = data.get("id")
    return str(value) if value is not None else None


def _validate_request_extra(extra: Mapping[str, Any] | None) -> dict[str, Any]:
    if extra is None:
        return {}
    if not isinstance(extra, Mapping):
        raise ValueError("request-extra must be a JSON object")
    forbidden = {"model", "messages", "authorization", "headers"}
    blocked = sorted(str(key) for key in extra if str(key).lower() in forbidden)
    if blocked:
        raise ValueError(
            "request-extra may not override protected fields: " + ", ".join(blocked)
        )
    return dict(extra)


class ProviderClient:
    """A small urllib-based client for OpenAI-compatible chat APIs."""

    def __init__(
        self,
        provider: str,
        api_key: str,
        *,
        api_base: str | None = None,
        timeout: float = 120.0,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        backoff_max: float = 8.0,
        jitter: float = 0.25,
        opener: Any = None,
        sleep: Callable[[float], None] = time.sleep,
        random_fn: Callable[[], float] = random.random,
        error_logger: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key must not be empty")
        self.provider = provider
        self.api_key = api_key
        self.api_base = resolve_api_base(provider, api_base)
        self.timeout = timeout
        self.max_retries = max(0, int(max_retries))
        self.backoff_base = max(0.0, float(backoff_base))
        self.backoff_max = max(0.0, float(backoff_max))
        self.jitter = max(0.0, float(jitter))
        self.opener = opener or open_no_redirect
        self.sleep = sleep
        self.random_fn = random_fn
        self.error_logger = error_logger
        self.last_retry_count = 0
        self.last_attempts: list[ProviderAttempt] = []

    def headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.provider == "openrouter":
            headers.update(
                {
                    "HTTP-Referer": "https://github.com/StrangeTcy/rl_eval_generator",
                    "X-OpenRouter-Title": "rl_eval_generator arena",
                }
            )
        return headers

    def _record_failure(self, attempt: ProviderAttempt) -> None:
        self.last_attempts.append(attempt)
        if self.error_logger:
            self.error_logger(attempt.as_dict())

    def _backoff(self, retry_number: int) -> None:
        delay = min(self.backoff_max, self.backoff_base * (2 ** max(0, retry_number - 1)))
        if self.jitter:
            delay = min(self.backoff_max, delay + self.jitter * self.random_fn())
        if delay > 0:
            self.sleep(delay)

    def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        temperature: float,
        request_extra: Mapping[str, Any] | None = None,
    ) -> Completion:
        """Make a completion request, retrying only explicitly transient errors."""

        if not model or not model.strip():
            raise ValueError("model must not be empty")
        extra = _validate_request_extra(request_extra)
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": int(max_tokens),
            "temperature": float(temperature),
        }
        payload.update(extra)
        # Protected keys are checked above, and are assigned before extras.  The
        # explicit assignment also protects callers that pass a strange Mapping.
        payload["model"] = model
        payload["messages"] = messages

        self.last_attempts = []
        self.last_retry_count = 0
        url = chat_completions_url(self.api_base)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = self.headers()

        for attempt_number in range(1, self.max_retries + 2):
            started = time.monotonic()
            try:
                req = request.Request(url, data=body, headers=headers, method="POST")
                with self.opener(req, timeout=self.timeout) as response:
                    response_body = response.read().decode("utf-8", errors="replace")
                    response_headers = _safe_headers(
                        dict(response.headers.items()), self.api_key
                    )
                data = json.loads(response_body)
                if not isinstance(data, dict):
                    failure = ProviderAttempt(
                        attempted_at=utc_now(),
                        status_code=None,
                        error_type="invalid_response",
                        body=_redact_text(response_body, self.api_key),
                        request_id=None,
                        retryable=False,
                        attempt=attempt_number,
                    )
                    self._record_failure(failure)
                    raise ProviderError(
                        "Provider returned a non-object JSON response",
                        body=failure.body,
                        attempts=attempt_number,
                    )
                choices = data.get("choices")
                if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                    request_id = _request_id(response_headers, data)
                    failure = ProviderAttempt(
                        attempted_at=utc_now(),
                        status_code=None,
                        error_type="invalid_response",
                        body=_redact_text(response_body, self.api_key),
                        request_id=request_id,
                        retryable=False,
                        attempt=attempt_number,
                    )
                    self._record_failure(failure)
                    raise ProviderError(
                        "Provider response did not contain choices[0]",
                        body=failure.body,
                        request_id=request_id,
                        response_headers=response_headers,
                        attempts=attempt_number,
                    )
                choice = choices[0]
                message = choice.get("message", {})
                finish_reason = choice.get("finish_reason")
                usage = data.get("usage")
                return Completion(
                    content=_content_from_message(message),
                    requested_model=model,
                    resolved_model=str(data["model"]) if data.get("model") is not None else None,
                    finish_reason=str(finish_reason) if finish_reason is not None else None,
                    usage=dict(usage) if isinstance(usage, dict) else {},
                    raw_response=dict(data),
                    latency_ms=max(0, int(round((time.monotonic() - started) * 1000))),
                    request_id=_request_id(response_headers, data),
                    response_headers=response_headers,
                    provider=self.provider,
                    upstream_provider=(
                        str(data["provider"]) if data.get("provider") is not None else None
                    ),
                )
            except error.HTTPError as exc:
                try:
                    response_body = exc.read().decode("utf-8", errors="replace")
                except (AttributeError, OSError):
                    response_body = ""
                status = int(exc.code)
                safe_headers = (
                    _safe_headers(dict(exc.headers.items()), self.api_key)
                    if exc.headers
                    else {}
                )
                request_id = _request_id(safe_headers, {})
                retryable = status == 429 or 500 <= status <= 599
                failure = ProviderAttempt(
                    attempted_at=utc_now(),
                    status_code=status,
                    error_type="http_error",
                    body=_redact_text(response_body, self.api_key),
                    request_id=request_id,
                    retryable=retryable,
                    attempt=attempt_number,
                )
                self._record_failure(failure)
                if retryable and attempt_number <= self.max_retries:
                    self.last_retry_count += 1
                    self._backoff(attempt_number)
                    continue
                raise ProviderError(
                    f"Provider HTTP {status}",
                    status_code=status,
                    body=failure.body,
                    request_id=request_id,
                    response_headers=safe_headers,
                    retryable=retryable,
                    attempts=attempt_number,
                ) from exc
            except TimeoutError as exc:
                failure = ProviderAttempt(
                    attempted_at=utc_now(),
                    status_code=None,
                    error_type="timeout",
                    body=_redact_text(str(exc), self.api_key),
                    request_id=None,
                    retryable=True,
                    attempt=attempt_number,
                )
                self._record_failure(failure)
                if attempt_number <= self.max_retries:
                    self.last_retry_count += 1
                    self._backoff(attempt_number)
                    continue
                raise ProviderError(
                    "Provider request timed out",
                    body=failure.body,
                    retryable=True,
                    attempts=attempt_number,
                ) from exc
            except error.URLError as exc:
                reason = exc.reason
                is_timeout = isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in str(reason).lower()
                failure = ProviderAttempt(
                    attempted_at=utc_now(),
                    status_code=None,
                    error_type="timeout" if is_timeout else "url_error",
                    body=_redact_text(str(reason), self.api_key),
                    request_id=None,
                    retryable=is_timeout,
                    attempt=attempt_number,
                )
                self._record_failure(failure)
                if is_timeout and attempt_number <= self.max_retries:
                    self.last_retry_count += 1
                    self._backoff(attempt_number)
                    continue
                raise ProviderError(
                    "Provider connection failed" if not is_timeout else "Provider request timed out",
                    body=failure.body,
                    retryable=is_timeout,
                    attempts=attempt_number,
                ) from exc
            except json.JSONDecodeError as exc:
                # Malformed provider output is a client/provider error, not a
                # transient network failure and must not be retried.
                failure = ProviderAttempt(
                    attempted_at=utc_now(),
                    status_code=None,
                    error_type="invalid_json",
                    body=_redact_text(response_body, self.api_key),
                    request_id=None,
                    retryable=False,
                    attempt=attempt_number,
                )
                self._record_failure(failure)
                raise ProviderError("Provider returned invalid JSON", body=failure.body) from exc
            except ProviderError:
                raise
            except Exception as exc:
                # Do not retry arbitrary exceptions: only timeouts and the
                # explicitly listed HTTP statuses are transient.
                failure = ProviderAttempt(
                    attempted_at=utc_now(),
                    status_code=None,
                    error_type=type(exc).__name__,
                    body=_redact_text(str(exc), self.api_key),
                    request_id=None,
                    retryable=False,
                    attempt=attempt_number,
                )
                self._record_failure(failure)
                raise ProviderError("Provider request failed", body=failure.body) from exc

        raise AssertionError("unreachable")


def provider_metadata(completion: Completion) -> dict[str, Any]:
    """Extract optional upstream metadata without inventing absent values."""

    raw = completion.raw_response
    metadata: dict[str, Any] = {}
    if completion.provider:
        metadata["provider"] = completion.provider
    if completion.upstream_provider is not None:
        metadata["upstream_provider"] = completion.upstream_provider
    for key in (
        "system_fingerprint",
        "service_tier",
        "created",
        "cost",
        "total_cost",
    ):
        if key in raw:
            metadata[key] = raw[key]
    if completion.request_id is not None:
        metadata["request_id"] = completion.request_id
    return metadata


__all__ = [
    "Completion",
    "PROVIDERS",
    "ProviderAttempt",
    "ProviderClient",
    "ProviderError",
    "chat_completions_url",
    "open_no_redirect",
    "provider_metadata",
    "require_https",
    "resolve_api_base",
    "resolve_credentials",
]
