"""
Google Gemini provider — single-call structured output.

Uses google-genai SDK (new unified SDK, replaces google.generativeai).

Free tier (Google AI Studio):
  - gemini-2.0-flash-exp: 10 RPM, 1500 RPD, 1M TPM
  - gemini-1.5-flash:     15 RPM, 1500 RPD, 1M TPM
  - gemini-1.5-pro:        2 RPM,   50 RPD, 32k TPM

Built-in rate limiter: minimum 4s between calls (15 RPM safe).
The user can override via `min_interval_seconds=`.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

from strategy.llm_providers.base import LLMProvider, ProviderError, RateLimitError

logger = logging.getLogger(__name__)


DEFAULT_GEMINI_MODEL = "gemini-2.5-flash-lite"  # fast (~6s/call), separate quota, stable
# Model lessons learned (2026-04-08):
# - 'gemini-flash-latest' aliases to gemini-3-flash (preview) — only 20 reqs/day
# - 'gemini-2.5-flash' frequently 503 (high demand)
# - 'gemini-2.5-flash-lite' fast + reliable + free tier covers our usage

# Rate limit conservativo (15 RPM = 4s entre calls)
DEFAULT_MIN_INTERVAL = 4.0

# Retry config for transient errors (503 high-demand, 429 rate-limit)
MAX_RETRIES = 5
RETRY_BASE_DELAY = 8.0  # seconds; doubles each attempt


class GeminiProvider(LLMProvider):
    """Google Gemini provider via google-genai SDK.

    Requires `GEMINI_API_KEY` in env (from https://aistudio.google.com/apikey).
    Free tier covers our hackathon usage.

    Rate limiting: enforces a minimum interval between calls to avoid hitting
    Google's 15 RPM cap on the free tier.
    """

    name = "gemini"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_GEMINI_MODEL,
        temperature: float = 0.1,
        min_interval_seconds: float = DEFAULT_MIN_INTERVAL,
    ):
        super().__init__(model=model, temperature=temperature)
        self._api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self.min_interval = min_interval_seconds
        self._last_call_ts = 0.0
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise ProviderError(
                "GEMINI_API_KEY not set. Get one at https://aistudio.google.com/apikey"
            )
        try:
            from google import genai  # type: ignore
        except ImportError as e:
            raise ProviderError(f"google-genai package not installed: {e}")
        self._client = genai.Client(api_key=self._api_key)
        return self._client

    def _rate_limit_wait(self):
        """Sleep enough to respect min_interval since last call."""
        now = time.monotonic()
        elapsed = now - self._last_call_ts
        if elapsed < self.min_interval:
            sleep_for = self.min_interval - elapsed
            logger.debug(f"Gemini rate limit: sleeping {sleep_for:.2f}s")
            time.sleep(sleep_for)
        self._last_call_ts = time.monotonic()

    def _gemini_to_json_schema(self, schema: dict) -> dict:
        """Adapt OpenAI-style schema to Gemini's responseSchema format.

        Gemini expects:
          - `type` capitalized as "OBJECT" / "STRING" / "INTEGER" / etc
          - No `additionalProperties`
          - `properties` with same nesting
        """
        type_map = {
            "object": "OBJECT",
            "string": "STRING",
            "integer": "INTEGER",
            "number": "NUMBER",
            "boolean": "BOOLEAN",
            "array": "ARRAY",
        }

        def adapt(node):
            if not isinstance(node, dict):
                return node
            out = {}
            for k, v in node.items():
                if k == "additionalProperties":
                    continue  # Gemini doesn't support
                if k == "type" and isinstance(v, str):
                    out[k] = type_map.get(v.lower(), v.upper())
                elif k == "properties" and isinstance(v, dict):
                    out[k] = {pk: adapt(pv) for pk, pv in v.items()}
                elif k == "items":
                    out[k] = adapt(v)
                elif k == "enum":
                    out[k] = v
                elif k == "required":
                    out[k] = v
                elif k == "description":
                    out[k] = v
                elif k in ("minimum", "maximum"):
                    out[k] = v
                else:
                    out[k] = adapt(v) if isinstance(v, dict) else v
            return out

        return adapt(schema)

    def call(
        self,
        system_prompt: str,
        user_message: str,
        response_schema: dict,
    ) -> dict:
        """Call Gemini with retry on transient errors (503/429).

        Retries up to MAX_RETRIES times with exponential backoff.
        Raises ProviderError if all retries fail.
        """
        self._rate_limit_wait()
        client = self._get_client()
        gemini_schema = self._gemini_to_json_schema(response_schema)

        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                from google.genai import types  # type: ignore

                response = client.models.generate_content(
                    model=self.model,
                    contents=[
                        {"role": "user", "parts": [{"text": user_message}]},
                    ],
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        temperature=self.temperature,
                        response_mime_type="application/json",
                        response_schema=gemini_schema,
                    ),
                )
                # Success — break retry loop
                break
            except Exception as e:
                last_exc = e
                msg = str(e).lower()
                is_transient = any(s in msg for s in ("503", "unavailable", "high demand", "overloaded"))
                is_rate_limit = any(s in msg for s in ("429", "rate", "quota", "exhausted"))

                if is_transient and attempt < MAX_RETRIES - 1:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(f"Gemini transient error (attempt {attempt + 1}/{MAX_RETRIES}): {msg[:100]}. Retrying in {delay:.0f}s...")
                    time.sleep(delay)
                    continue
                if is_rate_limit:
                    # Don't retry rate-limit errors here — caller should back off
                    raise RateLimitError(str(e)) from e
                # Non-transient or out of retries
                raise ProviderError(f"Gemini call failed (attempt {attempt + 1}): {e}") from e
        else:
            # Loop exhausted without break
            raise ProviderError(f"Gemini exhausted {MAX_RETRIES} retries. Last error: {last_exc}")

        # Extract JSON text
        try:
            raw = response.text
        except AttributeError:
            try:
                raw = response.candidates[0].content.parts[0].text
            except (IndexError, AttributeError) as e:
                raise ProviderError(f"Gemini returned no content: {e}") from e

        if not raw:
            raise ProviderError("Gemini returned empty content")

        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise ProviderError(f"Gemini returned invalid JSON: {e}") from e
