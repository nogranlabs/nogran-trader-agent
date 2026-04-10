"""
backtest.py — historical OHLCV backtest do nogran.trader.agent (no-LLM).

Reusa o mesmo pipeline do live (Feature Engine -> Pre-Filter -> KB enrichment
-> AI Overlay -> Risk Engine -> Decision Scorer), substituindo apenas:
  * a fonte de dados (OHLCV histor. via ccxt Kraken, em vez de WebSocket)
  * a strategy engine (heuristica determinista de Nogran PA via simulate_market.py
    em vez de chamar Strategy Engine/GPT — o juiz nao roda LLM)
  * a execucao (PnL simulator com prioridade intrabar stop/target em vez de
    Kraken CLI)

Output:
  logs/backtest/<run_id>/trades.jsonl     — trades executados (1 linha/trade)
  logs/backtest/<run_id>/equity.csv       — equity curve (timestamp, equity, dd)
  logs/backtest/<run_id>/decisions.jsonl  — todas as decisoes (GO + NO-GO)
  logs/backtest/<run_id>/summary.json     — BacktestMetrics serializado
  stdout                                  — sumario formatado

Usage:
  # 30 dias 1m BTC/USD via ccxt Kraken (cacheado em data/historical/)
  python scripts/backtest.py --days 30

  # Usa CSV cacheado se existir
  python scripts/backtest.py --days 7 --no-fetch

  # Modo synthetic (sem rede) — usa generate_pa_phases do simulate_market
  python scripts/backtest.py --source synthetic --candles 500
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ----- imports do projeto (resolvidos via sys.path) -----
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))  # pra reusar simulate_market helpers

from ai.decision_scorer import DecisionScorer  # noqa: E402
from domain.enums import Action, DrawdownBand  # noqa: E402
from domain.models import Candle  # noqa: E402
from infra.config import Config  # noqa: E402
from market.candle_buffer import CandleBuffer  # noqa: E402
from market.feature_engine import FeatureEngine  # noqa: E402
from market.pre_filter import calculate_mq_score  # noqa: E402
from risk.drawdown_controller import DrawdownController  # noqa: E402
# NOTA: ExposureManager do live usa time.time() (wall-clock) pra hourly limit,
# o que NAO funciona em backtest batch (todos os candles processam em <1s).
# Usamos BacktestExposureManager (definida abaixo) que opera em candle-index time.
from risk.position_sizer import PositionSizer  # noqa: E402
from strategy.probabilities_kb import ProbabilitiesKB  # noqa: E402
from strategy.signal_parser import calculate_strategy_score_with_kb  # noqa: E402
from telemetry.backtest_metrics import (  # noqa: E402
    TradeRecord,
    compute_metrics,
    format_metrics,
)

# Reusa as helpers ja testadas do simulate_market.py:
#   - mock_llm_response  : strategy engine no-LLM (Nogran PA heuristics)
#   - mock_regime        : regime detector local
#   - _mock_ao_score     : AI overlay scorer local
#   - generate_pa_phases : synthetic OHLCV para modo --source synthetic
from strategy.local_signal import detect_local_regime, generate_local_signal  # noqa: E402  # v2 PA detectors
from simulate_market import (  # noqa: E402
    _mock_ao_score,
    generate_pa_phases,
    mock_llm_response,
    mock_regime,
)

# Lazy: only constructed when --strategy-source python_llm
_llm_strategy_singleton = None
_llm_provider_name = "openai"  # set by main() before run_backtest
_llm_model_override: Optional[str] = None  # set by main() if --model passed
_llm_use_rag: bool = True  # set by main() if --no-rag passed


def _get_llm_strategy():
    global _llm_strategy_singleton
    if _llm_strategy_singleton is None:
        from strategy.llm_strategy import LLMStrategy, get_default_provider
        provider = get_default_provider(_llm_provider_name)
        if _llm_model_override:
            provider.model = _llm_model_override
        _llm_strategy_singleton = LLMStrategy(provider=provider, use_rag=_llm_use_rag)
    return _llm_strategy_singleton

# ============================================================
# Configs do backtest
# ============================================================

KRAKEN_TAKER_FEE_DEFAULT = 0.0026  # 0.26% — Kraken default taker
KRAKEN_MAKER_FEE_DEFAULT = 0.0016  # 0.16% — Kraken Pro maker
WARMUP_BARS = 25            # candles antes de gerar sinais
MAX_HOLD_BARS = Config.MAX_POSITION_TIME_CANDLES  # default 30


class BacktestExposureManager:
    """Versao do ExposureManager que usa candle-index como tempo (nao wall-clock).

    Live `ExposureManager` chama `time.time()` que num backtest batch processa
    8000+ candles em <1s. Isso fazia o limite hourly disparar apos 4 trades e
    NUNCA mais reabrir, gerando o bug "so 4 trades em 30 dias".

    Esta versao espera receber `bars_per_hour` para converter candles em horas
    (ex: 12 pra 5m timeframe). Mantem mesma API publica do ExposureManager
    original.
    """

    def __init__(self, bars_per_hour: int, max_trades_per_hour: int,
                 cooldown_candles: int):
        self.bars_per_hour = bars_per_hour
        self.max_trades_per_hour = max_trades_per_hour
        self.cooldown_candles = cooldown_candles
        self.has_open_position: bool = False
        self.position_entry_candle: int = 0
        self.last_trade_candle: int = -10_000
        self.trade_candles: list[int] = []  # candle indices of recent trades

    def can_open_position(self, current_candle_index: int) -> tuple[bool, str]:
        if self.has_open_position:
            return False, "Position already open"
        if (current_candle_index - self.last_trade_candle) < self.cooldown_candles:
            return False, "Cooldown"
        # Hourly window: drop trades older than `bars_per_hour` candles
        cutoff = current_candle_index - self.bars_per_hour
        self.trade_candles = [t for t in self.trade_candles if t >= cutoff]
        if len(self.trade_candles) >= self.max_trades_per_hour:
            return False, f"Max {self.max_trades_per_hour} trades/hour"
        return True, "OK"

    def on_position_opened(self, candle_index: int):
        self.has_open_position = True
        self.position_entry_candle = candle_index
        self.trade_candles.append(candle_index)

    def on_position_closed(self, candle_index: int):
        self.has_open_position = False
        self.last_trade_candle = candle_index

    def should_force_close(self, current_candle_index: int, max_hold: int) -> bool:
        if not self.has_open_position:
            return False
        return (current_candle_index - self.position_entry_candle) >= max_hold


# Bars-per-hour por timeframe (pro BacktestExposureManager)
BARS_PER_HOUR_BY_TIMEFRAME = {
    "1m": 60, "5m": 12, "15m": 4, "1h": 1, "4h": 1, "1d": 1,
}


class BiasTracker:
    """Anti-bias direcional pra contrabalancar o long-bias do LLM.

    Empirico: em v1.5 2880c, dos 12 trades executados 12 foram LONG (100%) num
    periodo de BTC oscilando. O LLM tem bias bullish embedded (BTC sempre subiu
    nos dados de treino). Esse tracker conta as ultimas N decisoes executadas
    e veta a proxima na mesma direcao quando o ratio passa do limite.

    Logica:
        - Mantem janela das ultimas N direcoes (long/short)
        - Se >=max_ratio da janela e da mesma direcao, veta proxima na mesma
        - Janela so comeca a vetar depois de cheia (warmup)
    """

    def __init__(self, window_size: int = 5, max_ratio: float = 0.8):
        self.window_size = window_size
        self.max_ratio = max_ratio
        self.recent: list[str] = []  # "long" | "short"

    def record(self, direction: str) -> None:
        if direction not in ("long", "short"):
            return
        self.recent.append(direction)
        if len(self.recent) > self.window_size:
            self.recent.pop(0)

    def can_take(self, direction: str) -> tuple[bool, str]:
        """Retorna (allowed, reason). Warmup permite tudo ate janela cheia."""
        if direction not in ("long", "short"):
            return True, "non-directional"
        if len(self.recent) < self.window_size:
            return True, "warmup"
        same = sum(1 for d in self.recent if d == direction)
        ratio = same / len(self.recent)
        if ratio >= self.max_ratio:
            return False, f"bias: {same}/{len(self.recent)} recent {direction}"
        return True, "ok"


@dataclass
class TuningParams:
    """Parametros tunaveis sem mutar Config (CLAUDE.md proibe)."""
    rr_min: float = Config.MIN_REWARD_RISK         # default 1.5
    atr_stop_mult: float = Config.ATR_STOP_MULTIPLIER  # default 1.5
    mq_threshold: int = 50                          # default pre-filter veto (raised from 30 — old value was a no-op)
    decision_threshold: int = Config.DECISION_THRESHOLD  # default 65
    peak_only: bool = False                         # se True, opera so em UTC 13:30-21:00
    fee_pct: float = KRAKEN_TAKER_FEE_DEFAULT       # round-trip por lado
    max_leverage: float = 1.0                       # cap notional / capital
    strategy_source: str = "mock"                   # "mock" | "python_llm"
    require_kb_match: bool = True                   # veto trades sem PA KB match (anti-hallucination)
    veto_hallucination: bool = True                 # veto trades com alarm warning/critical do KB
    # 2026-04-09: bias_window default 5 → 0 (disabled). The anti-bias rule is
    # NOT Nogran PA-native — the rule states "trade WITH the trend", and 100% long
    # in a confirmed bull trend is correct, not a bias to fight. The tracker
    # is kept as a code path so we can re-enable it via --bias-window N when
    # combined with multi-TF confirmation (#63), but it is OFF by default.
    bias_window: int = 0                            # tamanho da janela do BiasTracker (0 = desabilitado)
    bias_max_ratio: float = 0.8                     # >= esse ratio na mesma direcao = veto
    # KB diagnostic flags (added 2026-04-09 for the post-hoc 3-test analysis)
    no_kb_blend: bool = False                       # Test #1: skip KB enrichment entirely (LLM solo)
    halu_threshold: int | None = None               # Test #2: override hallucination gap threshold (default 25)
    clamp_kb_prob: int | None = None                # Test #3: clamp every KB probability to <= this value
    breakeven_enabled: bool = True                  # mover stop pra entry quando price atinge trigger_rr * risco
    breakeven_trigger_rr: float = 1.5               # RR at which the stop ratchets to entry+buffer.
                                                    # 2026-04-09 (Fix #2): bumped 1.0 → 1.5 after the
                                                    # paid 10d Window C run. Trade #4 reached 1R, BE
                                                    # ratcheted to entry+0.1R, then price retraced and
                                                    # stopped at +0.5R instead of timing out at +0.83R.
                                                    # Bumping the trigger to 1.5R means BE only fires on
                                                    # trades that already have a meaningful cushion.

# Bars-per-year pra anualizacao Sharpe/Sortino
BARS_PER_YEAR_BY_TIMEFRAME = {
    "1m": 525_600,
    "5m": 105_120,
    "15m": 35_040,
    "1h": 8_760,
    "4h": 2_190,
    "1d": 365,
}


# ============================================================
# Posicao aberta (estado simulado)
# ============================================================


@dataclass
class OpenPosition:
    side: str                # "long" | "short"
    entry_index: int
    entry_time: int          # ms
    entry_price: float
    stop_loss: float
    take_profit: float
    size: float              # BTC units
    decision_score: float
    mq: int
    ss: int
    ao: int
    rs: int
    kb_match_id: Optional[str] = None
    hallucination_severity: Optional[str] = None
    fees_in: float = 0.0
    # 2026-04-09 — for breakeven move (#64). original_stop is preserved so
    # rr_realized still uses the true risk denominator after the stop has
    # been ratcheted to entry. breakeven_moved prevents redundant moves.
    original_stop_loss: float = 0.0
    breakeven_moved: bool = False
    # Fix A (2026-04-09): trail stop ratchet level. After the BE move at 1.0R,
    # the stop is ratcheted upward at 1.5R, 2.0R, 2.5R to lock progressive
    # profit. Each level fires at most once per trade.
    trail_level: int = 0   # 0 = no trail, 1 = 1.5R locked, 2 = 2.0R locked, etc.


@dataclass
class ClosedTrade:
    side: str
    entry_index: int
    exit_index: int
    entry_time: int
    exit_time: int
    entry_price: float
    exit_price: float
    size: float
    pnl: float
    pnl_pct: float
    fees: float
    rr_realized: float
    exit_reason: str         # "stop_loss" | "take_profit" | "timeout"
    decision_score: float
    mq: int
    ss: int
    ao: int
    rs: int
    kb_match_id: Optional[str] = None
    hallucination_severity: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================================
# Data source (ccxt Kraken / CSV cache / synthetic)
# ============================================================


def _data_dir() -> Path:
    d = ROOT / "data" / "historical"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_path(symbol: str, timeframe: str, days: int) -> Path:
    safe = symbol.replace("/", "_")
    return _data_dir() / f"{safe}_{timeframe}_{days}d.csv"


def _cache_path_ex(exchange_id: str, symbol: str, timeframe: str, days: int) -> Path:
    safe = symbol.replace("/", "_")
    return _data_dir() / f"{exchange_id}_{safe}_{timeframe}_{days}d.csv"


def fetch_ohlcv_ccxt(symbol: str, timeframe: str, days: int,
                     exchange_id: str = "kraken") -> list[Candle]:
    """Pagina ccxt para OHLCV historico. Cacheia em CSV.

    exchange_id:
      - 'kraken'  → Kraken REST (limitado a 720 candles, sem pagination real)
      - 'binance' → Binance public REST (pagination forward funciona ate ~1000 candles/req,
                    cobre meses sem problema). Symbol deve ser 'BTC/USDT' (nao USD).
    """
    import ccxt  # type: ignore

    cache = _cache_path_ex(exchange_id, symbol, timeframe, days)
    print(f"Fetching {days}d {timeframe} {symbol} via ccxt {exchange_id}...")
    exchange_class = getattr(ccxt, exchange_id)
    exchange = exchange_class({"enableRateLimit": True})
    tf_ms = exchange.parse_timeframe(timeframe) * 1000
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - days * 24 * 60 * 60 * 1000

    # Binance suporta limit=1000, Kraken so 720
    chunk_limit = 1000 if exchange_id == "binance" else 720

    rows: list[list] = []
    since = start_ms
    safety_iter = 0
    while since < end_ms and safety_iter < 1000:
        safety_iter += 1
        try:
            chunk = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=chunk_limit)
        except Exception as e:
            print(f"  ccxt fetch failed at since={since}: {e}")
            break
        if not chunk:
            break
        rows.extend(chunk)
        last_ts = chunk[-1][0]
        if last_ts <= since:
            break
        since = last_ts + tf_ms
        if len(chunk) < chunk_limit:
            # got less than asked → caught up to live, stop
            break
        time.sleep(exchange.rateLimit / 1000.0)

    # De-duplicate by timestamp (Kraken sometimes returns overlap)
    seen = set()
    deduped = []
    for r in rows:
        if r[0] not in seen:
            seen.add(r[0])
            deduped.append(r)
    rows = deduped

    # Persist CSV cache
    with open(cache, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for r in rows:
            w.writerow(r)
    print(f"  fetched {len(rows)} candles -> cached at {cache}")
    return _rows_to_candles(rows)


def load_ohlcv_csv(symbol: str, timeframe: str, days: int,
                   exchange_id: str = "kraken") -> list[Candle]:
    cache = _cache_path_ex(exchange_id, symbol, timeframe, days)
    if not cache.exists():
        # backward-compat: try old path without exchange prefix
        legacy = _cache_path(symbol, timeframe, days)
        if legacy.exists():
            cache = legacy
        else:
            raise FileNotFoundError(f"No CSV cache at {cache}. Run without --no-fetch to download.")
    rows = []
    with open(cache, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)  # header
        for r in reader:
            rows.append([int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])])
    print(f"Loaded {len(rows)} cached candles from {cache}")
    return _rows_to_candles(rows)


def _rows_to_candles(rows: list[list]) -> list[Candle]:
    return [
        Candle(
            timestamp=int(r[0]),
            open=float(r[1]),
            high=float(r[2]),
            low=float(r[3]),
            close=float(r[4]),
            volume=float(r[5]),
        )
        for r in rows
    ]


# ============================================================
# PnL simulator — intrabar stop/target priority
# ============================================================


def _check_exit(pos: OpenPosition, candle: Candle) -> Optional[tuple[float, str]]:
    """Verifica se a posicao deve fechar nesta barra.

    Convencao conservadora: se a barra cobre stop E target ao mesmo tempo,
    assumimos que o STOP foi atingido primeiro (worst-case). Isso evita inflar
    artificialmente o PnL.

    Retorna (exit_price, exit_reason) ou None se posicao continua aberta.
    """
    if pos.side == "long":
        hit_stop = candle.low <= pos.stop_loss
        hit_target = candle.high >= pos.take_profit
        if hit_stop:
            return pos.stop_loss, "stop_loss"
        if hit_target:
            return pos.take_profit, "take_profit"
    else:  # short
        hit_stop = candle.high >= pos.stop_loss
        hit_target = candle.low <= pos.take_profit
        if hit_stop:
            return pos.stop_loss, "stop_loss"
        if hit_target:
            return pos.take_profit, "take_profit"
    return None


def _maybe_move_to_breakeven(pos: OpenPosition, candle: Candle,
                             trigger_rr: float = 1.0) -> bool:
    """Move stop pra entry quando price alcanca trigger_rr * risco original.

    core rule: "once the trade is paying you, dont let it pay you back".
    Empirico v1.8 2880c: asimetria win/loss ja era 1.04x mas WR 20% deixava
    expectativa negativa. Breakeven converte muitos losses em $0 fees-only,
    melhorando expectativa mesmo com WR baixo.

    Retorna True se moveu (idempotente — so move uma vez por trade).
    """
    if pos.breakeven_moved:
        return False
    if pos.original_stop_loss == 0.0:
        return False
    risk = abs(pos.entry_price - pos.original_stop_loss)
    if risk <= 0:
        return False

    # F1 fix (c): usar buffer +0.1R em vez de breakeven exato.
    # Empirical (4 walk-forwards, n=38, 2026-04-09): 5/13 BE-traps observados
    # eram multi-bar com exit_price == entry_price exato — o stop foi ratched
    # pra entry e o ricochete normal do candle bate o stop pelo low/high.
    # Buffer de 0.1R em preço dá folga ao movimento natural, ainda protegendo
    # contra reversões maiores que 0.1R abaixo de entry.
    BREAKEVEN_BUFFER_RR = 0.1
    buffer = risk * BREAKEVEN_BUFFER_RR  # `risk` está em preço/unidade

    if pos.side == "long":
        trigger_price = pos.entry_price + risk * trigger_rr
        if candle.high >= trigger_price:
            pos.stop_loss = pos.entry_price + buffer
            pos.breakeven_moved = True
            return True
    else:  # short
        trigger_price = pos.entry_price - risk * trigger_rr
        if candle.low <= trigger_price:
            pos.stop_loss = pos.entry_price - buffer
            pos.breakeven_moved = True
            return True
    return False


# Fix A (Trail stop): after the breakeven move at 1.0R, ratchet the stop up
# at fixed RR levels to progressively lock in profit. This captures the
# scenario from r1_full_C_d60_90 where positions reached partial profit
# (e.g. 0.83R on trade #4) but then drifted back to entry and timed out.
# A trail at 0.5R lock would have exited that trade in profit.
TRAIL_LEVELS = [
    # (trigger_rr, lock_rr) — fired in order, each at most once
    (1.5, 0.5),
    (2.0, 1.0),
    (2.5, 1.5),
]


def _maybe_trail_stop(pos: OpenPosition, candle: Candle) -> bool:
    """Ratchet stop upward through TRAIL_LEVELS once breakeven has fired.

    Returns True if the stop was moved this candle.
    """
    if not pos.breakeven_moved:
        return False
    if pos.original_stop_loss == 0.0:
        return False
    risk = abs(pos.entry_price - pos.original_stop_loss)
    if risk <= 0:
        return False

    # Walk through any trail levels above the current pos.trail_level
    moved = False
    for level_idx, (trigger_rr, lock_rr) in enumerate(TRAIL_LEVELS, start=1):
        if pos.trail_level >= level_idx:
            continue  # already locked this level
        if pos.side == "long":
            trigger_price = pos.entry_price + risk * trigger_rr
            if candle.high >= trigger_price:
                new_stop = pos.entry_price + risk * lock_rr
                if new_stop > pos.stop_loss:
                    pos.stop_loss = new_stop
                    pos.trail_level = level_idx
                    moved = True
                    continue
            break  # didn't reach this level, won't reach higher ones
        else:  # short
            trigger_price = pos.entry_price - risk * trigger_rr
            if candle.low <= trigger_price:
                new_stop = pos.entry_price - risk * lock_rr
                if new_stop < pos.stop_loss:
                    pos.stop_loss = new_stop
                    pos.trail_level = level_idx
                    moved = True
                    continue
            break

    return moved


def _close_position(pos: OpenPosition, exit_price: float, exit_reason: str,
                    exit_index: int, exit_time: int, fee_pct: float) -> ClosedTrade:
    fee_out = exit_price * pos.size * fee_pct
    fees = pos.fees_in + fee_out
    # Risk MUST come from the original stop, not the (possibly ratcheted) current
    # stop. Otherwise breakeven-moved trades report risk=0 → rr_realized = inf.
    stop_for_risk = pos.original_stop_loss if pos.original_stop_loss != 0.0 else pos.stop_loss
    if pos.side == "long":
        gross_pnl = (exit_price - pos.entry_price) * pos.size
        risk = (pos.entry_price - stop_for_risk) * pos.size
    else:
        gross_pnl = (pos.entry_price - exit_price) * pos.size
        risk = (stop_for_risk - pos.entry_price) * pos.size
    net_pnl = gross_pnl - fees
    notional = pos.entry_price * pos.size
    pnl_pct = net_pnl / notional if notional > 0 else 0.0
    rr_realized = (gross_pnl / risk) if risk > 0 else 0.0
    return ClosedTrade(
        side=pos.side,
        entry_index=pos.entry_index,
        exit_index=exit_index,
        entry_time=pos.entry_time,
        exit_time=exit_time,
        entry_price=pos.entry_price,
        exit_price=exit_price,
        size=pos.size,
        pnl=net_pnl,
        pnl_pct=pnl_pct,
        fees=fees,
        rr_realized=rr_realized,
        exit_reason=exit_reason,
        decision_score=pos.decision_score,
        mq=pos.mq,
        ss=pos.ss,
        ao=pos.ao,
        rs=pos.rs,
        kb_match_id=pos.kb_match_id,
        hallucination_severity=pos.hallucination_severity,
    )


# ============================================================
# Engine state container (replaces RiskMetrics for backtest scope)
# ============================================================


@dataclass
class EngineState:
    initial_capital: float
    capital: float
    equity_curve: list[float] = field(default_factory=list)
    equity_timestamps: list[int] = field(default_factory=list)
    closed_trades: list[ClosedTrade] = field(default_factory=list)
    open_position: Optional[OpenPosition] = None

    @property
    def peak_equity(self) -> float:
        return max(self.equity_curve) if self.equity_curve else self.initial_capital

    @property
    def current_drawdown(self) -> float:
        peak = self.peak_equity
        return 1.0 - (self.capital / peak) if peak > 0 else 0.0

    def record_equity(self, ts: int):
        self.equity_curve.append(self.capital)
        self.equity_timestamps.append(ts)


# ============================================================
# Risk score local (sem RiskMetrics — usa EngineState)
# ============================================================


def _compute_risk_score(state: EngineState, signal, dd_controller: DrawdownController,
                        rr_min: float, trust_llm_rr: bool = False) -> int:
    """Versao simplificada de calculate_risk_score que usa EngineState
    em vez de RiskMetrics. Mantem mesmo espirito do main.py:74-114.

    `trust_llm_rr`: when True, skip the rr_min filter. Used for python_llm mode
    where the LLM has chosen its own stop/target based on Nogran PA structure
    (e.g., shaved_bar scalps with 1:1 RR are valid Nogran PA setups).
    """
    if signal.stop_loss == 0:
        return 0
    # R/R check
    if signal.action == Action.COMPRA:
        risk = signal.entry_price - signal.stop_loss
        reward = signal.take_profit - signal.entry_price
    elif signal.action == Action.VENDA:
        risk = signal.stop_loss - signal.entry_price
        reward = signal.entry_price - signal.take_profit
    else:
        return 0
    if risk <= 0:
        return 0
    rr = reward / risk
    if not trust_llm_rr and rr < rr_min:
        return 0

    band = dd_controller.get_band(state.current_drawdown)
    band_score = {
        DrawdownBand.NORMAL: 80,
        DrawdownBand.DEFENSIVE: 50,
        DrawdownBand.MINIMUM: 25,
        DrawdownBand.CIRCUIT_BREAKER: 5,
    }[band]

    rr_bonus = min(20, int((rr - 1.5) * 10))
    return max(0, min(100, band_score + rr_bonus))


# ============================================================
# Position sizing simplificado (sem RiskMetrics)
# ============================================================


def _compute_position_size(state: EngineState, atr: float, entry_price: float,
                           decision_score_total: float,
                           dd_controller: DrawdownController,
                           atr_stop_mult: float,
                           max_leverage: float = 1.0,
                           explicit_stop_distance: float = 0.0) -> float:
    """Sizing baseado em risco-por-trade com hard cap de leverage.

    Sem o cap, com ATR pequeno (chop) o stop_distance fica tiny e o sizing
    via risk_dollars/stop_distance explode em multiplos do capital. O cap
    notional = capital * max_leverage garante que nenhum trade seja maior
    que o caixa disponivel (default 1x = sem leverage).

    `explicit_stop_distance`: if > 0, use this as the stop distance instead
    of computing atr * atr_stop_mult. Used by python_llm path where the LLM
    chose a structure-based stop, not a mechanical ATR multiple.
    """
    if entry_price <= 0:
        return 0.0
    if explicit_stop_distance > 0:
        stop_distance = explicit_stop_distance
    elif atr > 0:
        stop_distance = atr * atr_stop_mult
    else:
        return 0.0
    if stop_distance <= 0:
        return 0.0
    risk_dollars = state.capital * Config.RISK_PER_TRADE
    # score multiplier (65->0.6 .. 95->1.0)
    s = max(65.0, min(95.0, decision_score_total))
    score_mult = 0.6 + (s - 65) * (0.4 / 30)
    band = dd_controller.get_band(state.current_drawdown)
    dd_mult = dd_controller.get_sizing_multiplier(band)
    base_size = risk_dollars / stop_distance
    size = base_size * score_mult * dd_mult
    # Hard cap: notional <= capital * max_leverage
    max_size_by_notional = (state.capital * max_leverage) / entry_price
    size = min(size, max_size_by_notional)
    return max(0.0001, size)


# ============================================================
# Output writers
# ============================================================


class BacktestWriter:
    def __init__(self, out_dir: Path):
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.decisions_path = out_dir / "decisions.jsonl"
        self.trades_path = out_dir / "trades.jsonl"
        self.equity_path = out_dir / "equity.csv"
        self.summary_path = out_dir / "summary.json"
        # truncate
        for p in (self.decisions_path, self.trades_path):
            p.write_text("", encoding="utf-8")

    def log_decision(self, entry: dict):
        with open(self.decisions_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def log_trade(self, trade: ClosedTrade):
        with open(self.trades_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(trade.to_dict(), ensure_ascii=False) + "\n")

    def write_equity(self, curve: list[float], timestamps: list[int]):
        with open(self.equity_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["timestamp", "equity", "drawdown"])
            peak = curve[0] if curve else 0.0
            for ts, eq in zip(timestamps, curve):
                peak = max(peak, eq)
                dd = 1 - eq / peak if peak > 0 else 0.0
                w.writerow([ts, f"{eq:.4f}", f"{dd:.6f}"])

    def write_summary(self, summary: dict):
        with open(self.summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)


# ============================================================
# Main backtest loop
# ============================================================


def run_backtest(
    candles: list[Candle],
    initial_capital: float,
    timeframe: str,
    out_dir: Path,
    tuning: Optional[TuningParams] = None,
) -> dict:
    if tuning is None:
        tuning = TuningParams()
    if len(candles) < WARMUP_BARS + 5:
        raise ValueError(f"Not enough candles: {len(candles)} (need >= {WARMUP_BARS + 5})")

    # Pipeline modules
    feature_engine = FeatureEngine()
    buf_1m = CandleBuffer(maxlen=200)
    decision_scorer = DecisionScorer()
    kb = ProbabilitiesKB(
        clamp_max_pct=tuning.clamp_kb_prob,
        hallucination_threshold=tuning.halu_threshold,
    )
    dd_controller = DrawdownController()
    bars_per_hour = BARS_PER_HOUR_BY_TIMEFRAME.get(timeframe, 12)
    exposure_mgr = BacktestExposureManager(
        bars_per_hour=bars_per_hour,
        max_trades_per_hour=Config.MAX_TRADES_PER_HOUR,
        cooldown_candles=Config.COOLDOWN_CANDLES,
    )
    bias_tracker = BiasTracker(
        window_size=tuning.bias_window,
        max_ratio=tuning.bias_max_ratio,
    )

    state = EngineState(initial_capital=initial_capital, capital=initial_capital)
    # Equity curve is recorded inside the loop; do NOT pre-seed (avoids duplicate t0).

    writer = BacktestWriter(out_dir)
    stats = {
        "total_decisions": 0,
        "go": 0,
        "no_go": 0,
        "vetoes_pre_filter": 0,
        "vetoes_risk": 0,
        "alarms": 0,
        "executed_trades": 0,
    }

    for idx, candle in enumerate(candles):
        buf_1m.add(candle)

        # ----- Manage open position FIRST (intrabar exit) -----
        if state.open_position is not None:
            pos = state.open_position
            # Try to ratchet stop to breakeven BEFORE checking exit. If price
            # has moved 1R in our favor this bar, the stop is now at entry,
            # so a subsequent reversal at most yields a fees-only loss.
            # F1 fix (a): não ratchet pra breakeven no MESMO candle de entrada.
            # Empirical (4 walk-forwards, n=38, 2026-04-09): 8/13 BE-traps observados
            # eram same-bar — o range do bar de entrada cobria 1R favorável e voltava
            # no mesmo bar, fechando como fees-only loss (~21% do prejuízo agregado).
            if tuning.breakeven_enabled and pos.entry_index != idx:
                if _maybe_move_to_breakeven(pos, candle, tuning.breakeven_trigger_rr):
                    stats["breakeven_moves"] = stats.get("breakeven_moves", 0) + 1
                # Fix A: trail stop after breakeven — ratchet at 1.5R/2.0R/2.5R
                if _maybe_trail_stop(pos, candle):
                    stats["trail_moves"] = stats.get("trail_moves", 0) + 1
            exit_check = _check_exit(pos, candle)
            forced_timeout = (idx - pos.entry_index) >= MAX_HOLD_BARS
            if exit_check is not None:
                exit_price, reason = exit_check
                trade = _close_position(pos, exit_price, reason, idx, candle.timestamp, tuning.fee_pct)
                state.capital += trade.pnl
                state.closed_trades.append(trade)
                state.open_position = None
                exposure_mgr.on_position_closed(idx)
                writer.log_trade(trade)
            elif forced_timeout:
                trade = _close_position(pos, candle.close, "timeout", idx, candle.timestamp, tuning.fee_pct)
                state.capital += trade.pnl
                state.closed_trades.append(trade)
                state.open_position = None
                exposure_mgr.on_position_closed(idx)
                writer.log_trade(trade)

        state.record_equity(candle.timestamp)

        # ----- Warmup -----
        if idx < WARMUP_BARS:
            continue

        features = feature_engine.compute(buf_1m, candle_index=idx)
        if features is None:
            continue

        stats["total_decisions"] += 1

        # ----- Stage 0: peak-session gate (opcional) -----
        if tuning.peak_only and not features.is_peak_session:
            continue

        # ----- Stage 1: pre-filter -----
        mq_score = calculate_mq_score(features)
        if mq_score < tuning.mq_threshold:
            stats["vetoes_pre_filter"] += 1
            stats["no_go"] += 1
            writer.log_decision({
                "candle_index": idx,
                "timestamp": candle.timestamp,
                "veto": "pre_filter",
                "mq": mq_score,
            })
            continue

        # ----- Stage 2: exposure check -----
        can_open, _reason = exposure_mgr.can_open_position(idx)
        if not can_open:
            # Nao loga como veto (so cooldown/exposure), continua observando
            continue

        # ----- Stage 3: regime + signal -----
        regime = mock_regime(features)

        if tuning.strategy_source == "python_llm":
            # Pre-filter via mock heuristic — only call LLM if mock detects a candidate.
            # the rule states: trade 3-5% of bars. Most candles are AGUARDAR.
            # Calling LLM for all candles wastes ~95% of cost on obvious AGUARDAR.
            # Mock heuristic catches "obvious AGUARDAR" cases (range, no setup) for free.
            mock_signal = generate_local_signal(features, regime,
                                               strict_trend_alignment=True)
            if mock_signal.action == Action.AGUARDAR:
                # Mock says no candidate → skip LLM, save cost
                stats["pre_filter_skip"] = stats.get("pre_filter_skip", 0) + 1
                stats["no_go"] += 1
                continue

            # Mock detected a candidate → call LLM to verify with full PA RAG
            try:
                signal = _get_llm_strategy().ask(features)
                if signal is None:
                    stats["no_go"] += 1
                    continue
                stats["llm_calls"] = stats.get("llm_calls", 0) + 1
            except Exception as e:
                # First call may fail (no API key, etc) — log once and bail
                if stats.get("llm_errors", 0) == 0:
                    print(f"WARNING: LLM call failed ({e}). Set OPENAI_API_KEY in .env.")
                stats["llm_errors"] = stats.get("llm_errors", 0) + 1
                stats["no_go"] += 1
                continue
        else:
            signal = generate_local_signal(features, regime,
                                         strict_trend_alignment=True)

        if signal.action == Action.AGUARDAR:
            stats["no_go"] += 1
            writer.log_decision({
                "candle_index": idx,
                "timestamp": candle.timestamp,
                "veto": "aguardar",
                "mq": mq_score,
            })
            continue

        # ----- Fix D: HTF (1h) directional veto -----
        # Block trades that fight the 1h trend. Diagnosis from r1_full_C_d60_90:
        # 10/12 trades were LONG in a bear period because the LLM ignored the
        # tf_1h_direction='down' field in the prompt. Enforce in code.
        # Only veto when the HTF reading is available (early bars have None).
        htf_dir = features.tf_1h_direction
        if htf_dir is not None:
            if signal.action == Action.COMPRA and htf_dir == "down":
                stats["htf_vetoes"] = stats.get("htf_vetoes", 0) + 1
                stats["no_go"] += 1
                writer.log_decision({
                    "candle_index": idx,
                    "timestamp": candle.timestamp,
                    "veto": "htf_long_in_downtrend",
                    "mq": mq_score,
                })
                continue
            if signal.action == Action.VENDA and htf_dir == "up":
                stats["htf_vetoes"] = stats.get("htf_vetoes", 0) + 1
                stats["no_go"] += 1
                writer.log_decision({
                    "candle_index": idx,
                    "timestamp": candle.timestamp,
                    "veto": "htf_short_in_uptrend",
                    "mq": mq_score,
                })
                continue

        # Stop/target strategy:
        # - V2 detectors (local_signal.py) set structural stops (at swing
        #   low/high) and measured-move targets. Trust them.
        # - Only fall back to ATR override if the signal has placeholder
        #   stop/target (both == entry = detector returned AGUARDAR-like
        #   prices). This shouldn't happen but is defensive.
        if tuning.strategy_source == "mock":
            stop_ok = abs(signal.stop_loss - signal.entry_price) > 1e-6
            target_ok = abs(signal.take_profit - signal.entry_price) > 1e-6
            if not stop_ok or not target_ok:
                # Detector returned degenerate stop/target — fall back to ATR
                stop_dist_pre = features.atr_14 * tuning.atr_stop_mult
                target_dist_pre = stop_dist_pre * tuning.rr_min
                if signal.action == Action.COMPRA:
                    signal.stop_loss = candle.close - stop_dist_pre
                    signal.take_profit = candle.close + target_dist_pre
                elif signal.action == Action.VENDA:
                    signal.stop_loss = candle.close + stop_dist_pre
                    signal.take_profit = candle.close - target_dist_pre
        # else (python_llm): trust LLM stop/target as returned

        # ----- Stage 4: KB enrichment + hallucination detector -----
        # Test #1 (no_kb_blend): pass kb=None to skip blend entirely (LLM solo)
        enriched = calculate_strategy_score_with_kb(
            signal,
            kb=None if tuning.no_kb_blend else kb,
        )
        ss_score = enriched.blended_score
        if enriched.alarm:
            stats["alarms"] += 1

        # ----- Stage 4.5: KB match hard veto -----
        # Empirical: in v1.4 backtest, trades without kb_match lost 7/9 (~$500 of $475 net loss).
        # If LLM proposes a setup the PA KB cannot match, treat it as hallucinated and skip.
        if tuning.require_kb_match and enriched.match is None:
            stats["vetoes_no_kb"] = stats.get("vetoes_no_kb", 0) + 1
            stats["no_go"] += 1
            writer.log_decision({
                "candle_index": idx,
                "timestamp": candle.timestamp,
                "veto": "no_kb_match",
                "action": signal.action.value,
                "setup": signal.setup.value,
                "mq": mq_score,
                "ss": ss_score,
            })
            continue

        # ----- Stage 4.55: Anti-bias direcional -----
        # Empirical: in v1.5 2880c, 12 of 12 trades were LONG. LLM has bullish
        # bias embedded. BiasTracker veta trades quando a janela recente esta
        # dominada por uma direcao. Set bias_window=0 to disable.
        if tuning.bias_window > 0 and signal.action != Action.AGUARDAR:
            direction = "long" if signal.action == Action.COMPRA else "short"
            ok, reason = bias_tracker.can_take(direction)
            if not ok:
                stats["vetoes_bias"] = stats.get("vetoes_bias", 0) + 1
                stats["no_go"] += 1
                writer.log_decision({
                    "candle_index": idx,
                    "timestamp": candle.timestamp,
                    "veto": "directional_bias",
                    "reason": reason,
                    "action": signal.action.value,
                    "mq": mq_score,
                    "ss": ss_score,
                })
                continue

        # ----- Stage 4.6: Hallucination hard veto -----
        # Only veto on CRITICAL severity (gap >= 40), not warning (gap >= 25).
        # Empirical: LLMs inflate confidence ~15-25 points systematically over Nogran PA
        # baseline probabilities (e.g. high_2_pullback_ma_bull = 60% in KB, LLM returns
        # 75-85). That puts almost every trade into "warning". Vetoing warning kills
        # 11 of 12 trades. "Critical" (gap >= 40) signals genuine disagreement worth
        # blocking. Toggle: --allow-hallucination disables both.
        if (tuning.veto_hallucination and enriched.alarm is not None
                and enriched.alarm.severity == "critical"):
            stats["vetoes_hallucination"] = stats.get("vetoes_hallucination", 0) + 1
            stats["no_go"] += 1
            writer.log_decision({
                "candle_index": idx,
                "timestamp": candle.timestamp,
                "veto": "hallucination",
                "severity": enriched.alarm.severity,
                "action": signal.action.value,
                "setup": signal.setup.value,
                "mq": mq_score,
                "ss": ss_score,
            })
            continue

        # ----- Stage 5: AI overlay -----
        ao_score = _mock_ao_score(regime, signal, features)

        # ----- Stage 6: risk score -----
        # F2/F3 fix: sempre validar RR. trust_llm_rr=True estava pulando o check
        # inteiro e fazendo `vetoes_risk` ser 0 em 4/4 walk-forwards (11.4k
        # decisoes, 0 vetos). RS virou folclore — sempre 80+ no path LLM. A LLM
        # hard guard MIN_RR_RATIO=1.0 em llm_strategy.py continua como floor
        # independente; o tuning.rr_min=1.5 do backtest agora e o real piso.
        rs_score = _compute_risk_score(state, signal, dd_controller, tuning.rr_min,
                                       trust_llm_rr=False)
        if rs_score == 0:
            stats["vetoes_risk"] += 1
            stats["no_go"] += 1
            writer.log_decision({
                "candle_index": idx,
                "timestamp": candle.timestamp,
                "veto": "risk",
                "mq": mq_score,
                "ss": ss_score,
                "ao": ao_score,
                "rs": rs_score,
            })
            continue

        # ----- Stage 7: decision score -----
        decision = decision_scorer.calculate(mq_score, ss_score, ao_score, rs_score)

        decision_entry = {
            "candle_index": idx,
            "timestamp": candle.timestamp,
            "mq": mq_score,
            "ss": ss_score,
            "ao": ao_score,
            "rs": rs_score,
            "total": decision.total,
            "go": decision.go,
            "hard_veto": decision.hard_veto,
            "veto_reason": decision.veto_reason,
            "action": signal.action.value,
            "setup": signal.setup.value,
            "kb_match": enriched.match.setup_id if enriched.match else None,
            "hallucination_alarm": enriched.alarm.severity if enriched.alarm else None,
        }
        writer.log_decision(decision_entry)

        if not decision.go:
            stats["no_go"] += 1
            continue

        stats["go"] += 1

        # ----- Stage 8: open position (entry at NEXT bar's open to avoid lookahead) -----
        if idx + 1 >= len(candles):
            break  # nao da pra abrir no ultimo bar
        next_candle = candles[idx + 1]
        entry_price = next_candle.open

        # For LLM signals, use the LLM's actual stop distance (Nogran PA structure-based)
        # so position size is based on TRUE risk, not mechanical ATR.
        explicit_stop_dist = 0.0
        if tuning.strategy_source != "mock":
            if signal.action == Action.COMPRA:
                explicit_stop_dist = signal.entry_price - signal.stop_loss
            else:
                explicit_stop_dist = signal.stop_loss - signal.entry_price
            if explicit_stop_dist <= 0:
                # LLM gave invalid stop — fall back to ATR-based
                explicit_stop_dist = 0.0

        size = _compute_position_size(state, features.atr_14, entry_price,
                                      decision.total, dd_controller,
                                      atr_stop_mult=tuning.atr_stop_mult,
                                      max_leverage=tuning.max_leverage,
                                      explicit_stop_distance=explicit_stop_dist)
        if size <= 0:
            continue

        # Stop/target placement:
        # - mock: ATR-mechanical, recomputed around entry_price (slippage adjust)
        # - python_llm: trust LLM's stop/target (Nogran PA structure-based).
        #   Adjust ONLY for the slippage between signal close and next-bar open
        #   by translating the entire stop/target relative to that delta.
        if tuning.strategy_source == "mock":
            stop_dist = features.atr_14 * tuning.atr_stop_mult
            target_dist = stop_dist * tuning.rr_min
            if signal.action == Action.COMPRA:
                stop = entry_price - stop_dist
                target = entry_price + target_dist
                side = "long"
            else:
                stop = entry_price + stop_dist
                target = entry_price - target_dist
                side = "short"
        else:
            # python_llm: trust LLM's stop/target. Slip both by next-bar gap.
            slip = entry_price - signal.entry_price
            stop = signal.stop_loss + slip
            target = signal.take_profit + slip
            side = "long" if signal.action == Action.COMPRA else "short"

        fee_in = entry_price * size * tuning.fee_pct
        state.open_position = OpenPosition(
            side=side,
            entry_index=idx + 1,
            entry_time=next_candle.timestamp,
            entry_price=entry_price,
            stop_loss=stop,
            take_profit=target,
            size=size,
            decision_score=decision.total,
            mq=mq_score,
            ss=ss_score,
            ao=ao_score,
            rs=rs_score,
            kb_match_id=enriched.match.setup_id if enriched.match else None,
            hallucination_severity=enriched.alarm.severity if enriched.alarm else None,
            fees_in=fee_in,
            original_stop_loss=stop,  # frozen for risk-denominator after breakeven move
        )
        exposure_mgr.on_position_opened(idx + 1)
        bias_tracker.record(side)  # "long" | "short"
        stats["executed_trades"] += 1

    # Force-close any open position on the last bar
    if state.open_position is not None:
        last = candles[-1]
        trade = _close_position(state.open_position, last.close, "end_of_data",
                                len(candles) - 1, last.timestamp, tuning.fee_pct)
        state.capital += trade.pnl
        state.closed_trades.append(trade)
        state.open_position = None
        writer.log_trade(trade)

    # ----- Compute metrics -----
    trade_records = [
        TradeRecord(pnl=t.pnl, pnl_pct=t.pnl_pct, fees=t.fees, rr_realized=t.rr_realized)
        for t in state.closed_trades
    ]
    period_days = (candles[-1].timestamp - candles[0].timestamp) / 1000.0 / 86400.0
    bars_per_year = BARS_PER_YEAR_BY_TIMEFRAME.get(timeframe, 252)

    metrics = compute_metrics(
        trades=trade_records,
        equity_curve=state.equity_curve,
        initial_capital=initial_capital,
        first_close=candles[0].close,
        last_close=candles[-1].close,
        period_days=period_days,
        bars_processed=len(candles),
        bars_per_year=bars_per_year,
        fee_pct=tuning.fee_pct,
    )

    writer.write_equity(state.equity_curve, state.equity_timestamps)
    summary = {
        "metrics": metrics.to_dict(),
        "stats": stats,
        "config": {
            "timeframe": timeframe,
            "warmup_bars": WARMUP_BARS,
            "max_hold_bars": MAX_HOLD_BARS,
            "fee_pct": tuning.fee_pct,
            "decision_threshold": Config.DECISION_THRESHOLD,
            "risk_per_trade": Config.RISK_PER_TRADE,
        },
        "tuning": asdict(tuning),
    }
    writer.write_summary(summary)

    print()
    print(format_metrics(metrics))
    print()
    print("PIPELINE STATS")
    print(f"  total decisions      : {stats['total_decisions']}")
    print(f"  GO                   : {stats['go']}")
    print(f"  NO-GO                : {stats['no_go']}")
    print(f"  pre-filter vetoes    : {stats['vetoes_pre_filter']}")
    print(f"  no-kb vetoes         : {stats.get('vetoes_no_kb', 0)}")
    print(f"  bias vetoes          : {stats.get('vetoes_bias', 0)}")
    print(f"  hallucination vetoes : {stats.get('vetoes_hallucination', 0)}")
    print(f"  risk vetoes          : {stats['vetoes_risk']}")
    print(f"  hallucination alarms : {stats['alarms']}")
    print(f"  breakeven moves      : {stats.get('breakeven_moves', 0)}")
    print(f"  executed trades      : {stats['executed_trades']}")
    print()
    print(f"Output -> {out_dir}")

    return summary


# ============================================================
# Entry
# ============================================================


def main():
    parser = argparse.ArgumentParser(description="nogran.trader.agent backtest")
    parser.add_argument("--source", choices=["ccxt", "csv", "synthetic"], default="ccxt")
    parser.add_argument("--exchange", default="kraken",
                        help="ccxt exchange id (kraken|binance|...). Use binance pra historico longo")
    parser.add_argument("--symbol", default="BTC/USD")
    parser.add_argument("--timeframe", default="1m")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--candles", type=int, default=500,
                        help="number of synthetic candles (only for --source synthetic)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--initial-capital", type=float, default=10000.0)
    parser.add_argument("--no-fetch", action="store_true",
                        help="when source=ccxt, error out if no cache exists instead of refetching")
    parser.add_argument("--out-dir", default=None,
                        help="output directory (default: logs/backtest/<run_id>)")
    # Tuning flags (NAO mutam Config — apenas afetam este run)
    parser.add_argument("--rr", type=float, default=Config.MIN_REWARD_RISK,
                        help=f"reward/risk minimo (default Config.MIN_REWARD_RISK={Config.MIN_REWARD_RISK})")
    parser.add_argument("--atr-stop", type=float, default=Config.ATR_STOP_MULTIPLIER,
                        help=f"ATR stop multiplier (default {Config.ATR_STOP_MULTIPLIER})")
    parser.add_argument("--mq-threshold", type=int, default=50,
                        help="pre-filter MQ veto threshold (default 50; below this candle is vetoed pre-LLM)")
    parser.add_argument("--peak-only", action="store_true",
                        help="opera so em peak session UTC 13:30-21:00 (NY hours)")
    parser.add_argument("--maker-fees", action="store_true",
                        help="usa Kraken Pro maker fee 0.16%% em vez de taker 0.26%%")
    parser.add_argument("--fee-pct", type=float, default=None,
                        help="override fee fraction per side (ex: 0.0 pra zero-fee, 0.001 pra 0.1%%)")
    parser.add_argument("--max-leverage", type=float, default=1.0,
                        help="cap notional/capital (default 1.0 = sem leverage)")
    parser.add_argument("--label", default="",
                        help="label opcional pra incluir no out_dir name (ex: 'baseline', 'tuned-v1')")
    parser.add_argument("--strategy-source", choices=["mock", "python_llm"], default="mock",
                        help="signal source: 'mock' (deterministic Nogran PA heuristic) or "
                             "'python_llm' (LLM single-call structured). Default mock.")
    parser.add_argument("--provider", choices=["openai", "gemini"], default="gemini",
                        help="LLM provider when --strategy-source python_llm. Default gemini (free tier)")
    parser.add_argument("--model", default=None,
                        help="override provider's default model. "
                             "OpenAI examples: gpt-4o-2024-08-06 (full, expensive), "
                             "gpt-4o-mini (17x cheaper, 7x higher rate limit). "
                             "Gemini: gemini-2.5-flash-lite, gemini-2.5-flash, etc.")
    parser.add_argument("--max-candles", type=int, default=0,
                        help="if > 0, slice to last N candles (smoke testing)")
    parser.add_argument("--start-offset", type=int, default=-1,
                        help="start the slice N candles from the beginning of the dataset "
                             "(combine with --max-candles for walk-forward windows). "
                             "Use 0 to start at the very first candle.")
    parser.add_argument("--allow-no-kb", action="store_true",
                        help="allow trades without PA KB match (default: veto them as hallucinations)")
    parser.add_argument("--allow-hallucination", action="store_true",
                        help="allow trades when KB hallucination detector fires "
                             "(default: veto warning/critical alarms)")
    parser.add_argument("--no-breakeven", action="store_true",
                        help="disable the breakeven stop ratchet (default: ratchet at RR 1.0)")
    parser.add_argument("--breakeven-trigger-rr", type=float, default=None,
                        help="RR multiple at which the stop is moved to entry "
                             "(default None = use TuningParams default 1.5)")
    parser.add_argument("--no-rag", action="store_true",
                        help="disable PA RAG retriever (LLM sees only system prompt + features)")
    # KB diagnostic flags
    parser.add_argument("--no-kb-blend", action="store_true",
                        help="Test #1: skip KB enrichment blend (LLM solo, no PA KB anchor)")
    parser.add_argument("--halu-threshold", type=int, default=None,
                        help="Test #2: override hallucination gap threshold (default 25). "
                             "Lower = more sensitive = more vetoes.")
    parser.add_argument("--clamp-kb-prob", type=int, default=None,
                        help="Test #3: clamp every KB setup probability_pct to <= this value. "
                             "Tests the hypothesis that the KB book values are over-optimistic for BTC 15m.")
    args = parser.parse_args()

    # Inject provider/model into module-level globals for _get_llm_strategy()
    global _llm_provider_name, _llm_model_override, _llm_use_rag
    _llm_provider_name = args.provider
    _llm_model_override = args.model
    _llm_use_rag = not args.no_rag

    if args.fee_pct is not None:
        fee = args.fee_pct
    elif args.maker_fees:
        fee = KRAKEN_MAKER_FEE_DEFAULT
    else:
        fee = KRAKEN_TAKER_FEE_DEFAULT

    tuning = TuningParams(
        rr_min=args.rr,
        atr_stop_mult=args.atr_stop,
        mq_threshold=args.mq_threshold,
        peak_only=args.peak_only,
        fee_pct=fee,
        max_leverage=args.max_leverage,
        strategy_source=args.strategy_source,
        require_kb_match=not args.allow_no_kb,
        veto_hallucination=not args.allow_hallucination,
        no_kb_blend=args.no_kb_blend,
        halu_threshold=args.halu_threshold,
        clamp_kb_prob=args.clamp_kb_prob,
        breakeven_enabled=not args.no_breakeven,
        **({'breakeven_trigger_rr': args.breakeven_trigger_rr} if args.breakeven_trigger_rr is not None else {}),
    )

    # Resolve output dir
    if args.out_dir:
        out_dir = Path(args.out_dir)
    else:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        if args.label:
            run_id = f"{run_id}_{args.label}"
        out_dir = ROOT / "logs" / "backtest" / run_id

    # Resolve data
    if args.source == "synthetic":
        candles = generate_pa_phases(args.candles, args.seed)
        print(f"Synthetic mode: {len(candles)} candles (seed={args.seed})")
    elif args.source == "csv":
        candles = load_ohlcv_csv(args.symbol, args.timeframe, args.days, exchange_id=args.exchange)
    else:  # ccxt
        cache = _cache_path_ex(args.exchange, args.symbol, args.timeframe, args.days)
        if cache.exists() and args.no_fetch:
            candles = load_ohlcv_csv(args.symbol, args.timeframe, args.days, exchange_id=args.exchange)
        elif cache.exists():
            print(f"Cache hit: {cache}")
            candles = load_ohlcv_csv(args.symbol, args.timeframe, args.days, exchange_id=args.exchange)
        else:
            try:
                candles = fetch_ohlcv_ccxt(args.symbol, args.timeframe, args.days, exchange_id=args.exchange)
            except Exception as e:
                print(f"ccxt fetch failed: {e}")
                print("Falling back to synthetic data.")
                candles = generate_pa_phases(max(args.candles, 500), args.seed)

    # Walk-forward window: start at offset, take max_candles from there.
    # If only --max-candles is set, behave as before (last N).
    if args.start_offset >= 0:
        start = args.start_offset
        end = start + (args.max_candles if args.max_candles > 0 else len(candles) - start)
        candles = candles[start:end]
        print(f"Sliced to candles [{start}:{start + len(candles)}] "
              f"({len(candles)} candles)")
    elif args.max_candles > 0 and len(candles) > args.max_candles:
        candles = candles[-args.max_candles:]
        print(f"Sliced to last {len(candles)} candles (--max-candles {args.max_candles})")

    if len(candles) < WARMUP_BARS + 10:
        print(f"ERROR: only {len(candles)} candles, need >= {WARMUP_BARS + 10}")
        sys.exit(1)

    run_backtest(
        candles=candles,
        initial_capital=args.initial_capital,
        timeframe=args.timeframe,
        out_dir=out_dir,
        tuning=tuning,
    )


if __name__ == "__main__":
    main()
