"""Model providers for the assistant.

DeepSeek exposes an OpenAI-compatible chat completions endpoint, so the client
is a small dependency-free JSON POST. A fake provider keeps tests offline.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"
MAX_ERROR_BODY = 300
CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.S)


class ProviderError(RuntimeError):
    """Raised when the model endpoint fails or returns an unusable payload."""


class ModelProvider(Protocol):
    def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1200,
    ) -> str: ...


def strip_code_fence(text: str) -> str:
    """Remove a Markdown JSON fence if the model adds one despite instructions."""
    stripped = text.strip()
    match = CODE_FENCE_RE.match(stripped)
    return match.group(1) if match else stripped


def _default_opener(request: urllib.request.Request, timeout: int) -> bytes:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


class DeepSeekProvider:
    """OpenAI-compatible chat completions client."""

    name = "deepseek"

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = 90,
        thinking: bool = False,
        opener: Callable[[urllib.request.Request, int], bytes] | None = None,
    ) -> None:
        if not api_key:
            raise ProviderError("model api key is empty")
        self._api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.thinking = thinking
        self._opener = opener or _default_opener
        self.last_usage: dict[str, int] | None = None

    def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1200,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [dict(message) for message in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
            "response_format": {"type": "json_object"},
            "thinking": {"type": "enabled" if self.thinking else "disabled"},
        }
        data = self._post(payload)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("model response has no message content") from exc
        usage = data.get("usage") or {}
        self.last_usage = {
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
        }
        return str(content)

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json; charset=utf-8",
            },
            method="POST",
        )
        try:
            raw = self._opener(request, self.timeout)
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001 - error detail is best effort only
                detail = ""
            message = " ".join(detail.split())[:MAX_ERROR_BODY]
            raise ProviderError(f"HTTP {exc.code}: {message or exc.reason}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderError(f"network error: {type(exc).__name__}") from exc
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderError("model response is not valid JSON") from exc
        if not isinstance(data, dict):
            raise ProviderError("model response is not a JSON object")
        return data


class FakeProvider:
    """Scripted provider for tests; records every call."""

    name = "fake"

    def __init__(self, responses: Sequence[str] | str) -> None:
        if isinstance(responses, str):
            self._responses = [responses]
        else:
            self._responses = list(responses)
        self.calls: list[list[dict[str, str]]] = []
        self.last_usage = {"prompt_tokens": 0, "completion_tokens": 0}

    def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1200,
    ) -> str:
        self.calls.append([dict(message) for message in messages])
        if not self._responses:
            raise ProviderError("fake provider has no scripted response")
        return self._responses.pop(0)
