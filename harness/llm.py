"""
Thin wrapper over the Anthropic SDK.

Exposes a single .complete() interface so the rest of the harness is
provider-agnostic (provider selected via BALCON_LLM_PROVIDER env var).
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-6"


class LLMClient:
    """Wraps the configured LLM provider and returns (response_text, tokens_used)."""

    def __init__(self) -> None:
        provider = os.environ.get("BALCON_LLM_PROVIDER", "anthropic").lower()
        self.model = os.environ.get("BALCON_MODEL", DEFAULT_MODEL)

        if provider == "anthropic":
            import anthropic  # noqa: PLC0415

            self._client = anthropic.Anthropic()
            self._complete = self._complete_anthropic
        elif provider == "bedrock":
            import anthropic  # noqa: PLC0415

            self._client = anthropic.AnthropicBedrock(
                aws_region=os.environ.get("AWS_REGION", "us-east-1"),
            )
            self._complete = self._complete_anthropic  # same Messages API
        else:
            raise ValueError(f"Unsupported BALCON_LLM_PROVIDER: {provider!r}")

    def complete(
        self,
        messages: list[dict],
        *,
        system: str = "",
        model: str | None = None,
    ) -> tuple[str, int]:
        """Call the LLM and return (response_text, total_tokens_used)."""
        return self._complete(messages, system=system, model=model or self.model)

    # ------------------------------------------------------------------
    # Provider implementations
    # ------------------------------------------------------------------

    def _complete_anthropic(
        self,
        messages: list[dict],
        *,
        system: str,
        model: str,
    ) -> tuple[str, int]:
        kwargs: dict = dict(
            model=model,
            max_tokens=8192,
            messages=messages,
        )
        if system:
            kwargs["system"] = system

        response = self._client.messages.create(**kwargs)
        text = response.content[0].text
        tokens = response.usage.input_tokens + response.usage.output_tokens
        logger.debug("LLM call: model=%s tokens=%d", model, tokens)
        return text, tokens
