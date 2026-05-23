"""Anthropic client scaffold with prompt-caching support.

The autonomous loop's prompt has a large, stable prefix (hard caps,
persona catalog, action template) followed by a small dynamic tail
(current GitHub state + the specific target). The Anthropic prompt-cache
header lets us mark the prefix as cacheable so repeated ticks within a
few minutes pay full price for the prefix once and the discounted rate
afterwards.

The split point is the ``<!-- CACHE -->`` sentinel emitted by
:mod:`simulation.tools.loop_speedup.split_cacheable_prefix`. This module
turns that split into the SDK's ``content`` blocks with ``cache_control``.

Usage::

    from simulation.tools.llm_client import LlmClient

    client = LlmClient(model="claude-opus-4-7", max_tokens=4096)
    response = client.complete(prompt=rendered_prompt, system="You are…")
    print(response.text)

If the ``anthropic`` SDK is not importable, :class:`LlmClient` falls back
to ``None`` so callers can degrade gracefully (used by the dry-run test
that exercises only the cache-split logic).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-4-7"
DEFAULT_MAX_TOKENS = 4096
CACHE_BETA_HEADER = "prompt-caching-2025-02-19"

try:
    import anthropic  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover — SDK is optional in this sandbox
    anthropic = None  # type: ignore[assignment]

from simulation.tools.loop_speedup import CACHE_SENTINEL, split_cacheable_prefix


@dataclass
class LlmResponse:
    text: str
    usage: dict[str, Any]
    cached: bool


class LlmClient:
    """Thin Anthropic wrapper that splits prompts at ``<!-- CACHE -->``."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        api_key: str | None = None,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._client = anthropic.Anthropic(api_key=self.api_key) if anthropic else None

    def _build_content(self, prompt: str) -> list[dict[str, Any]]:
        prefix, dynamic = split_cacheable_prefix(prompt)
        if not prefix:
            return [{"type": "text", "text": dynamic}]
        return [
            {
                "type": "text",
                "text": prefix,
                "cache_control": {"type": "ephemeral"},
            },
            {"type": "text", "text": dynamic or "(no dynamic content)"},
        ]

    def complete(self, *, prompt: str, system: str | None = None) -> LlmResponse:
        """Call the model; the prefix is sent with ``cache_control: ephemeral``."""
        if self._client is None:
            raise RuntimeError(
                "anthropic SDK not available — install `anthropic` to call complete()"
            )
        content = self._build_content(prompt)
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [{"role": "user", "content": content}],
            "extra_headers": {"anthropic-beta": CACHE_BETA_HEADER},
        }
        if system:
            kwargs["system"] = system
        response = self._client.messages.create(**kwargs)
        # The SDK exposes usage including ``cache_read_input_tokens`` /
        # ``cache_creation_input_tokens`` for prompt-cache hit detection.
        usage = getattr(response, "usage", None)
        cached = bool(getattr(usage, "cache_read_input_tokens", 0)) if usage else False
        text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
        return LlmResponse(
            text=text,
            usage=dict(getattr(usage, "__dict__", {}) or {}),
            cached=cached,
        )


__all__ = [
    "CACHE_BETA_HEADER",
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_MODEL",
    "LlmClient",
    "LlmResponse",
]
