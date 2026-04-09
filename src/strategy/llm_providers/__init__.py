"""
LLM provider abstraction.

Providers expose a uniform interface so the LLMStrategy orchestrator can
swap models (OpenAI GPT-4o, Google Gemini, Anthropic Claude, etc.) without
changing pipeline code.

Use:
    from strategy.llm_providers import OpenAIProvider, GeminiProvider
    from strategy.llm_strategy import LLMStrategy

    strategy = LLMStrategy(provider=GeminiProvider())
    signal = strategy.ask(features)
"""

from strategy.llm_providers.base import LLMProvider, ProviderError, RateLimitError
from strategy.llm_providers.gemini_provider import GeminiProvider
from strategy.llm_providers.openai_provider import OpenAIProvider

__all__ = [
    "LLMProvider",
    "ProviderError",
    "RateLimitError",
    "OpenAIProvider",
    "GeminiProvider",
]
