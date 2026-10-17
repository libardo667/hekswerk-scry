"""A small OpenRouter client (OpenAI-compatible chat completions), standard library only.

It sends a conversation plus tool definitions and returns the model's reply. The reply's
message is kept exactly as returned, including any reasoning details, because the next
request must send it back unchanged: Claude models check that earlier turns weren't
edited.
"""

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from hekswerk_scry.core.settings import AISettings

# A transport takes (url, headers, body, timeout) and returns (status, body). Tests pass
# a scripted one; the default sends a real HTTPS request.
Transport = Callable[[str, dict[str, str], bytes, float], tuple[int, bytes]]

RETRY_STATUSES = frozenset({408, 429, 500, 502, 503, 504})


class AIProviderError(RuntimeError):
    """The AI provider could not be reached or returned something unusable."""


@dataclass(frozen=True)
class ChatReply:
    message: dict[str, Any]
    finish_reason: str
    model: str
    cost_usd: float | None
    usage: dict[str, Any] = field(default_factory=dict)

    @property
    def tool_calls(self) -> list[dict[str, Any]]:
        calls = self.message.get("tool_calls") or []
        return [call for call in calls if isinstance(call, dict)]

    @property
    def text(self) -> str:
        content = self.message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                part.get("text", "") for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        return ""


def https_transport(
    url: str, headers: dict[str, str], body: bytes, timeout: float
) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


class OpenRouterClient:
    def __init__(
        self,
        settings: AISettings,
        *,
        transport: Transport | None = None,
        timeout: float = 600,
        retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self.transport = transport or https_transport
        self.timeout = timeout
        self.retries = retries
        self.sleep = sleep

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ChatReply:
        body = json.dumps(
            {
                "model": self.settings.model,
                "messages": messages,
                "tools": tools,
                # Forced tool use is not available on current Claude models; the model
                # decides when to call a tool.
                "tool_choice": "auto",
                "reasoning": {"effort": self.settings.effort},
                "max_tokens": 16000,
                "usage": {"include": True},
            }
        ).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
            "X-Title": "hekswerk-scry",
        }
        url = f"{self.settings.base_url}/chat/completions"
        for attempt in range(self.retries + 1):
            try:
                status, raw = self.transport(url, headers, body, self.timeout)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt == self.retries:
                    raise AIProviderError(f"Couldn't reach OpenRouter: {exc}") from exc
                self.sleep(2.0 * 2**attempt)
                continue
            if status in RETRY_STATUSES and attempt < self.retries:
                self.sleep(2.0 * 2**attempt)
                continue
            return self._parse(status, raw)
        raise AIProviderError("OpenRouter kept failing; giving up.")  # pragma: no cover

    def _parse(self, status: int, raw: bytes) -> ChatReply:
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AIProviderError(
                f"OpenRouter returned something that isn't JSON (status {status})."
            ) from exc
        if status != 200 or "error" in data:
            error = data.get("error") if isinstance(data, dict) else None
            message = error.get("message") if isinstance(error, dict) else None
            raise AIProviderError(
                f"OpenRouter refused the request (status {status}): {message or data}"
            )
        try:
            choice = data["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderError("OpenRouter's reply had no message in it.") from exc
        usage = data.get("usage") or {}
        cost = usage.get("cost")
        return ChatReply(
            message=message,
            finish_reason=str(choice.get("finish_reason") or ""),
            model=str(data.get("model") or self.settings.model),
            cost_usd=float(cost) if isinstance(cost, int | float) else None,
            usage=usage,
        )
