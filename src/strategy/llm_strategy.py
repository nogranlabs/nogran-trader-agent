"""
LLM strategy — orchestrator for single-call structured output via pluggable providers.

Aceita qualquer provider (OpenAI, Gemini, Claude, etc) que implemente
`LLMProvider`, com cache em disco compartilhado.

Pipeline interno:
    1. Build user message a partir das features
    2. Compute cache key (provider.cache_signature() entra no hash)
    3. Cache hit -> return parsed signal (custo zero, qualquer provider)
    4. Cache miss -> provider.call(prompt, schema)
    5. Parse JSON -> TradeSignal
    6. Save to cache
    7. Return signal

Cache reduz custo de tuning a zero apos primeira passada num dataset.
JSON Schema strict (OpenAI) ou responseSchema (Gemini) garantem output valido.

Erros do provider sao logados e retornam None (caller decide AGUARDAR).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from domain.enums import Action, AlwaysIn, DayType, SetupType, SignalBarQuality
from domain.models import FeatureSnapshot, TradeSignal
from strategy.llm_cache import LLMCache
from strategy.llm_prompts import (
    RESPONSE_SCHEMA,
    SYSTEM_PROMPT,
    build_user_prompt,
)
from strategy.llm_providers.base import LLMProvider, ProviderError
from strategy.pa_retriever import PARetriever

logger = logging.getLogger(__name__)

# Schema version signature — bump when RESPONSE_SCHEMA fields change.
# History: v1.1-en (English prompts), v1.2-fee (fee-aware trader's equation),
# v1.3-strict (hard RR constraints), v1.4-stop05 (stop >= 0.5% hard rule),
# v3.0-structural (swing-anchored stops + structure-first pipeline).
SCHEMA_SIGNATURE = "v3.0-structural"

# Hard guards: minimum stop/target distance and RR ratio. Mirror the prompt
# rules but enforced in code so the LLM cannot bypass them.
# v1.4: stop >= 0.5% (kills noise stops where fees dominate gross loss)
# v1.5: target >= 1.0% AND RR >= 1.5 (later relaxed)
# v2.0: RR floor lowered from 1.5 → 1.0 to allow 1:1 RR for high-probability
#       setups (shaved bars in strong trends, second entries, etc) where
#       probability >= 60% compensates the low RR. Combined with target >= 1.0%
#       and stop >= 0.5%, the math floor stays positive after fees: target 1.0%
#       = 1R fee (~0.4%) leaves +0.6% expected per win.
MIN_STOP_DISTANCE_PCT = 0.005   # 0.5%
MIN_TARGET_DISTANCE_PCT = 0.010  # 1.0%
MIN_RR_RATIO = 1.0               # target_distance / stop_distance — 1:1 allowed

# Swing-based stop validation (Bloco 7 of P0 sprint).
# Rule: stops belong AT structure (last swing low for longs, last swing high
# for shorts). If the LLM picks a stop far from the structural level, we
# auto-adjust the stop to the swing AND keep the same RR.
SWING_STOP_TOLERANCE_PCT = 0.003  # 0.3% tolerance — stop must be within this distance of swing


def get_default_provider(provider_name: str = "openai") -> LLMProvider:
    """Factory: returns a provider instance by name. Lazy imports to avoid hard deps."""
    name = provider_name.lower()
    if name == "openai":
        from strategy.llm_providers.openai_provider import OpenAIProvider
        return OpenAIProvider()
    if name == "gemini":
        from strategy.llm_providers.gemini_provider import GeminiProvider
        return GeminiProvider()
    raise ValueError(f"Unknown provider: {provider_name}. Use 'openai' or 'gemini'.")


class LLMStrategy:
    """Provider-agnostic LLM signal generator with disk cache.

    Use:
        from strategy.llm_providers import GeminiProvider
        strategy = LLMStrategy(provider=GeminiProvider())
        signal = strategy.ask(features)  # TradeSignal | None

    Or use the factory:
        strategy = LLMStrategy.from_name("gemini")
    """

    def __init__(
        self,
        provider: Optional[LLMProvider] = None,
        cache: Optional[LLMCache] = None,
        cache_only: bool = False,
        retriever: Optional[PARetriever] = None,
        use_rag: bool = True,
    ):
        self.provider = provider if provider is not None else get_default_provider("openai")
        self.cache = cache if cache is not None else LLMCache()
        self.cache_only = cache_only  # se True, NUNCA chama provider (so cache hits)
        # PA RAG retriever (lazy-loaded). use_rag=False disables retrieval entirely.
        self.use_rag = use_rag
        self._retriever = retriever
        if self.use_rag and self._retriever is None:
            self._retriever = PARetriever()

    @classmethod
    def from_name(cls, provider_name: str, **kwargs) -> LLMStrategy:
        """Convenience factory: build LLMStrategy from a provider name string."""
        return cls(provider=get_default_provider(provider_name), **kwargs)

    # =========================================================
    # Public API
    # =========================================================

    def ask(self, features: FeatureSnapshot) -> Optional[TradeSignal]:
        """Pergunta ao LLM. Retorna TradeSignal ou None em caso de erro."""
        # RAG retrieval (rule-based, deterministic, ~5-10 chunks)
        pa_ref = ""
        retrieved_ids: list[str] = []
        if self.use_rag and self._retriever is not None and self._retriever.available:
            try:
                result = self._retriever.retrieve(features)
                pa_ref = result.to_prompt_text()
                retrieved_ids = result.chunk_ids()
            except Exception as e:
                logger.warning(f"PARetriever failed (continuing without RAG): {e}")

        user_msg = build_user_prompt(features, pa_reference=pa_ref)
        cache_key = self.cache.make_key(
            system_prompt=SYSTEM_PROMPT,
            user_message=user_msg,
            model=self.provider.cache_signature(),
            temperature=self.provider.temperature,
            schema_signature=SCHEMA_SIGNATURE,
        )

        # Cache lookup
        cached = self.cache.get(cache_key)
        if cached is not None:
            return self._parse_response(cached, features)

        if self.cache_only:
            logger.warning("LLM cache miss in cache_only mode → returning None")
            return None

        # Live call via provider
        try:
            response_dict = self.provider.call(SYSTEM_PROMPT, user_msg, RESPONSE_SCHEMA)
        except ProviderError as e:
            logger.error(f"Provider {self.provider.name} call failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error in provider {self.provider.name}: {e}")
            return None

        # Save to cache incrementally (write happens before parse → if parse fails, cache still has raw)
        try:
            self.cache.put(
                cache_key,
                response_dict,
                metadata={
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "candle_index": features.candle_index,
                    "provider": self.provider.name,
                    "model": self.provider.model,
                    "pa_chunks_used": retrieved_ids,
                },
            )
        except Exception as e:
            logger.warning(f"Failed to write to cache: {e}")

        return self._parse_response(response_dict, features)

    def _parse_response(self, data: dict, features: FeatureSnapshot) -> Optional[TradeSignal]:
        """Parse LLM JSON response into TradeSignal. Strip _meta if present."""
        try:
            # Strip cache metadata
            data = {k: v for k, v in data.items() if k != "_meta"}

            action_str = data.get("action", "AGUARDAR")
            try:
                action = Action(action_str)
            except ValueError:
                logger.warning(f"Invalid action from LLM: {action_str!r}, coercing to AGUARDAR")
                action = Action.AGUARDAR

            try:
                day_type = DayType(data.get("layer1_day_type", "indefinido"))
            except ValueError:
                day_type = DayType.INDEFINIDO

            try:
                always_in = AlwaysIn(data.get("layer2_always_in", "NEUTRO"))
            except ValueError:
                always_in = AlwaysIn.NEUTRO

            try:
                setup = SetupType(data.get("layer5_setup", "none"))
            except ValueError:
                setup = SetupType.NONE

            try:
                bar_quality = SignalBarQuality(
                    data.get("layer4_signal_bar_quality", "REPROVADO")
                )
            except ValueError:
                bar_quality = SignalBarQuality.REPROVADO

            confidence = int(data.get("confidence", 0))
            confidence = max(0, min(100, confidence))

            entry = float(data.get("entry_price", features.candle.close))
            stop = float(data.get("stop_loss", features.candle.close))
            target = float(data.get("take_profit", features.candle.close))

            # Swing-based stop validation (Bloco 7).
            # If we have a swing low (long) or swing high (short) AND the LLM
            # picked a stop far from it, snap the stop to the swing — preserves
            # the RR by also re-anchoring the target.
            if action == Action.COMPRA and features.last_swing_low is not None and entry > 0:
                ideal_stop = features.last_swing_low * (1 - 0.001)  # 0.1% safety below
                if ideal_stop < entry:
                    distance_to_ideal = abs(stop - ideal_stop) / entry
                    if distance_to_ideal > SWING_STOP_TOLERANCE_PCT:
                        original_rr = (target - entry) / max(entry - stop, 1e-9)
                        logger.info(
                            f"Snapping COMPRA stop to swing low: "
                            f"${stop:.2f} → ${ideal_stop:.2f} (RR preserved {original_rr:.2f})"
                        )
                        stop = ideal_stop
                        target = entry + (entry - stop) * original_rr
            elif action == Action.VENDA and features.last_swing_high is not None and entry > 0:
                ideal_stop = features.last_swing_high * (1 + 0.001)
                if ideal_stop > entry:
                    distance_to_ideal = abs(stop - ideal_stop) / entry
                    if distance_to_ideal > SWING_STOP_TOLERANCE_PCT:
                        original_rr = (entry - target) / max(stop - entry, 1e-9)
                        logger.info(
                            f"Snapping VENDA stop to swing high: "
                            f"${stop:.2f} → ${ideal_stop:.2f} (RR preserved {original_rr:.2f})"
                        )
                        stop = ideal_stop
                        target = entry - (stop - entry) * original_rr

            # Hard guards: enforce stop/target/RR rules in code regardless of
            # what the LLM returns. See MIN_*_PCT and MIN_RR_RATIO above.
            if action != Action.AGUARDAR and entry > 0:
                stop_distance = abs(entry - stop)
                target_distance = abs(target - entry)

                if stop_distance < entry * MIN_STOP_DISTANCE_PCT:
                    logger.warning(
                        f"Stop too tight ({stop_distance:.2f} = "
                        f"{stop_distance / entry * 100:.3f}% of entry, "
                        f"min required {MIN_STOP_DISTANCE_PCT * 100:.1f}%) — "
                        f"coercing {action.value} to AGUARDAR"
                    )
                    action = Action.AGUARDAR
                    stop = entry
                    target = entry
                elif target_distance < entry * MIN_TARGET_DISTANCE_PCT:
                    logger.warning(
                        f"Target too tight ({target_distance:.2f} = "
                        f"{target_distance / entry * 100:.3f}% of entry, "
                        f"min required {MIN_TARGET_DISTANCE_PCT * 100:.1f}%) — "
                        f"coercing {action.value} to AGUARDAR"
                    )
                    action = Action.AGUARDAR
                    stop = entry
                    target = entry
                else:
                    rr = target_distance / stop_distance
                    if rr < MIN_RR_RATIO:
                        logger.warning(
                            f"RR too low ({rr:.2f}, min required {MIN_RR_RATIO}) — "
                            f"coercing {action.value} to AGUARDAR"
                        )
                        action = Action.AGUARDAR
                        stop = entry
                        target = entry

            reasoning = str(data.get("reasoning", ""))[:500]
            decisive_layer = int(data.get("decisive_layer", 1))
            decisive_layer = max(1, min(5, decisive_layer))

            return TradeSignal(
                action=action,
                confidence=confidence,
                day_type=day_type,
                always_in=always_in,
                setup=setup,
                signal_bar_quality=bar_quality,
                entry_price=entry,
                stop_loss=stop,
                take_profit=target,
                decisive_layer=decisive_layer,
                reasoning=reasoning,
                timestamp=datetime.now(timezone.utc),
            )
        except Exception as e:
            logger.error(f"Failed to parse LLM response: {e}; data={data}")
            return None
