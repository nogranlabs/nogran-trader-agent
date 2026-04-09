"""OpenAI GPT-4o provider — single-call structured output via JSON Schema strict."""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

from strategy.llm_providers.base import LLMProvider, ProviderError, RateLimitError

logger = logging.getLogger(__name__)


DEFAULT_OPENAI_MODEL = "gpt-4o-2024-08-06"


class OpenAIProvider(LLMProvider):
    """OpenAI Chat Completions with structured output (JSON Schema strict).

    Requires `OPENAI_API_KEY` in env (or passed via api_key=).
    """

    name = "openai"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_OPENAI_MODEL,
        temperature: float = 0.1,
    ):
        super().__init__(model=model, temperature=temperature)
        self._api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self._client = None  # lazy init

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise ProviderError(
                "OPENAI_API_KEY not set. Pass api_key= or set in .env."
            )
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as e:
            raise ProviderError(f"openai package not installed: {e}")
        self._client = OpenAI(api_key=self._api_key)
        return self._client

    def call(
        self,
        system_prompt: str,
        user_message: str,
        response_schema: dict,
    ) -> dict:
        client = self._get_client()
        try:
            completion = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "trading_decision",
                        "strict": True,
                        "schema": response_schema,
                    },
                },
                temperature=self.temperature,
            )
        except Exception as e:
            # Detect rate limit specifically
            msg = str(e).lower()
            if "rate" in msg and "limit" in msg:
                raise RateLimitError(str(e)) from e
            raise ProviderError(str(e)) from e

        try:
            raw = completion.choices[0].message.content
        except (IndexError, AttributeError) as e:
            raise ProviderError(f"OpenAI returned no content: {e}") from e

        if not raw:
            raise ProviderError("OpenAI returned empty content")

        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise ProviderError(f"OpenAI returned invalid JSON: {e}") from e
