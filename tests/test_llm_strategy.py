"""Tests for src/strategy/llm_strategy.py + llm_cache.py + llm_prompts.py.

NAO chama OpenAI real. Usa cache pre-populado + mocks pra validar:
- Cache key e estavel
- Cache hit retorna sem chamar API
- Parser converte JSON valido em TradeSignal correto
- Parser e robusto a campos invalidos (graceful degradation)
- Schema inclui todos os 14 campos requeridos
"""

import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from domain.enums import Action, AlwaysIn, DayType, SetupType, SignalBarQuality  # noqa: E402
from domain.models import Candle, FeatureSnapshot  # noqa: E402
from strategy.llm_cache import LLMCache  # noqa: E402
from strategy.llm_prompts import (  # noqa: E402
    DEFAULT_MODEL,
    DEFAULT_TEMPERATURE,
    RESPONSE_SCHEMA,
    SYSTEM_PROMPT,
    build_user_prompt,
)
from strategy.llm_providers.base import LLMProvider, ProviderError  # noqa: E402
from strategy.llm_strategy import (  # noqa: E402
    MIN_RR_RATIO,
    MIN_STOP_DISTANCE_PCT,
    MIN_TARGET_DISTANCE_PCT,
    SCHEMA_SIGNATURE,
    LLMStrategy,
)

# ============================================================
# MockProvider for tests (no API calls)
# ============================================================


class MockProvider(LLMProvider):
    """Test provider: returns canned response or raises if configured."""

    name = "mock"

    def __init__(self, response: dict | None = None, raises: Exception | None = None,
                 model: str = "mock-test-1", temperature: float = 0.1):
        super().__init__(model=model, temperature=temperature)
        self.response = response
        self.raises = raises
        self.call_count = 0

    def call(self, system_prompt, user_message, response_schema):
        self.call_count += 1
        if self.raises is not None:
            raise self.raises
        if self.response is None:
            raise ProviderError("MockProvider has no response set")
        return self.response


# ============================================================
# Helpers
# ============================================================


def make_features(close=67000.0, **overrides) -> FeatureSnapshot:
    candle = Candle(
        timestamp=overrides.pop("timestamp", 1775653260000),
        open=overrides.pop("open", close - 50),
        high=overrides.pop("high", close + 100),
        low=overrides.pop("low", close - 100),
        close=close,
        volume=overrides.pop("volume", 5.0),
    )
    return FeatureSnapshot(
        candle=candle,
        candle_index=overrides.pop("candle_index", 100),
        ema_20=overrides.pop("ema_20", close - 30),
        atr_14=overrides.pop("atr_14", 50.0),
        atr_sma_20=overrides.pop("atr_sma_20", 45.0),
        adx_14=overrides.pop("adx_14", 28.0),
        price_vs_ema=overrides.pop("price_vs_ema", 0.45),
        atr_ratio=overrides.pop("atr_ratio", 1.1),
        body_pct=overrides.pop("body_pct", 60.0),
        upper_tail_pct=overrides.pop("upper_tail_pct", 15.0),
        lower_tail_pct=overrides.pop("lower_tail_pct", 25.0),
        consecutive_bull=overrides.pop("consecutive_bull", 3),
        consecutive_bear=overrides.pop("consecutive_bear", 0),
        bar_overlap_ratio=overrides.pop("bar_overlap_ratio", 0.35),
        direction_change_ratio=overrides.pop("direction_change_ratio", 0.2),
        volume_ratio=overrides.pop("volume_ratio", 1.2),
        is_peak_session=overrides.pop("is_peak_session", True),
        atr_expanding=overrides.pop("atr_expanding", True),
        atr_contracting=overrides.pop("atr_contracting", False),
    )


def valid_llm_response(action="COMPRA") -> dict:
    # Stop distance is 0.6% of entry (>= MIN_STOP_DISTANCE_PCT 0.5% guard).
    # Target distance is 1.2% (RR 2.0). Both consistent with v1.4 prompt rules.
    return {
        "layer1_day_type": "trend_from_open",
        "layer1_reasoning": "Bull trend forte com 3 bull bars consecutivas",
        "layer2_always_in": "SEMPRE_COMPRADO" if action == "COMPRA" else "SEMPRE_VENDIDO" if action == "VENDA" else "NEUTRO",
        "layer2_reasoning": "Bulls dominam, pullback ofereceu entrada",
        "layer3_structure": "Acima EMA20, +0.45%, sem resistencia proxima",
        "layer4_signal_bar_quality": "APROVADO",
        "layer5_setup": "second_entry_H2",
        "action": action,
        "confidence": 75,
        "entry_price": 67000.0,
        "stop_loss": 66598.0 if action == "COMPRA" else 67402.0,   # 0.6% away
        "take_profit": 67804.0 if action == "COMPRA" else 66196.0,  # 1.2% away (RR 2.0)
        "reasoning": "H2 pullback completo, MA holding, RR 2:1",
        "decisive_layer": 5,
    }


# ============================================================
# Schema integrity
# ============================================================


class TestResponseSchema:
    def test_has_all_required_fields(self):
        required = set(RESPONSE_SCHEMA["required"])
        expected = {
            "layer1_day_type", "layer1_reasoning",
            "layer2_always_in", "layer2_reasoning",
            "layer3_structure",
            "layer4_signal_bar_quality",
            "layer5_setup",
            "action", "confidence",
            "entry_price", "stop_loss", "take_profit",
            "reasoning", "decisive_layer",
        }
        assert required == expected

    def test_action_enum_values(self):
        assert RESPONSE_SCHEMA["properties"]["action"]["enum"] == ["COMPRA", "VENDA", "AGUARDAR"]

    def test_confidence_bounds(self):
        c = RESPONSE_SCHEMA["properties"]["confidence"]
        assert c["minimum"] == 0 and c["maximum"] == 100

    def test_decisive_layer_bounds(self):
        l = RESPONSE_SCHEMA["properties"]["decisive_layer"]
        assert l["minimum"] == 1 and l["maximum"] == 5

    def test_no_additional_properties(self):
        assert RESPONSE_SCHEMA["additionalProperties"] is False

    def test_all_setup_types_in_enum(self):
        # Schema enum must match domain.enums.SetupType
        schema_enum = set(RESPONSE_SCHEMA["properties"]["layer5_setup"]["enum"])
        domain_values = {s.value for s in SetupType}
        assert schema_enum == domain_values

    def test_all_day_types_in_enum(self):
        schema_enum = set(RESPONSE_SCHEMA["properties"]["layer1_day_type"]["enum"])
        domain_values = {d.value for d in DayType}
        assert schema_enum == domain_values

    def test_all_always_in_in_enum(self):
        schema_enum = set(RESPONSE_SCHEMA["properties"]["layer2_always_in"]["enum"])
        domain_values = {a.value for a in AlwaysIn}
        assert schema_enum == domain_values


# ============================================================
# build_user_prompt
# ============================================================


class TestBuildUserPrompt:
    def test_includes_close(self):
        f = make_features(close=68500.55)
        prompt = build_user_prompt(f)
        assert "68500.55" in prompt

    def test_includes_indicators(self):
        f = make_features()
        prompt = build_user_prompt(f)
        assert "EMA(20)" in prompt
        assert "ATR(14)" in prompt
        assert "ADX(14)" in prompt

    def test_includes_consecutive_bars(self):
        f = make_features(consecutive_bull=5, consecutive_bear=0)
        prompt = build_user_prompt(f)
        assert "Consecutive bull bars: 5" in prompt

    def test_no_5m_when_unavailable(self):
        f = make_features()
        f.tf_5m_direction = None
        prompt = build_user_prompt(f)
        assert "5m direction" not in prompt

    def test_with_5m_context(self):
        f = make_features()
        f.tf_5m_direction = "ALTA"
        f.tf_5m_ema_20 = 66950.0
        f.tf_5m_price_vs_ema = 0.3
        f.tf_5m_consecutive_bull = 2
        prompt = build_user_prompt(f)
        assert "ALTA" in prompt
        assert "66950" in prompt

    def test_session_marker(self):
        peak = make_features(is_peak_session=True)
        off = make_features(is_peak_session=False)
        assert "Peak session" in build_user_prompt(peak)
        assert "Peak session" in build_user_prompt(off)


# ============================================================
# LLMCache
# ============================================================


class TestLLMCache:
    def test_make_key_stable(self):
        k1 = LLMCache.make_key("sys", "user", "gpt-4o", 0.1, "v1")
        k2 = LLMCache.make_key("sys", "user", "gpt-4o", 0.1, "v1")
        assert k1 == k2
        assert len(k1) == 64  # sha256 hex

    def test_make_key_changes_with_prompt(self):
        k1 = LLMCache.make_key("sys", "user A", "gpt-4o", 0.1)
        k2 = LLMCache.make_key("sys", "user B", "gpt-4o", 0.1)
        assert k1 != k2

    def test_make_key_changes_with_temperature(self):
        k1 = LLMCache.make_key("sys", "user", "gpt-4o", 0.1)
        k2 = LLMCache.make_key("sys", "user", "gpt-4o", 0.5)
        assert k1 != k2

    def test_make_key_changes_with_schema_signature(self):
        k1 = LLMCache.make_key("sys", "user", "gpt-4o", 0.1, "v1")
        k2 = LLMCache.make_key("sys", "user", "gpt-4o", 0.1, "v2")
        assert k1 != k2

    def test_get_miss_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = LLMCache(cache_dir=Path(tmp))
            assert cache.get("nonexistent_key_aaaaa") is None

    def test_put_then_get_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = LLMCache(cache_dir=Path(tmp))
            payload = {"action": "COMPRA", "confidence": 75}
            cache.put("abcd1234" * 8, payload)
            got = cache.get("abcd1234" * 8)
            assert got is not None
            assert got["action"] == "COMPRA"
            assert got["confidence"] == 75

    def test_put_with_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = LLMCache(cache_dir=Path(tmp))
            cache.put("xyz" * 21 + "x", {"a": 1}, metadata={"ts": "2026-01-01"})
            got = cache.get("xyz" * 21 + "x")
            assert "_meta" in got
            assert got["_meta"]["ts"] == "2026-01-01"

    def test_stats_track_hits_and_misses(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = LLMCache(cache_dir=Path(tmp))
            cache.put("k1" * 32, {"v": 1})
            cache.get("k1" * 32)  # hit
            cache.get("nonexistent_aaaaa")  # miss
            cache.get("k1" * 32)  # hit
            stats = cache.stats
            assert stats["hits"] == 2
            assert stats["misses"] == 1
            assert stats["writes"] == 1
            assert stats["hit_rate"] == pytest.approx(2 / 3, rel=1e-3)

    def test_size_counts_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = LLMCache(cache_dir=Path(tmp))
            assert cache.size() == 0
            cache.put("a" * 64, {"v": 1})
            cache.put("b" * 64, {"v": 2})
            assert cache.size() == 2

    def test_clear_removes_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = LLMCache(cache_dir=Path(tmp))
            cache.put("a" * 64, {"v": 1})
            cache.put("b" * 64, {"v": 2})
            cache.clear()
            assert cache.size() == 0


# ============================================================
# LLMStrategy — without API key (cache-only)
# ============================================================


class TestLLMStrategyCacheOnly:
    def test_no_provider_response_no_cache_returns_none(self):
        """cache_only=True returns None on cache miss without calling provider."""
        with tempfile.TemporaryDirectory() as tmp:
            cache = LLMCache(cache_dir=Path(tmp))
            mock = MockProvider(response=None)
            strategy = LLMStrategy(provider=mock, cache=cache, cache_only=True, use_rag=False)
            f = make_features()
            result = strategy.ask(f)
            assert result is None
            assert mock.call_count == 0

    def test_cache_hit_returns_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = LLMCache(cache_dir=Path(tmp))
            mock = MockProvider(response=None)
            strategy = LLMStrategy(provider=mock, cache=cache, cache_only=True, use_rag=False)
            f = make_features()

            # Pre-populate cache (using provider's cache_signature)
            user_msg = build_user_prompt(f)
            key = cache.make_key(SYSTEM_PROMPT, user_msg, mock.cache_signature(),
                                 mock.temperature, SCHEMA_SIGNATURE)
            cache.put(key, valid_llm_response("COMPRA"))

            signal = strategy.ask(f)
            assert signal is not None
            assert signal.action == Action.COMPRA
            assert signal.confidence == 75
            assert signal.setup == SetupType.SECOND_ENTRY_H2
            assert mock.call_count == 0

    def test_cache_hit_no_provider_call(self):
        """Cache hit must NOT call provider."""
        with tempfile.TemporaryDirectory() as tmp:
            cache = LLMCache(cache_dir=Path(tmp))
            mock = MockProvider(response=None)
            strategy = LLMStrategy(provider=mock, cache=cache, cache_only=False, use_rag=False)
            f = make_features()

            user_msg = build_user_prompt(f)
            key = cache.make_key(SYSTEM_PROMPT, user_msg, mock.cache_signature(),
                                 mock.temperature, SCHEMA_SIGNATURE)
            cache.put(key, valid_llm_response("VENDA"))

            signal = strategy.ask(f)
            assert signal is not None
            assert signal.action == Action.VENDA
            assert mock.call_count == 0

    def test_cache_miss_calls_provider_and_caches(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = LLMCache(cache_dir=Path(tmp))
            mock = MockProvider(response=valid_llm_response("COMPRA"))
            strategy = LLMStrategy(provider=mock, cache=cache, use_rag=False)
            f = make_features()

            signal = strategy.ask(f)
            assert signal is not None
            assert signal.action == Action.COMPRA
            assert mock.call_count == 1

            # Second ask: same features → cache hit
            signal2 = strategy.ask(f)
            assert signal2 is not None
            assert mock.call_count == 1  # not 2

    def test_provider_error_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = LLMCache(cache_dir=Path(tmp))
            mock = MockProvider(raises=ProviderError("API down"))
            strategy = LLMStrategy(provider=mock, cache=cache, use_rag=False)
            f = make_features()
            assert strategy.ask(f) is None


# ============================================================
# LLMStrategy — _parse_response
# ============================================================


class TestParseResponse:
    def _strategy(self):
        with tempfile.TemporaryDirectory() as tmp:
            mock = MockProvider(response=None)
            return LLMStrategy(provider=mock, cache=LLMCache(cache_dir=Path(tmp)), use_rag=False)

    def test_valid_compra(self):
        s = self._strategy()
        f = make_features()
        signal = s._parse_response(valid_llm_response("COMPRA"), f)
        assert signal.action == Action.COMPRA
        assert signal.day_type == DayType.TREND_FROM_OPEN
        assert signal.always_in == AlwaysIn.SEMPRE_COMPRADO
        assert signal.setup == SetupType.SECOND_ENTRY_H2
        assert signal.signal_bar_quality == SignalBarQuality.APROVADO
        assert signal.entry_price == 67000.0
        assert signal.stop_loss == 66598.0
        assert signal.take_profit == 67804.0
        assert signal.decisive_layer == 5

    def test_valid_aguardar(self):
        s = self._strategy()
        f = make_features()
        data = valid_llm_response("AGUARDAR")
        signal = s._parse_response(data, f)
        assert signal.action == Action.AGUARDAR

    def test_invalid_action_falls_back_aguardar(self):
        s = self._strategy()
        data = valid_llm_response()
        data["action"] = "INVALID_ACTION"
        signal = s._parse_response(data, make_features())
        assert signal.action == Action.AGUARDAR

    def test_invalid_setup_falls_back_none(self):
        s = self._strategy()
        data = valid_llm_response()
        data["layer5_setup"] = "nonsense_setup"
        signal = s._parse_response(data, make_features())
        assert signal.setup == SetupType.NONE

    def test_confidence_clamped_high(self):
        s = self._strategy()
        data = valid_llm_response()
        data["confidence"] = 200
        signal = s._parse_response(data, make_features())
        assert signal.confidence == 100

    def test_confidence_clamped_low(self):
        s = self._strategy()
        data = valid_llm_response()
        data["confidence"] = -50
        signal = s._parse_response(data, make_features())
        assert signal.confidence == 0

    def test_decisive_layer_clamped(self):
        s = self._strategy()
        data = valid_llm_response()
        data["decisive_layer"] = 99
        signal = s._parse_response(data, make_features())
        assert signal.decisive_layer == 5

    def test_strips_meta_field(self):
        s = self._strategy()
        data = valid_llm_response()
        data["_meta"] = {"ts": "2026-01-01"}
        # Should still parse without raising
        signal = s._parse_response(data, make_features())
        assert signal is not None

    def test_long_reasoning_truncated(self):
        s = self._strategy()
        data = valid_llm_response()
        data["reasoning"] = "x" * 2000
        signal = s._parse_response(data, make_features())
        assert len(signal.reasoning) <= 500


# ============================================================
# v1.4 stop_distance >= 0.5% guard
# ============================================================
#
# Background: in the 1000-candle backtest dated 2026-04-09, every trade with
# stop_distance < 0.4% of entry lost money because the tight stop scaled position
# size up to the leverage cap, multiplying fees beyond gross loss. The v1.4
# prompt asks the LLM to respect a 0.5% minimum, but a prompt is not a contract:
# the LLM can ignore it. These tests pin a code-side guard so the rule is
# enforced regardless of what the LLM returns.


class TestStopDistanceGuard:
    def _strategy(self):
        with tempfile.TemporaryDirectory() as tmp:
            mock = MockProvider(response=None)
            return LLMStrategy(provider=mock, cache=LLMCache(cache_dir=Path(tmp)), use_rag=False)

    def test_constant_is_half_percent(self):
        assert MIN_STOP_DISTANCE_PCT == 0.005

    def test_compra_with_too_tight_stop_coerces_to_aguardar(self):
        # 67000 entry, 66950 stop → distance 50 = 0.075% (well under 0.5%)
        s = self._strategy()
        data = valid_llm_response("COMPRA")
        data["stop_loss"] = 66950.0
        signal = s._parse_response(data, make_features())
        assert signal.action == Action.AGUARDAR
        # Coerced placeholders: stop and target collapse to entry
        assert signal.stop_loss == signal.entry_price
        assert signal.take_profit == signal.entry_price

    def test_venda_with_too_tight_stop_coerces_to_aguardar(self):
        # 67000 entry, 67050 stop → distance 50 (0.075%)
        s = self._strategy()
        data = valid_llm_response("VENDA")
        data["stop_loss"] = 67050.0
        signal = s._parse_response(data, make_features())
        assert signal.action == Action.AGUARDAR

    def test_compra_at_exact_minimum_is_allowed(self):
        # 67000 entry, stop 67000*(1 - 0.005) = 66665 → distance exactly 0.5%
        s = self._strategy()
        data = valid_llm_response("COMPRA")
        data["stop_loss"] = 67000.0 * (1 - MIN_STOP_DISTANCE_PCT)
        signal = s._parse_response(data, make_features())
        assert signal.action == Action.COMPRA

    def test_compra_well_above_minimum_is_allowed(self):
        # 67000 entry, 66330 stop → distance 1.0%, target 68340 → distance 2.0%, RR 2.0
        s = self._strategy()
        data = valid_llm_response("COMPRA")
        data["stop_loss"] = 66330.0
        data["take_profit"] = 68340.0  # bumped to satisfy RR >= 1.5
        signal = s._parse_response(data, make_features())
        assert signal.action == Action.COMPRA
        assert signal.stop_loss == 66330.0

    def test_aguardar_response_is_not_affected_by_guard(self):
        # AGUARDAR with placeholder stop=entry must remain AGUARDAR (not crash on 0 distance)
        s = self._strategy()
        data = valid_llm_response("AGUARDAR")
        data["stop_loss"] = data["entry_price"]
        data["take_profit"] = data["entry_price"]
        signal = s._parse_response(data, make_features())
        assert signal.action == Action.AGUARDAR


# ============================================================
# v1.5 target_distance >= 1% and RR >= 1.5 guards
# ============================================================
#
# Background: in the v1.4 backtest, wins kept closing at RR ~1.0 while losses
# always hit full -1.0 stop, producing a $44 win vs $96 loss asymmetry. The LLM
# was technically saying "Nogran PA" but ignoring Nogran PA' actual RR rules (Nogran PA
# teaches RR >= 2.0 for scalps, 3-4x for swings). These guards lock the rule in
# code so the LLM cannot bypass it by hallucinating short targets.


class TestTargetAndRRGuards:
    def _strategy(self):
        with tempfile.TemporaryDirectory() as tmp:
            mock = MockProvider(response=None)
            return LLMStrategy(provider=mock, cache=LLMCache(cache_dir=Path(tmp)), use_rag=False)

    def test_constants_are_pinned(self):
        # 2026-04-09 — RR floor lowered from 1.5 → 1.0 to be Nogran PA-compliant.
        # Nogran PA accepts 1:1 RR for high-probability shaved-bar / second-entry
        # setups where probability >= 60% compensates the low ratio.
        assert MIN_TARGET_DISTANCE_PCT == 0.010
        assert MIN_RR_RATIO == 1.0

    def test_compra_target_too_tight_coerces_aguardar(self):
        # 67000 entry, stop 66600 (0.6% — passes stop guard),
        # target 67500 → distance 500 = 0.746% < 1.0% guard
        s = self._strategy()
        data = valid_llm_response("COMPRA")
        data["entry_price"] = 67000.0
        data["stop_loss"] = 66600.0
        data["take_profit"] = 67500.0
        signal = s._parse_response(data, make_features())
        assert signal.action == Action.AGUARDAR

    def test_venda_target_too_tight_coerces_aguardar(self):
        # 67000 entry, stop 67400 (0.6%), target 66500 (0.746%) → fails 1% rule
        s = self._strategy()
        data = valid_llm_response("VENDA")
        data["entry_price"] = 67000.0
        data["stop_loss"] = 67400.0
        data["take_profit"] = 66500.0
        signal = s._parse_response(data, make_features())
        assert signal.action == Action.AGUARDAR

    def test_compra_low_rr_coerces_aguardar(self):
        # Both stop and target pass distance rules individually,
        # but RR < 1.0 (post v2.0): stop 1.5%, target 1.2% → RR 0.8
        s = self._strategy()
        data = valid_llm_response("COMPRA")
        data["entry_price"] = 67000.0
        data["stop_loss"] = 66000.0    # -1.49% (1.5% stop)
        data["take_profit"] = 67804.0  # +1.2% target → RR ~0.8
        signal = s._parse_response(data, make_features())
        assert signal.action == Action.AGUARDAR

    def test_compra_at_minimum_rr_passes(self):
        # Post v2.0: minimum RR is 1.0 (Nogran PA accepts shaved-bar 1:1 setups).
        # stop 1.0%, target 1.0% → RR exactly 1.0
        s = self._strategy()
        data = valid_llm_response("COMPRA")
        data["entry_price"] = 67000.0
        data["stop_loss"] = 66330.0     # -1.0%
        data["take_profit"] = 67670.0   # +1.0% → RR 1.0
        signal = s._parse_response(data, make_features())
        assert signal.action == Action.COMPRA

    def test_compra_with_rr_2_passes(self):
        # stop 1.0%, target 2.0% → RR 2.0 (Nogran PA scalp minimum)
        s = self._strategy()
        data = valid_llm_response("COMPRA")
        data["entry_price"] = 67000.0
        data["stop_loss"] = 66330.0      # -1.0%
        data["take_profit"] = 68340.0    # +2.0%
        signal = s._parse_response(data, make_features())
        assert signal.action == Action.COMPRA

    def test_combined_chain_stop_first_then_target_then_rr(self):
        # Stop guard fires FIRST. Even if target/RR are also bad, log says stop.
        s = self._strategy()
        data = valid_llm_response("COMPRA")
        data["entry_price"] = 67000.0
        data["stop_loss"] = 66950.0   # 0.075% — stop guard fires first
        data["take_profit"] = 67050.0  # also bad, but stop catches it first
        signal = s._parse_response(data, make_features())
        assert signal.action == Action.AGUARDAR
