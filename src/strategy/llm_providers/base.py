"""
LLMProvider — abstract base for pluggable LLM backends.

Each provider implements `call()` to send a prompt and return parsed JSON
matching the response schema. The orchestrator (LLMStrategy) handles caching,
parsing into TradeSignal, and error recovery.

Providers MUST:
- Be deterministic given fixed (system_prompt, user_message, model, temperature)
- Raise `ProviderError` on transient failures (will be logged + skipped)
- Raise `RateLimitError` on rate-limit hits (caller may retry with backoff)
- Return a dict that satisfies the response_schema (strict)

Providers MUST NOT:
- Cache internally (LLMStrategy owns the cache)
- Mutate the prompts/schema
- Block more than ~30s per call
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class ProviderError(Exception):
    """Generic provider failure (network, parse, etc)."""


class RateLimitError(ProviderError):
    """Provider hit rate limit. Caller may sleep + retry."""


class LLMProvider(ABC):
    """Abstract LLM backend.

    Subclasses must implement `call()` and `cache_signature()`.
    """

    name: str = "abstract"

    def __init__(self, model: str, temperature: float = 0.1):
        self.model = model
        self.temperature = temperature

    @abstractmethod
    def call(
        self,
        system_prompt: str,
        user_message: str,
        response_schema: dict,
    ) -> dict:
        """Send the prompt to the LLM and return parsed JSON dict.

        Must satisfy response_schema (strict). Raise ProviderError on failure,
        RateLimitError if rate-limited.
        """
        ...

    def cache_signature(self) -> str:
        """Unique identifier for cache keying. Includes provider name + model.

        Default: "{name}:{model}". Override if you need provider-specific
        version bumps without renaming the model.
        """
        return f"{self.name}:{self.model}"

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} model={self.model!r} temp={self.temperature}>"
