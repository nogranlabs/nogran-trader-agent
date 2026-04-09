"""
Tests for signal_parser.py — Pydantic schema validation + TradeSignal coercion.

Resolve docs/tech-debt.md CRITICAL: "Sem validacao de schema na resposta do LLM".

Cenarios cobertos:
- Payload OK: parse normal
- Payload com tipos errados: rejeita com erro
- Payload com numeros absurdos (preco negativo, valores >1e7): rejeita
- Payload com strings absurdamente longas: rejeita
- Payload com inconsistencia direcional (BUY com stop acima do entry): coerce p/ AGUARDAR
- Payload None / nao-dict: retorna None
- Campos faltantes: usa defaults
- Backward compat: todos os campos esperados sao parseados
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from domain.enums import Action, AlwaysIn, DayType, SetupType, SignalBarQuality
from domain.models import TradeSignal
from strategy.signal_parser import (
    MAX_PRICE,
    MAX_REASONING_CHARS,
    LLMSignalSchema,
    parse_signal,
)


def make_raw(**overrides):
    """Build a valid raw LLM response with given overrides."""
    base = {
        "acao": "COMPRA",
        "confianca": 75,
        "tipo_dia": "trend_from_open",
        "always_in": "SEMPRE_COMPRADO",
        "setup": "second_entry_H2",
        "qualidade_signal_bar": "APROVADO",
        "entry_price": 50000.0,
        "stop_loss": 49500.0,
        "take_profit": 51000.0,
        "camada_decisiva": 5,
        "razao": "Second entry H2 in confirmed bull trend",
    }
    base.update(overrides)
    return base


class TestHappyPath:
    def test_valid_buy_signal(self):
        sig = parse_signal(make_raw())
        assert sig is not None
        assert sig.action == Action.COMPRA
        assert sig.confidence == 75
        assert sig.entry_price == 50000.0
        assert sig.stop_loss == 49500.0
        assert sig.take_profit == 51000.0

    def test_valid_sell_signal(self):
        raw = make_raw(
            acao="VENDA", always_in="SEMPRE_VENDIDO",
            entry_price=50000, stop_loss=50500, take_profit=49000,
        )
        sig = parse_signal(raw)
        assert sig is not None
        assert sig.action == Action.VENDA

    def test_aguardar_signal(self):
        raw = make_raw(acao="AGUARDAR", entry_price=0, stop_loss=0, take_profit=0)
        sig = parse_signal(raw)
        assert sig is not None
        assert sig.action == Action.AGUARDAR


class TestNullAndType:
    def test_none_returns_none(self):
        assert parse_signal(None) is None

    def test_non_dict_returns_none(self):
        assert parse_signal("not a dict") is None
        assert parse_signal(["list", "not", "dict"]) is None
        assert parse_signal(42) is None


class TestMissingFields:
    def test_empty_dict_uses_defaults(self):
        sig = parse_signal({})
        assert sig is not None
        assert sig.action == Action.AGUARDAR
        assert sig.confidence == 0
        assert sig.entry_price == 0.0

    def test_partial_fields_works(self):
        sig = parse_signal({"acao": "COMPRA", "confianca": 80})
        assert sig is not None
        assert sig.action == Action.COMPRA
        assert sig.confidence == 80


class TestPriceBounds:
    def test_negative_entry_price_rejected(self):
        sig = parse_signal(make_raw(entry_price=-100))
        assert sig is None  # validation fails

    def test_negative_stop_rejected(self):
        sig = parse_signal(make_raw(stop_loss=-1))
        assert sig is None

    def test_absurd_high_price_rejected(self):
        sig = parse_signal(make_raw(entry_price=MAX_PRICE + 1))
        assert sig is None

    def test_at_max_price_accepted(self):
        raw = make_raw(entry_price=MAX_PRICE, stop_loss=0, take_profit=0, acao="AGUARDAR")
        sig = parse_signal(raw)
        assert sig is not None


class TestConfidenceBounds:
    def test_confidence_above_100_rejected(self):
        sig = parse_signal(make_raw(confianca=150))
        assert sig is None

    def test_negative_confidence_rejected(self):
        sig = parse_signal(make_raw(confianca=-1))
        assert sig is None

    def test_confidence_at_boundaries(self):
        assert parse_signal(make_raw(confianca=0)) is not None
        assert parse_signal(make_raw(confianca=100)) is not None


class TestStringLength:
    def test_reasoning_too_long_rejected(self):
        sig = parse_signal(make_raw(razao="x" * (MAX_REASONING_CHARS + 1)))
        assert sig is None

    def test_reasoning_at_max_accepted(self):
        sig = parse_signal(make_raw(razao="x" * MAX_REASONING_CHARS))
        assert sig is not None

    def test_setup_label_too_long_rejected(self):
        sig = parse_signal(make_raw(setup="x" * 200))
        assert sig is None


class TestDirectionalConsistency:
    def test_buy_with_stop_above_entry_coerced_to_wait(self):
        # Stop acima do entry em uma compra = invalido
        raw = make_raw(entry_price=50000, stop_loss=51000, take_profit=52000)
        sig = parse_signal(raw)
        assert sig is not None
        assert sig.action == Action.AGUARDAR  # coerced

    def test_buy_with_target_below_entry_coerced(self):
        raw = make_raw(entry_price=50000, stop_loss=49500, take_profit=49000)
        sig = parse_signal(raw)
        assert sig is not None
        assert sig.action == Action.AGUARDAR

    def test_sell_with_stop_below_entry_coerced(self):
        raw = make_raw(
            acao="VENDA", entry_price=50000, stop_loss=49000, take_profit=49500,
        )
        sig = parse_signal(raw)
        assert sig is not None
        assert sig.action == Action.AGUARDAR

    def test_sell_with_target_above_entry_coerced(self):
        raw = make_raw(
            acao="VENDA", entry_price=50000, stop_loss=50500, take_profit=51000,
        )
        sig = parse_signal(raw)
        assert sig is not None
        assert sig.action == Action.AGUARDAR


class TestEnumCoercion:
    def test_unknown_setup_falls_back_to_none(self):
        sig = parse_signal(make_raw(setup="unknown_setup_42"))
        assert sig is not None
        assert sig.setup == SetupType.NONE

    def test_unknown_day_type_falls_back(self):
        sig = parse_signal(make_raw(tipo_dia="alien_day_type"))
        assert sig is not None
        assert sig.day_type == DayType.INDEFINIDO

    def test_unknown_action_falls_back(self):
        sig = parse_signal(make_raw(acao="MAYBE", entry_price=0, stop_loss=0, take_profit=0))
        assert sig is not None
        assert sig.action == Action.AGUARDAR


class TestExtraFields:
    def test_extra_fields_silently_ignored(self):
        raw = make_raw(
            extra_field="ignored",
            another_unknown=12345,
            nested={"deep": "stuff"},
        )
        sig = parse_signal(raw)
        assert sig is not None
        assert sig.confidence == 75


class TestTypeMismatch:
    def test_string_in_numeric_field_rejected(self):
        # Pydantic v2 default coerces "75" -> 75 for int. Test for true rejection.
        sig = parse_signal(make_raw(confianca="not_a_number"))
        assert sig is None

    def test_dict_where_float_expected_rejected(self):
        sig = parse_signal(make_raw(entry_price={"nested": "value"}))
        assert sig is None


class TestSchemaDirectly:
    """Sanity checks on the Pydantic model itself."""

    def test_model_validates_minimal_payload(self):
        m = LLMSignalSchema.model_validate({})
        assert m.acao == "AGUARDAR"
        assert m.confianca == 0

    def test_model_strips_whitespace(self):
        m = LLMSignalSchema.model_validate({"acao": "  COMPRA  "})
        assert m.acao == "COMPRA"
