"""
Local signal generator — produces TradeSignals from features WITHOUT calling the LLM.

Usado quando:
1. Live trading sem LLM (STRATEGY_SOURCE=mock, sem custo de API)
2. Backtest determinstico (scripts/backtest.py)
3. Demo offline

A heuristica e Nogran PA-aware, deterministica, e respeita strict_trend_alignment
para nao gerar counter-trend trades em uptrends/downtrends fortes.

Esta logica e o **mesmo** mock heuristic usado em scripts/simulate_market.py
e scripts/backtest.py. Centralizamos aqui pra que `src/main.py` possa importar
sem dependencia em scripts/.
"""

from __future__ import annotations

from datetime import datetime, timezone

from domain.enums import Action, AlwaysIn, DayType, Regime, SetupType, SignalBarQuality
from domain.models import FeatureSnapshot, TradeSignal

# Trend alignment thresholds (em pct EMA distance)
STRONG_UP = 0.8
STRONG_DOWN = -0.8


def _make(action, conf, day_type, always_in, setup, reason, entry, stop, target):
    return TradeSignal(
        action=action,
        confidence=conf,
        day_type=DayType(day_type),
        always_in=AlwaysIn(always_in),
        setup=setup,
        signal_bar_quality=SignalBarQuality.APROVADO,
        entry_price=entry,
        stop_loss=stop,
        take_profit=target,
        decisive_layer=5 if action != Action.AGUARDAR else 1,
        reasoning=reason,
        timestamp=datetime.now(timezone.utc),
    )


def detect_local_regime(features: FeatureSnapshot) -> Regime:
    """Regime detector simples sem ML."""
    if features.adx_14 >= 25 and features.bar_overlap_ratio < 0.45:
        return Regime.TRENDING
    if features.bar_overlap_ratio > 0.55:
        return Regime.RANGING
    return Regime.TRANSITIONING


def generate_local_signal(
    features: FeatureSnapshot,
    regime: Regime | None = None,
    strict_trend_alignment: bool = True,
) -> TradeSignal:
    """Gera TradeSignal sem chamar o LLM.

    Heuristics roughly mirror the Nogran PA teaching:
    - Strong consecutive bull bars + body% in trending regime -> H2 BUY
    - Strong consecutive bear bars + bearish bias -> L2 SELL
    - Choppy/transitioning -> AGUARDAR
    - Wedge top (large upper tails after run-up) -> SELL hypothesis
    - Always-in long (uptrend forte) -> bull pullback BUY
    - Always-in short (downtrend forte) -> bear pullback SELL

    `strict_trend_alignment=True` adds the rule: "NUNCA opere contra
    tendencia sem quebra de LT significativa". Default True em live.
    """
    if regime is None:
        regime = detect_local_regime(features)

    candle = features.candle
    ema_diff = features.price_vs_ema
    body = features.body_pct
    consec_bull = features.consecutive_bull
    consec_bear = features.consecutive_bear
    upper_tail = features.upper_tail_pct
    is_bull = candle.is_bullish

    # Choppy / transitioning -> wait
    if regime == Regime.RANGING or features.bar_overlap_ratio > 0.55:
        return _make(Action.AGUARDAR, 30, "trending_trading_range",
                     AlwaysIn.NEUTRO, SetupType.NONE,
                     "Mercado em trading range, aguardar quebra.",
                     entry=candle.close, stop=candle.close, target=candle.close)

    # Wedge top SHORT
    wedge_top_ok = upper_tail >= 30 and consec_bull >= 2 and ema_diff > 0
    if strict_trend_alignment and ema_diff > STRONG_UP:
        wedge_top_ok = False
    if wedge_top_ok:
        return _make(
            Action.VENDA, 55, "reversal_day", AlwaysIn.NEUTRO,
            SetupType.BREAKOUT_PULLBACK,
            "Wedge top — tres empurroes para cima, tail superior crescendo.",
            entry=candle.close, stop=candle.close + features.atr_14,
            target=candle.close - features.atr_14 * 2,
        )

    # Bull continuation H2
    bull_ok = is_bull and consec_bull >= 2 and ema_diff > -0.5 and body >= 40
    if strict_trend_alignment and ema_diff < STRONG_DOWN:
        bull_ok = False
    if bull_ok:
        return _make(
            Action.COMPRA, 72, "trend_from_open", AlwaysIn.SEMPRE_COMPRADO,
            SetupType.SECOND_ENTRY_H2,
            "Pullback completou H2 acima da EMA20 — segunda entrada em bull trend.",
            entry=candle.close, stop=candle.close - features.atr_14,
            target=candle.close + features.atr_14 * 2,
        )

    # Bear continuation L2
    bear_ok = not is_bull and consec_bear >= 2 and ema_diff < 0.5 and body >= 40
    if strict_trend_alignment and ema_diff > STRONG_UP:
        bear_ok = False
    if bear_ok:
        return _make(
            Action.VENDA, 72, "spike_and_channel", AlwaysIn.SEMPRE_VENDIDO,
            SetupType.SECOND_ENTRY_H2,
            "Pullback completou L2 abaixo da EMA20 — segunda entrada em bear trend.",
            entry=candle.close, stop=candle.close + features.atr_14,
            target=candle.close - features.atr_14 * 2,
        )

    # Always-in long pullback
    if strict_trend_alignment and ema_diff > STRONG_UP and is_bull and consec_bull >= 1:
        return _make(
            Action.COMPRA, 65, "trend_from_open", AlwaysIn.SEMPRE_COMPRADO,
            SetupType.H2_EMA,
            "Always-in long — uptrend forte, comprar pullback tecnico.",
            entry=candle.close, stop=candle.close - features.atr_14,
            target=candle.close + features.atr_14 * 2,
        )

    # Always-in short pullback
    if strict_trend_alignment and ema_diff < STRONG_DOWN and not is_bull and consec_bear >= 1:
        return _make(
            Action.VENDA, 65, "spike_and_channel", AlwaysIn.SEMPRE_VENDIDO,
            SetupType.H2_EMA,
            "Always-in short — downtrend forte, vender pullback tecnico.",
            entry=candle.close, stop=candle.close + features.atr_14,
            target=candle.close - features.atr_14 * 2,
        )

    return _make(Action.AGUARDAR, 25, "indefinido", AlwaysIn.NEUTRO,
                 SetupType.NONE, "Sem sinal claro nesta barra.",
                 entry=candle.close, stop=candle.close, target=candle.close)
