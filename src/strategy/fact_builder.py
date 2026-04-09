from domain.models import FeatureSnapshot


def build_fact(features: FeatureSnapshot, timeframe: str = "1m") -> str:
    """
    Build the enriched mathematical fact string from features.
    This is the ONLY thing the LLM sees — no raw data.
    """
    candle = features.candle
    direction = "ALTA" if candle.is_bullish else "BAIXA"

    # Consecutive bars
    if features.consecutive_bull > 0:
        consecutive_str = f"{features.consecutive_bull} barras bull consecutivas"
    elif features.consecutive_bear > 0:
        consecutive_str = f"{features.consecutive_bear} barras bear consecutivas"
    else:
        consecutive_str = "sem sequencia direcional"

    # Price vs EMA
    ema_position = "acima" if features.price_vs_ema > 0 else "abaixo"

    # ATR interpretation
    if features.atr_ratio > 1.15:
        atr_desc = "volatilidade alta (ATR expandindo)"
    elif features.atr_ratio < 0.75:
        atr_desc = "volatilidade baixa (ATR contraindo)"
    elif features.atr_ratio < 0.9:
        atr_desc = "volatilidade normal-baixa"
    else:
        atr_desc = "volatilidade normal"

    lines = [
        f"Vela {timeframe} #{features.candle_index} fechou em {direction}.",
        f"OHLCV: O=${candle.open:.1f} H=${candle.high:.1f} L=${candle.low:.1f} C=${candle.close:.1f} V={candle.volume:.4f}.",
        f"Corpo: {features.body_pct:.1f}% do range. Cauda superior: {features.upper_tail_pct:.1f}%. Cauda inferior: {features.lower_tail_pct:.1f}%.",
        f"Tendencia: {consecutive_str}.",
        f"EMA(20): ${features.ema_20:.1f}. Preco {ema_position} da EMA. Distancia: {features.price_vs_ema:+.2f}%.",
        f"ATR(14): ${features.atr_14:.1f}. ATR relativo a media: {features.atr_ratio:.2f} ({atr_desc}).",
    ]

    # 5m context (if available)
    if features.tf_5m_direction is not None:
        cons_5m = ""
        if features.tf_5m_consecutive_bull > 0:
            cons_5m = f", {features.tf_5m_consecutive_bull} barras bull consecutivas"
        elif features.tf_5m_consecutive_bear > 0:
            cons_5m = f", {features.tf_5m_consecutive_bear} barras bear consecutivas"

        ema_5m_str = ""
        if features.tf_5m_ema_20 is not None:
            pos_5m = "acima" if (features.tf_5m_price_vs_ema or 0) > 0 else "abaixo"
            ema_5m_str = f", preco {pos_5m} EMA(20) 5m"

        lines.append(f"Contexto 5m: ultima vela {features.tf_5m_direction}{ema_5m_str}{cons_5m}.")

    return "\n".join(lines)
