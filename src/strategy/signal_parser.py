import logging

from pydantic import BaseModel, Field, ValidationError, model_validator

from domain.enums import Action, AlwaysIn, DayType, SetupType, SignalBarQuality
from domain.models import TradeSignal

logger = logging.getLogger(__name__)

# Setup quality hierarchy (higher = better)
SETUP_QUALITY = {
    "second_entry_H2": 0,
    "breakout_pullback": -5,
    "H2_ema": -10,
    "ii_breakout": -15,
    "shaved_bar": -20,
    "none": -50,
}


# ============================================================
# Schema validation (Pydantic) for raw LLM JSON responses
# ============================================================
# Defensive bounds against malformed payloads:
# - precos negativos / absurdos
# - strings absurdamente longas (memory bombs)
# - campos faltantes (cobertos por defaults)
# - inconsistencia direcional (BUY com stop acima do entry, etc.)

MAX_REASONING_CHARS = 4000   # Razao do LLM truncada (defensive)
MAX_LABEL_CHARS = 100        # tipo_dia, setup, etc.
MAX_PRICE = 10_000_000.0     # USD por BTC — folga absurda


class LLMSignalSchema(BaseModel):
    """Strict schema for the raw LLM JSON response (5-layer top-down output)."""

    acao: str = Field(default="AGUARDAR", max_length=MAX_LABEL_CHARS)
    confianca: int = Field(default=0, ge=0, le=100)
    tipo_dia: str = Field(default="indefinido", max_length=MAX_LABEL_CHARS)
    always_in: str = Field(default="NEUTRO", max_length=MAX_LABEL_CHARS)
    setup: str = Field(default="none", max_length=MAX_LABEL_CHARS)
    qualidade_signal_bar: str = Field(default="REPROVADO", max_length=MAX_LABEL_CHARS)
    entry_price: float = Field(default=0.0, ge=0.0, le=MAX_PRICE)
    stop_loss: float = Field(default=0.0, ge=0.0, le=MAX_PRICE)
    take_profit: float = Field(default=0.0, ge=0.0, le=MAX_PRICE)
    camada_decisiva: int = Field(default=0, ge=0, le=10)
    razao: str = Field(default="", max_length=MAX_REASONING_CHARS)

    model_config = {
        "extra": "ignore",          # ignora campos extras silenciosamente
        "str_strip_whitespace": True,
    }

    @model_validator(mode="after")
    def check_directional_consistency(self):
        """
        Se a acao for BUY/SELL com precos definidos, valida que stop e target
        estao do lado certo do entry. Sinal incoerente vira AGUARDAR (downstream
        decide nao operar).
        """
        action_upper = self.acao.upper()

        if action_upper == "COMPRA" and self.entry_price > 0:
            if self.stop_loss > 0 and self.stop_loss >= self.entry_price:
                logger.warning(
                    f"LLM signal incoherent: COMPRA with stop_loss {self.stop_loss} "
                    f">= entry {self.entry_price} — coerced to AGUARDAR"
                )
                self.acao = "AGUARDAR"
            elif self.take_profit > 0 and self.take_profit <= self.entry_price:
                logger.warning(
                    f"LLM signal incoherent: COMPRA with take_profit {self.take_profit} "
                    f"<= entry {self.entry_price} — coerced to AGUARDAR"
                )
                self.acao = "AGUARDAR"
        elif action_upper == "VENDA" and self.entry_price > 0:
            if self.stop_loss > 0 and self.stop_loss <= self.entry_price:
                logger.warning(
                    f"LLM signal incoherent: VENDA with stop_loss {self.stop_loss} "
                    f"<= entry {self.entry_price} — coerced to AGUARDAR"
                )
                self.acao = "AGUARDAR"
            elif self.take_profit > 0 and self.take_profit >= self.entry_price:
                logger.warning(
                    f"LLM signal incoherent: VENDA with take_profit {self.take_profit} "
                    f">= entry {self.entry_price} — coerced to AGUARDAR"
                )
                self.acao = "AGUARDAR"

        return self


def parse_signal(raw: dict | None) -> TradeSignal | None:
    """
    Parse a raw LLM JSON response into a TradeSignal.

    Pipeline:
    1. Validate raw via Pydantic LLMSignalSchema (strict bounds + coerencia direcional)
    2. Coerce string fields para os enums internos (com fallback seguro)
    3. Build TradeSignal

    Returns None if validation or parsing fails.
    """
    if raw is None:
        return None

    if not isinstance(raw, dict):
        logger.error(f"LLM response is not a dict: type={type(raw).__name__}")
        return None

    # Stage 1: Pydantic schema validation
    try:
        validated = LLMSignalSchema.model_validate(raw)
    except ValidationError as e:
        # Log first 3 errors compactly (defensive against verbose payloads)
        errors = e.errors()[:3]
        compact = [f"{err['loc']}={err['msg']}" for err in errors]
        logger.error(
            f"LLM response failed schema validation ({len(e.errors())} errors): {compact}"
        )
        return None

    # Stage 2: Coerce strings to internal enums (lenient — unknown values become defaults)
    try:
        action_str = validated.acao.upper()
        action = Action(action_str) if action_str in Action.__members__ else Action.AGUARDAR

        try:
            day_type = DayType(validated.tipo_dia)
        except ValueError:
            day_type = DayType.INDEFINIDO

        try:
            always_in = AlwaysIn(validated.always_in)
        except ValueError:
            always_in = AlwaysIn.NEUTRO

        try:
            setup = SetupType(validated.setup)
        except ValueError:
            setup = SetupType.NONE

        try:
            quality = SignalBarQuality(validated.qualidade_signal_bar)
        except ValueError:
            quality = SignalBarQuality.REPROVADO

        return TradeSignal(
            action=action,
            confidence=validated.confianca,
            day_type=day_type,
            always_in=always_in,
            setup=setup,
            signal_bar_quality=quality,
            entry_price=validated.entry_price,
            stop_loss=validated.stop_loss,
            take_profit=validated.take_profit,
            decisive_layer=validated.camada_decisiva,
            reasoning=validated.razao,
        )
    except Exception as e:
        logger.error(f"Failed to build TradeSignal after validation: {e}")
        return None


def calculate_strategy_score(signal: TradeSignal) -> int:
    """
    Strategy Score (0-100) based on LLM confidence + setup quality + consistency.
    """
    if signal is None or signal.action == Action.AGUARDAR:
        return 0

    score = float(signal.confidence)

    # Penalize if signal bar is rejected but LLM suggests trading anyway
    if signal.signal_bar_quality == SignalBarQuality.REPROVADO:
        score -= 30

    # Setup quality adjustment
    score += SETUP_QUALITY.get(signal.setup.value, -25)

    # Bonus for clear day type
    if signal.day_type != DayType.INDEFINIDO:
        score += 5

    # Bonus for clear always-in direction matching action
    if signal.always_in == AlwaysIn.SEMPRE_COMPRADO and signal.action == Action.COMPRA:
        score += 5
    elif signal.always_in == AlwaysIn.SEMPRE_VENDIDO and signal.action == Action.VENDA:
        score += 5
    elif signal.always_in == AlwaysIn.NEUTRO:
        score -= 5  # Less conviction

    return max(0, min(100, int(score)))


def calculate_strategy_score_with_kb(signal: TradeSignal, kb=None):
    """
    Enriched strategy score: blend the LLM-derived score with the Nogran PA KB
    probability and trigger a hallucination alarm on divergence.

    - kb: a ProbabilitiesKB instance. If None, behaviour is identical to
      calculate_strategy_score (backward compat).

    Returns EnrichedScore (see probabilities_kb.py).
    """
    llm_score = calculate_strategy_score(signal)

    if kb is None:
        from strategy.probabilities_kb import EnrichedScore
        return EnrichedScore(
            llm_score=llm_score,
            blended_score=llm_score,
            match=None,
            alarm=None,
            rr_warning=None,
        )

    return kb.enrich_signal(signal, llm_score)
