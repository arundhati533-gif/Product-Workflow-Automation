"""Claude API client: structured output, prompt caching and cost tracking."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol, TypeVar

import anthropic
from pydantic import BaseModel

from core import config

T = TypeVar("T", bound=BaseModel)

MAX_TOKENS = 32_000
TIMEOUT_SECONDS = 600
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(RuntimeError):
    """A model call failed in a way the user should see (refusal, truncation, API error)."""


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_write_tokens + other.cache_write_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
        )


@dataclass
class LLMResult:
    output: BaseModel
    model: str
    usage: Usage
    cost_usd: float


def compute_cost(model: str, usage: Usage) -> float:
    price = config.MODELS.get(model)
    if price is None:  # demo mode
        return 0.0
    per_input = price["input"] / 1_000_000
    per_output = price["output"] / 1_000_000
    return round(
        usage.input_tokens * per_input
        + usage.cache_write_tokens * per_input * config.CACHE_WRITE_MULTIPLIER
        + usage.cache_read_tokens * per_input * config.CACHE_READ_MULTIPLIER
        + usage.output_tokens * per_output,
        4,
    )


def estimate_tokens(text: str) -> int:
    """Rough token count for English text (about 1.4 tokens per word)."""
    return int(len(text.split()) * 1.4)


def estimate_meeting_cost(model: str, transcript_text: str) -> float:
    """Rough cost of running all five stages (plus the DoR review) on one transcript.

    Assumes the transcript is written to the cache once and read five times,
    each stage adds ~4k tokens of earlier outputs, and writes ~6k output tokens
    (including thinking).
    """
    context = estimate_tokens(transcript_text) + 1_500
    calls = len(config.STAGES) + 1
    usage = Usage(
        input_tokens=calls * 4_000,
        output_tokens=calls * 6_000,
        cache_write_tokens=context,
        cache_read_tokens=context * (calls - 1),
    )
    return compute_cost(model, usage)


class StructuredLLM(Protocol):
    """What the pipeline needs from an LLM. Tests use a fake implementation."""

    model: str

    def generate(self, system: str, context: str, prompt: str, schema: type[T]) -> LLMResult: ...


class ClaudeLLM:
    def __init__(self, model: str = config.DEFAULT_MODEL, api_key: str | None = None,
                 client: anthropic.Anthropic | None = None):
        if model not in config.MODELS:
            raise ValueError(f"Unknown model: {model}")
        self.model = model
        self.client = client or anthropic.Anthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"),
            timeout=TIMEOUT_SECONDS,
            max_retries=3,
        )

    def generate(self, system: str, context: str, prompt: str, schema: type[T]) -> LLMResult:
        """One structured call.

        `system` and `context` (project, roster and transcript) are identical for
        every stage of a meeting, so they form a cached prefix; only `prompt`
        changes between stages.
        """
        kwargs = {}
        if config.MODELS[self.model].get("fallbacks"):
            kwargs = {"betas": [FALLBACK_BETA], "fallbacks": "default"}
        try:
            response = self.client.beta.messages.parse(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=[
                    {"type": "text", "text": system},
                    {"type": "text", "text": context, "cache_control": {"type": "ephemeral"}},
                ],
                messages=[{"role": "user", "content": prompt}],
                output_format=schema,
                # Explicit timeout: the SDK otherwise refuses non-streaming calls with a large max_tokens.
                timeout=TIMEOUT_SECONDS,
                **kwargs,
            )
        except anthropic.AuthenticationError as exc:
            raise LLMError("The Anthropic API key is missing or invalid. Check it in Settings.") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("Rate limited by the Claude API. Wait a minute and try again.") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("Could not reach the Claude API. Check your internet connection.") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Claude API error ({exc.status_code}): {exc.message}") from exc

        if response.stop_reason == "refusal":
            raise LLMError("The model declined this request. Try rephrasing your feedback.")
        if response.stop_reason == "max_tokens":
            raise LLMError("The response was too long and got cut off. Try regenerating with narrower feedback.")
        if response.parsed_output is None:
            raise LLMError("The model returned output that did not match the expected format. Try again.")

        u = response.usage
        usage = Usage(
            input_tokens=u.input_tokens or 0,
            output_tokens=u.output_tokens or 0,
            cache_write_tokens=u.cache_creation_input_tokens or 0,
            cache_read_tokens=u.cache_read_input_tokens or 0,
        )
        return LLMResult(response.parsed_output, self.model, usage, compute_cost(self.model, usage))

    def check_key(self) -> None:
        """Cheap call used by Settings to validate the API key."""
        try:
            self.client.models.retrieve(self.model)
        except anthropic.AuthenticationError as exc:
            raise LLMError("The Anthropic API key is invalid.") from exc
        except anthropic.APIError as exc:
            raise LLMError(f"Could not validate the key: {exc}") from exc
