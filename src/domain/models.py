from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from domain.enums import (
    Action,
    AlwaysIn,
    DayType,
    DrawdownBand,
    Regime,
    SetupType,
    SignalBarQuality,
)


@dataclass
class Candle:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def body_pct(self) -> float:
        return (self.body / self.range * 100) if self.range > 0 else 0.0

    @property
    def is_bullish(self) -> bool:
        return self.close >= self.open

    @property
    def upper_tail_pct(self) -> float:
        if self.range == 0:
            return 0.0
        top = max(self.open, self.close)
        return (self.high - top) / self.range * 100

    @property
    def lower_tail_pct(self) -> float:
        if self.range == 0:
            return 0.0
        bottom = min(self.open, self.close)
        return (bottom - self.low) / self.range * 100


@dataclass
class FeatureSnapshot:
    """All computed features for the current candle + context."""
    # Current candle
    candle: Candle
    candle_index: int

    # Indicators
    ema_20: float
    atr_14: float
    atr_sma_20: float  # SMA of ATR for relative comparison
    adx_14: float

    # Derived
    price_vs_ema: float        # (close - ema) / ema * 100
    atr_ratio: float           # atr / atr_sma_20
    body_pct: float
    upper_tail_pct: float
    lower_tail_pct: float
    consecutive_bull: int
    consecutive_bear: int
    bar_overlap_ratio: float   # 0.0 to 1.0 — overlap of last 10 bars
    direction_change_ratio: float  # 0.0 to 1.0 — how often direction flips

    # Volume
    volume_ratio: float        # current vol / sma(vol, 20)

    # Multi-TF (5m context)
    tf_5m_direction: Optional[str] = None   # "ALTA" | "BAIXA" | None
    tf_5m_ema_20: Optional[float] = None
    tf_5m_consecutive_bull: int = 0
    tf_5m_consecutive_bear: int = 0
    tf_5m_price_vs_ema: Optional[float] = None

    # Higher timeframe context (1h aggregated from 15m — Bloco 3 of P0 sprint).
    # Rule: "always check the higher timeframe before entering. Trading
    # against the HTF trend has ~30% WR." On 15m exec, 1h is the natural HTF.
    tf_1h_direction: Optional[str] = None   # "up" | "down" | "flat" | None
    tf_1h_ema_20: Optional[float] = None
    tf_1h_price_vs_ema: Optional[float] = None
    tf_1h_consecutive_bull: int = 0
    tf_1h_consecutive_bear: int = 0
    tf_1h_adx: float = 0.0
    tf_1h_above_ema: bool = False
    tf_1h_below_ema: bool = False

    # Session
    is_peak_session: bool = False  # 13:00-21:00 UTC

    # ATR dynamics
    atr_expanding: bool = False
    atr_contracting: bool = False

    # Pullback context (added 2026-04-09 — fix for "buying spike top" pattern).
    # H2 entries happen on the PULLBACK after a spike, not on the spike
    # itself. These features tell the LLM where the current candle sits relative
    # to recent extremes so it can distinguish "spike top" from "pullback low".
    is_at_5bar_high: bool = False        # current high is the highest of last 5 bars
    is_at_5bar_low: bool = False         # current low is the lowest of last 5 bars
    bars_since_5bar_high: int = 0        # 0 = current bar is the 5-bar high
    bars_since_5bar_low: int = 0         # 0 = current bar is the 5-bar low

    # Recent bar sequence (added 2026-04-09 — Fix A: pattern recognition).
    # A price action trader reads CHARTS, not statistics. Single-bar features
    # summarize the current bar but lose the SEQUENCE that defines H2/L2 setups
    # (1-2 pullback bars, then resumption). Feeding the LLM the actual last N
    # bars lets it recognize "pullback finished, resumption starting" visually.
    # Empty list = not populated by feature engine.
    recent_bars: list = field(default_factory=list)

    # Swing structure (added 2026-04-09 — Bloco 1 of P0 sprint).
    # Market structure is defined via swing highs and lows. Without these
    # fields the LLM has no way to identify HH/HL (uptrend) vs LH/LL (downtrend)
    # vs ranges/wedges. Stops are placed at the last swing low (long) or
    # swing high (short).
    last_swing_high: Optional[float] = None
    last_swing_low: Optional[float] = None
    bars_since_swing_high: int = -1
    bars_since_swing_low: int = -1
    structure_classification: str = "INDETERMINATE"  # HH_HL | LH_LL | HH_LL | LH_HL | INDETERMINATE
    swing_high_count: int = 0
    swing_low_count: int = 0

    # EMA test detection (Bloco 2 of P0 sprint).
    # Rule: "every EMA test in a strong trend is a buy/sell". The current
    # bar may be testing the EMA from above (pullback in uptrend) or below
    # (pullback in downtrend). bars_since_ema_test = how many bars since the
    # last touch (-1 if never).
    is_touching_ema: bool = False        # current bar's range crosses EMA20
    bars_since_ema_test: int = -1
    ema_slope_5bar: float = 0.0          # (ema_now - ema_5_bars_ago) / ema_5_bars_ago * 100
    ema_slope_direction: str = "flat"    # "up" | "down" | "flat"

    # Regime classification (Bloco 4 of P0 sprint).
    # Rule: classify the day FIRST. Same setup works in trend, fails in range.
    regime: str = "transition"  # trending_up | trending_down | range | transition | spike

    # Always-in bias COMPUTED (Bloco 5 of P0 sprint).
    # Rule: every moment the market is "always-in" long, short, or transitioning.
    # We compute this from observable evidence rather than asking the LLM to guess.
    computed_always_in: str = "NEUTRO"  # SEMPRE_COMPRADO | SEMPRE_VENDIDO | NEUTRO

    # Failed-attempt / second-entry tracker (Bloco 6 of P0 sprint).
    # Rule: "after a failed breakout, the second attempt succeeds ~60%".
    bars_since_failed_breakout_up: int = -1
    bars_since_failed_breakout_down: int = -1
    second_attempt_long_pending: bool = False
    second_attempt_short_pending: bool = False


@dataclass
class TradeSignal:
    """Output from the Strategy Engine."""
    action: Action
    confidence: int             # 0-100 from LLM
    day_type: DayType
    always_in: AlwaysIn
    setup: SetupType
    signal_bar_quality: SignalBarQuality
    entry_price: float
    stop_loss: float
    take_profit: float
    decisive_layer: int         # 1-5
    reasoning: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ScoreBreakdown:
    score: int
    weight: float
    contribution: float         # score * weight


@dataclass
class DecisionScore:
    total: float
    go: bool
    breakdown: dict             # {"market_quality": ScoreBreakdown, ...}
    threshold: int
    hard_veto: bool
    veto_reason: str = ""


@dataclass
class RiskApproval:
    approved: bool
    position_size: float
    adjusted_stop: float
    adjusted_target: float
    risk_pct: float             # % of capital risked
    reward_risk_ratio: float
    current_drawdown: float
    drawdown_band: DrawdownBand
    regime: Regime
    atr: float
    sharpe_rolling: float
    risk_score: int             # 0-100
    reason: str = ""


@dataclass
class TradeResult:
    intent_id: str
    action: Action
    side: str                   # "buy" | "sell"
    entry_price: float
    exit_price: float
    position_size: float
    pnl: float
    pnl_pct: float
    decision_score: DecisionScore
    entry_time: datetime
    exit_time: datetime
    exit_reason: str            # "stop_loss" | "take_profit" | "timeout" | "manual"
    slippage: float = 0.0

    @property
    def is_win(self) -> bool:
        return self.pnl > 0

    @property
    def age_minutes(self) -> float:
        return (self.exit_time - self.entry_time).total_seconds() / 60


@dataclass
class TradeIntent:
    """ERC-8004 compliant trade intent for signing."""
    intent_id: str
    agent_id: int
    action: str
    symbol: str
    entry_price: float
    stop_loss: float
    take_profit: float
    position_size: float
    decision_score: DecisionScore
    strategy_reasoning: dict
    risk_context: dict
    timestamp: datetime
    signature: str = ""
