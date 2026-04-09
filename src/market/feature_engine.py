import logging
from datetime import datetime, timezone

from domain.models import Candle as CandleModel
from domain.models import FeatureSnapshot
from infra.indicators import (
    adx,
    atr,
    atr_series,
    calculate_bar_overlap,
    count_consecutive,
    count_direction_changes,
    ema_current,
    sma,
)
from market.always_in import compute_always_in
from market.candle_buffer import CandleBuffer
from market.failed_attempts import detect_failed_attempts
from market.regime_classifier import classify_regime
from market.swing_points import compute_swing_context


def aggregate_to_higher_tf(candles: list, group_size: int = 4) -> list:
    """Aggregate N consecutive candles into one higher-tf candle.

    For 15m → 1h, group_size=4. The aggregation drops any trailing partial group
    so we always work with completed higher-tf bars.
    """
    if not candles or group_size <= 1:
        return list(candles)
    out = []
    n = (len(candles) // group_size) * group_size
    for i in range(0, n, group_size):
        chunk = candles[i:i + group_size]
        out.append(CandleModel(
            timestamp=chunk[0].timestamp,
            open=chunk[0].open,
            high=max(c.high for c in chunk),
            low=min(c.low for c in chunk),
            close=chunk[-1].close,
            volume=sum(c.volume for c in chunk),
        ))
    return out

logger = logging.getLogger(__name__)


class FeatureEngine:
    """Computes FeatureSnapshot from candle buffers."""

    def compute(
        self,
        buf_1m: CandleBuffer,
        buf_5m: CandleBuffer | None = None,
        candle_index: int = 0,
    ) -> FeatureSnapshot | None:
        """
        Compute features from the 1m buffer (and optional 5m buffer).
        Returns None if insufficient data (need at least 21 candles for EMA(20)).
        """
        if len(buf_1m) < 21:
            logger.warning(f"Insufficient data: {len(buf_1m)} candles (need 21)")
            return None

        candle = buf_1m.latest
        closes = buf_1m.closes()
        hlc = buf_1m.hlc_tuples()
        hl = buf_1m.hl_tuples()
        volumes = buf_1m.volumes()
        bullish_list = buf_1m.is_bullish_list()

        # Core indicators
        current_ema_20 = ema_current(closes, 20)
        current_atr_14 = atr(hlc, 14)
        atr_values = atr_series(hlc, 14)
        current_atr_sma_20 = sma(atr_values, 20) if len(atr_values) >= 20 else current_atr_14
        current_adx_14 = adx(hlc, 14)

        # Price vs EMA
        price_vs_ema = ((candle.close - current_ema_20) / current_ema_20 * 100) if current_ema_20 > 0 else 0.0

        # ATR dynamics
        atr_ratio = current_atr_14 / current_atr_sma_20 if current_atr_sma_20 > 0 else 1.0
        atr_expanding = atr_ratio > 1.15
        atr_contracting = atr_ratio < 0.75

        # Bar analysis
        consecutive_bull, consecutive_bear = count_consecutive(bullish_list)
        overlap_ratio = calculate_bar_overlap(hl[-10:]) if len(hl) >= 10 else 0.0
        direction_changes = count_direction_changes(bullish_list[-10:]) if len(bullish_list) >= 10 else 0.5

        # Pullback context — distinguishes "spike top" from "pullback low".
        # H2/L2 entries happen on the pullback, not the spike.
        recent5_hl = hl[-5:] if len(hl) >= 5 else hl
        if recent5_hl:
            highs5 = [h for h, _ in recent5_hl]
            lows5 = [l for _, l in recent5_hl]
            max_high5 = max(highs5)
            min_low5 = min(lows5)
            is_at_5bar_high = candle.high >= max_high5
            is_at_5bar_low = candle.low <= min_low5
            # bars_since: count from end (0 = current bar set the extreme)
            bars_since_5bar_high = 0
            for i in range(len(highs5) - 1, -1, -1):
                if highs5[i] >= max_high5:
                    bars_since_5bar_high = (len(highs5) - 1) - i
                    break
            bars_since_5bar_low = 0
            for i in range(len(lows5) - 1, -1, -1):
                if lows5[i] <= min_low5:
                    bars_since_5bar_low = (len(lows5) - 1) - i
                    break
        else:
            is_at_5bar_high = False
            is_at_5bar_low = False
            bars_since_5bar_high = 0
            bars_since_5bar_low = 0

        # Volume
        vol_sma = sma(volumes, 20) if len(volumes) >= 20 else (sum(volumes) / len(volumes) if volumes else 1.0)
        volume_ratio = candle.volume / vol_sma if vol_sma > 0 else 1.0

        # Session check (13:00-21:00 UTC = peak liquidity).
        # F1.5 fix: usar o timestamp do CANDLE, nao wallclock. O `datetime.now()`
        # original tornava is_peak_session non-deterministic entre runs (cada run em
        # horario diferente gerava prompt diferente), invalidando o cache do LLM em
        # 100% das chamadas. Tambem causava lookahead bias (live "now" vazando pro
        # backtest). Timestamps Candle estao em ms epoch.
        candle_dt = datetime.fromtimestamp(candle.timestamp / 1000, tz=timezone.utc)
        is_peak = 13 <= candle_dt.hour < 21

        # 5m context
        tf_5m_direction = None
        tf_5m_ema_20 = None
        tf_5m_cons_bull = 0
        tf_5m_cons_bear = 0
        tf_5m_price_vs_ema = None

        if buf_5m and len(buf_5m) >= 21:
            closes_5m = buf_5m.closes()
            tf_5m_ema_20 = ema_current(closes_5m, 20)
            bullish_5m = buf_5m.is_bullish_list()
            tf_5m_cons_bull, tf_5m_cons_bear = count_consecutive(bullish_5m)
            latest_5m = buf_5m.latest
            if latest_5m:
                tf_5m_direction = "ALTA" if latest_5m.is_bullish else "BAIXA"
                if tf_5m_ema_20 > 0:
                    tf_5m_price_vs_ema = (latest_5m.close - tf_5m_ema_20) / tf_5m_ema_20 * 100

        # Recent bars sequence (Fix A: pattern recognition for H2/L2 setups)
        # Last 6 bars including the current one (index 0..5, 5 = current).
        all_buf = list(buf_1m._candles)
        recent_bars_list = all_buf[-6:] if len(all_buf) >= 6 else all_buf

        # Swing structure (Bloco 1: HH/HL classification + last swing levels)
        # PA methodology reads the market via swing highs/lows. Without this we can't
        # distinguish "spike top" (no recent swing low to retrace to) from
        # "pullback after swing low" (H2 entry).
        swing_ctx = compute_swing_context(all_buf, lookback=2, window=50)

        # Failed-attempt tracker (Bloco 6: second-entry rule)
        failed_ctx = detect_failed_attempts(
            all_buf,
            last_swing_high=swing_ctx.last_swing_high,
            last_swing_low=swing_ctx.last_swing_low,
            lookback=6,
        )

        # EMA test detection (Bloco 2: pullback-to-mean signals)
        # Rule: "every EMA test in a strong trend is a buy/sell".
        is_touching_ema = (candle.low <= current_ema_20 <= candle.high)

        # bars_since_ema_test: walk back through buffer to find last touch
        bars_since_ema_test = -1
        # We need EMA at each historical bar to check touch. Recompute incrementally.
        # Use a simpler approximation: look at last N bars and if any range crossed
        # the CURRENT EMA value (good enough — the EMA moves slowly).
        if is_touching_ema:
            bars_since_ema_test = 0
        elif current_ema_20 > 0:
            for back, prior in enumerate(reversed(all_buf[:-1]), start=1):
                if prior.low <= current_ema_20 <= prior.high:
                    bars_since_ema_test = back
                    break
                if back >= 50:  # cap lookback
                    break

        # Higher timeframe (1h) — aggregated from 15m exec buffer.
        # Rule: trade WITH the HTF trend whenever possible.
        tf_1h_direction = None
        tf_1h_ema_20 = None
        tf_1h_price_vs_ema = None
        tf_1h_cons_bull = 0
        tf_1h_cons_bear = 0
        tf_1h_adx = 0.0
        tf_1h_above_ema = False
        tf_1h_below_ema = False

        agg_1h = aggregate_to_higher_tf(all_buf, group_size=4)
        if len(agg_1h) >= 21:
            closes_1h = [c.close for c in agg_1h]
            hlc_1h = [(c.high, c.low, c.close) for c in agg_1h]
            tf_1h_ema_20 = ema_current(closes_1h, 20)
            latest_1h = agg_1h[-1]
            if tf_1h_ema_20 > 0:
                tf_1h_price_vs_ema = (latest_1h.close - tf_1h_ema_20) / tf_1h_ema_20 * 100
                tf_1h_above_ema = latest_1h.close > tf_1h_ema_20
                tf_1h_below_ema = latest_1h.close < tf_1h_ema_20
            tf_1h_direction = "up" if latest_1h.is_bullish else "down"
            bullish_1h = [c.is_bullish for c in agg_1h]
            tf_1h_cons_bull, tf_1h_cons_bear = count_consecutive(bullish_1h)
            tf_1h_adx = adx(hlc_1h, 14)

        # EMA slope over last 5 bars
        ema_slope_5bar = 0.0
        ema_slope_direction = "flat"
        if len(closes) >= 25:  # need 5 bars + 20 for EMA history
            ema_5_ago = ema_current(closes[:-5], 20)
            if ema_5_ago > 0:
                ema_slope_5bar = (current_ema_20 - ema_5_ago) / ema_5_ago * 100
                if ema_slope_5bar > 0.05:
                    ema_slope_direction = "up"
                elif ema_slope_5bar < -0.05:
                    ema_slope_direction = "down"

        return FeatureSnapshot(
            candle=candle,
            candle_index=candle_index,
            ema_20=current_ema_20,
            atr_14=current_atr_14,
            atr_sma_20=current_atr_sma_20,
            adx_14=current_adx_14,
            price_vs_ema=price_vs_ema,
            atr_ratio=atr_ratio,
            body_pct=candle.body_pct,
            upper_tail_pct=candle.upper_tail_pct,
            lower_tail_pct=candle.lower_tail_pct,
            consecutive_bull=consecutive_bull,
            consecutive_bear=consecutive_bear,
            bar_overlap_ratio=overlap_ratio,
            direction_change_ratio=direction_changes,
            volume_ratio=volume_ratio,
            tf_5m_direction=tf_5m_direction,
            tf_5m_ema_20=tf_5m_ema_20,
            tf_5m_consecutive_bull=tf_5m_cons_bull,
            tf_5m_consecutive_bear=tf_5m_cons_bear,
            tf_5m_price_vs_ema=tf_5m_price_vs_ema,
            is_peak_session=is_peak,
            atr_expanding=atr_expanding,
            atr_contracting=atr_contracting,
            is_at_5bar_high=is_at_5bar_high,
            is_at_5bar_low=is_at_5bar_low,
            bars_since_5bar_high=bars_since_5bar_high,
            bars_since_5bar_low=bars_since_5bar_low,
            recent_bars=recent_bars_list,
            last_swing_high=swing_ctx.last_swing_high,
            last_swing_low=swing_ctx.last_swing_low,
            bars_since_swing_high=swing_ctx.bars_since_swing_high,
            bars_since_swing_low=swing_ctx.bars_since_swing_low,
            structure_classification=swing_ctx.structure,
            swing_high_count=swing_ctx.swing_high_count,
            swing_low_count=swing_ctx.swing_low_count,
            is_touching_ema=is_touching_ema,
            bars_since_ema_test=bars_since_ema_test,
            ema_slope_5bar=ema_slope_5bar,
            ema_slope_direction=ema_slope_direction,
            tf_1h_direction=tf_1h_direction,
            tf_1h_ema_20=tf_1h_ema_20,
            tf_1h_price_vs_ema=tf_1h_price_vs_ema,
            tf_1h_consecutive_bull=tf_1h_cons_bull,
            tf_1h_consecutive_bear=tf_1h_cons_bear,
            tf_1h_adx=tf_1h_adx,
            tf_1h_above_ema=tf_1h_above_ema,
            tf_1h_below_ema=tf_1h_below_ema,
            regime=classify_regime(
                structure=swing_ctx.structure,
                adx=current_adx_14,
                bar_overlap=overlap_ratio,
                consecutive_bull=consecutive_bull,
                consecutive_bear=consecutive_bear,
                atr_ratio=atr_ratio,
                tf_1h_above_ema=tf_1h_above_ema,
                tf_1h_below_ema=tf_1h_below_ema,
                tf_1h_direction=tf_1h_direction,
            ),
            computed_always_in=compute_always_in(
                last_bar_is_bull=candle.is_bullish,
                last_5_bull_count=sum(1 for b in bullish_list[-5:] if b),
                price_above_ema=candle.close > current_ema_20,
                structure=swing_ctx.structure,
                tf_1h_above_ema=tf_1h_above_ema,
                tf_1h_direction=tf_1h_direction,
            ),
            bars_since_failed_breakout_up=failed_ctx.bars_since_failed_breakout_up,
            bars_since_failed_breakout_down=failed_ctx.bars_since_failed_breakout_down,
            second_attempt_long_pending=failed_ctx.second_attempt_long_pending,
            second_attempt_short_pending=failed_ctx.second_attempt_short_pending,
        )
