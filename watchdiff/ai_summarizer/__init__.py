"""
AI Summarizer - generates natural language summaries of diffs.

Supported providers: anthropic, openai (+ compatible endpoints), gemini, custom.
Auto-detected from ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY env vars.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

_DEFAULTS: dict[str, str] = {
    "anthropic": "claude-haiku-4-5-20251001",
    "openai":    "gpt-4o-mini",
    "gemini":    "gemini-3.1-flash-lite",
}


class AiErrorKind(str, Enum):
    INVALID_KEY    = "invalid_key"
    QUOTA_EXCEEDED = "quota_exceeded"
    MODEL_ERROR    = "model_error"
    NETWORK_ERROR  = "network_error"


class AiError(Exception):
    def __init__(self, message: str, kind: AiErrorKind, status_code: int | None = None) -> None:
        super().__init__(message)
        self.kind        = kind
        self.status_code = status_code

    @property
    def is_retryable(self) -> bool:
        return self.kind in (AiErrorKind.QUOTA_EXCEEDED, AiErrorKind.NETWORK_ERROR)

    @property
    def is_permanent(self) -> bool:
        return self.kind in (AiErrorKind.INVALID_KEY, AiErrorKind.MODEL_ERROR)


@dataclass
class AiProvider:
    type:     str                                          # "anthropic" | "openai" | "gemini" | "custom"
    api_key:  str | None                                   = None
    model:    str | None                                   = None
    base_url: str | None                                   = None  # for OpenAI-compatible endpoints
    call_ai:  Callable[[str], str | None] | None           = None  # custom escape hatch


def resolve_provider() -> AiProvider | None:
    if key := os.environ.get("ANTHROPIC_API_KEY"):
        return AiProvider(type="anthropic", api_key=key)
    if key := os.environ.get("OPENAI_API_KEY"):
        return AiProvider(type="openai", api_key=key)
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_AI_API_KEY")
    if key:
        return AiProvider(type="gemini", api_key=key)
    return None


def get_provider(config: Any) -> AiProvider | None:
    if getattr(config, "ai_provider", None):
        return config.ai_provider
    if getattr(config, "ai_summary", False):
        return resolve_provider()
    return None


def ai_summary_enabled(config: Any) -> bool:
    return bool(getattr(config, "ai_summary", False))


def call_provider(prompt: str, provider: AiProvider | None = None) -> str | None:
    if provider is None:
        provider = resolve_provider()
    if provider is None:
        return None

    if provider.type == "custom":
        if provider.call_ai:
            try:
                return provider.call_ai(prompt)
            except Exception as e:
                raise AiError(str(e), AiErrorKind.NETWORK_ERROR) from e
        return None

    if provider.type == "anthropic":
        return _call_anthropic(prompt, provider)
    if provider.type == "openai":
        return _call_openai(prompt, provider)
    if provider.type == "gemini":
        return _call_gemini(prompt, provider)
    return None


def generate_ai_summary(
    report: Any,
    provider: AiProvider | None = None,
    prompt_override: str | Callable[[Any], str] | None = None,
) -> str | None:
    if not getattr(report, "has_changes", False):
        return None
    if provider is None:
        return None
    if prompt_override is not None:
        prompt = prompt_override(report) if callable(prompt_override) else prompt_override
    else:
        prompt = _build_url_prompt(report)
    return call_provider(prompt, provider)


def _build_url_prompt(report: Any) -> str:
    changes = list(report.changes)[:20]
    lines   = [c.human() if hasattr(c, "human") else str(c) for c in changes]
    return (
        "You are monitoring a web page for changes. Summarize the following diff in 1-2 sentences "
        "in plain language, focusing on what is important to a human reader.\n\n"
        f"URL: {report.url}\nChanges:\n" + "\n".join(lines) + "\n\nSummary:"
    )


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _http_post(url: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(body).encode()
    req  = urllib.request.Request(url, data=data, headers={**headers, "content-type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())  # type: ignore[return-value]
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            body_text = e.read().decode()
        except Exception:
            body_text = ""
        if status in (401, 403):
            raise AiError(f"Auth error {status}: {body_text}", AiErrorKind.INVALID_KEY, status) from e
        if status == 429:
            raise AiError(f"Quota exceeded: {body_text}", AiErrorKind.QUOTA_EXCEEDED, status) from e
        if status == 400:
            raise AiError(f"Bad request {status}: {body_text}", AiErrorKind.MODEL_ERROR, status) from e
        raise AiError(f"HTTP {status}: {body_text}", AiErrorKind.MODEL_ERROR, status) from e
    except AiError:
        raise
    except Exception as e:
        raise AiError(str(e), AiErrorKind.NETWORK_ERROR) from e


# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------

def _call_anthropic(prompt: str, provider: AiProvider) -> str | None:
    model = provider.model or _DEFAULTS["anthropic"]
    resp  = _http_post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key":         provider.api_key or "",
            "anthropic-version": "2023-06-01",
        },
        body={
            "model":      model,
            "max_tokens": 256,
            "messages":   [{"role": "user", "content": prompt}],
        },
    )
    content = resp.get("content") or []
    if content:
        return content[0].get("text") or None
    return None


def _call_openai(prompt: str, provider: AiProvider) -> str | None:
    base  = (provider.base_url or "https://api.openai.com").rstrip("/")
    model = provider.model or _DEFAULTS["openai"]
    resp  = _http_post(
        f"{base}/v1/chat/completions",
        headers={"Authorization": f"Bearer {provider.api_key or ''}"},
        body={
            "model":      model,
            "max_tokens": 256,
            "messages":   [{"role": "user", "content": prompt}],
        },
    )
    choices = resp.get("choices") or []
    if choices:
        return choices[0].get("message", {}).get("content") or None
    return None


def _call_gemini(prompt: str, provider: AiProvider) -> str | None:
    model   = provider.model or _DEFAULTS["gemini"]
    api_key = provider.api_key or ""
    resp    = _http_post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
        headers={},
        body={"contents": [{"parts": [{"text": prompt}]}]},
    )
    candidates = resp.get("candidates") or []
    if candidates:
        parts = candidates[0].get("content", {}).get("parts") or []
        if parts:
            return parts[0].get("text") or None
    return None


__all__ = [
    "AiError",
    "AiErrorKind",
    "AiProvider",
    "ai_summary_enabled",
    "call_provider",
    "generate_ai_summary",
    "get_provider",
    "resolve_provider",
]
