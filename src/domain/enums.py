from enum import Enum


class Action(str, Enum):
    COMPRA = "COMPRA"
    VENDA = "VENDA"
    AGUARDAR = "AGUARDAR"


class Regime(str, Enum):
    TRENDING = "TRENDING"
    RANGING = "RANGING"
    TRANSITIONING = "TRANSITIONING"


class DayType(str, Enum):
    TREND_FROM_OPEN = "trend_from_open"
    SPIKE_AND_CHANNEL = "spike_and_channel"
    TRENDING_TRADING_RANGE = "trending_trading_range"
    REVERSAL_DAY = "reversal_day"
    TREND_RESUMPTION = "trend_resumption"
    INDEFINIDO = "indefinido"


class AlwaysIn(str, Enum):
    SEMPRE_COMPRADO = "SEMPRE_COMPRADO"
    SEMPRE_VENDIDO = "SEMPRE_VENDIDO"
    NEUTRO = "NEUTRO"


class SetupType(str, Enum):
    SECOND_ENTRY_H2 = "second_entry_H2"
    BREAKOUT_PULLBACK = "breakout_pullback"
    H2_EMA = "H2_ema"
    II_BREAKOUT = "ii_breakout"
    SHAVED_BAR = "shaved_bar"
    NONE = "none"


class SignalBarQuality(str, Enum):
    APROVADO = "APROVADO"
    REPROVADO = "REPROVADO"


class DrawdownBand(str, Enum):
    NORMAL = "NORMAL"           # 0-3%
    DEFENSIVE = "DEFENSIVE"     # 3-5%
    MINIMUM = "MINIMUM"         # 5-8%
    CIRCUIT_BREAKER = "CIRCUIT_BREAKER"  # >8%
