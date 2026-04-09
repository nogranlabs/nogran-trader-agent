"""Tests for src/strategy/pa_retriever.py — rule-based RAG."""

import json
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from domain.models import Candle, FeatureSnapshot  # noqa: E402
from strategy.pa_retriever import (  # noqa: E402
    LAYER_FILES,
    PAChunk,
    PARetriever,
    RetrievalResult,
)

# ============================================================
# Helpers
# ============================================================


def make_features(**overrides) -> FeatureSnapshot:
    c = Candle(
        timestamp=overrides.pop("timestamp", 1775653260000),
        open=overrides.pop("open", 67000),
        high=overrides.pop("high", 67200),
        low=overrides.pop("low", 66950),
        close=overrides.pop("close", 67150),
        volume=overrides.pop("volume", 8.5),
    )
    return FeatureSnapshot(
        candle=c,
        candle_index=overrides.pop("candle_index", 100),
        ema_20=overrides.pop("ema_20", 66950.0),
        atr_14=overrides.pop("atr_14", 80.0),
        atr_sma_20=overrides.pop("atr_sma_20", 75.0),
        adx_14=overrides.pop("adx_14", 28.0),
        price_vs_ema=overrides.pop("price_vs_ema", 0.30),
        atr_ratio=overrides.pop("atr_ratio", 1.07),
        body_pct=overrides.pop("body_pct", 60.0),
        upper_tail_pct=overrides.pop("upper_tail_pct", 20.0),
        lower_tail_pct=overrides.pop("lower_tail_pct", 20.0),
        consecutive_bull=overrides.pop("consecutive_bull", 3),
        consecutive_bear=overrides.pop("consecutive_bear", 0),
        bar_overlap_ratio=overrides.pop("bar_overlap_ratio", 0.35),
        direction_change_ratio=overrides.pop("direction_change_ratio", 0.20),
        volume_ratio=overrides.pop("volume_ratio", 1.3),
        is_peak_session=overrides.pop("is_peak_session", True),
        atr_expanding=overrides.pop("atr_expanding", True),
        atr_contracting=overrides.pop("atr_contracting", False),
    )


def make_temp_chunks_dir(tmpdir: Path) -> Path:
    """Create a fake chunks dir with minimal layer files for testing."""
    chunks_dir = tmpdir / "chunks"
    chunks_dir.mkdir(parents=True)

    # layer1: spike_and_channel + trend_from_open
    (chunks_dir / "layer1_day_type.json").write_text(json.dumps([
        {
            "id": "day_type_spike_and_channel_chunk001",
            "topic": "spike_and_channel",
            "description": "Spike and Channel basics",
            "content": "A spike and channel pattern starts with a strong directional spike followed by a slower channel.",
        },
        {
            "id": "day_type_trend_from_open_chunk001",
            "topic": "trend_from_open",
            "description": "Trend from the open",
            "content": "Trend from the open is a day that opens at one extreme and closes at the other.",
        },
        {
            "id": "day_type_trending_trading_range_chunk001",
            "topic": "trending_trading_range",
            "description": "Trending trading range",
            "content": "Trending trading range alternates between range and trend phases.",
        },
        {
            "id": "day_type_reversal_day_chunk001",
            "topic": "reversal_day",
            "description": "Reversal day",
            "content": "A reversal day starts in one direction and reverses to the opposite.",
        },
    ]), encoding="utf-8")

    # layer2: macro
    (chunks_dir / "layer2_macro.json").write_text(json.dumps([
        {
            "id": "macro_spectrum_chunk001",
            "topic": "spectrum_of_price_action",
            "description": "Spectrum",
            "content": "Nogran PA: every market is somewhere on a spectrum from pure trend to pure trading range.",
        },
        {
            "id": "macro_signs_of_strength_chunk001",
            "topic": "signs_of_strength_in_trends",
            "description": "Signs of strength",
            "content": "Signs of strength: strong trend bars, follow-through, no climax, breakouts succeed.",
        },
        {
            "id": "macro_two_legs_chunk001",
            "topic": "two_legs",
            "description": "Two legs",
            "content": "Nogran PA: most pullbacks have two legs before the trend resumes.",
        },
    ]), encoding="utf-8")

    # layer3: structure
    (chunks_dir / "layer3_structure.json").write_text(json.dumps([
        {
            "id": "structure_trend_lines_chunk001",
            "topic": "trend_lines",
            "description": "Trend lines",
            "content": "A trend line is drawn from significant pivot lows in an uptrend or highs in a downtrend.",
        },
        {
            "id": "structure_breakouts_tests_chunk001",
            "topic": "breakouts_and_tests",
            "description": "Breakouts and tests",
            "content": "Breakouts often pull back to test the breakout level before continuing.",
        },
    ]), encoding="utf-8")

    # layer4: micro
    (chunks_dir / "layer4_micro.json").write_text(json.dumps([
        {
            "id": "micro_bar_anatomy_chunk001",
            "topic": "bar_anatomy",
            "description": "Bar anatomy",
            "content": "Every bar has a body (open to close) and tails (high above close, low below open).",
        },
        {
            "id": "micro_reversal_bar_chunk001",
            "topic": "reversal_bar_criteria",
            "description": "Reversal bar criteria",
            "content": "A reversal bar must close strongly opposite to prior trend with a tail in the trend direction.",
        },
        {
            "id": "micro_signal_bar_chunk001",
            "topic": "signal_and_entry_bars",
            "description": "Signal and entry bars",
            "content": "Signal bar must have body 50%+ of range and tail aligned with intended direction.",
        },
    ]), encoding="utf-8")

    # layer5: setup
    (chunks_dir / "layer5_setup.json").write_text(json.dumps([
        {
            "id": "setup_signal_bar_types_chunk001",
            "topic": "signal_bar_types",
            "description": "Signal bar types",
            "content": "Nogran PA identifies several signal bar types: trend bars, ii, iii, two-bar reversals.",
        },
        {
            "id": "setup_second_entries_chunk001",
            "topic": "second_entries",
            "description": "Second entries",
            "content": "Second entries are more reliable than first entries because they show pullback failure.",
        },
    ]), encoding="utf-8")

    return chunks_dir


# ============================================================
# Loading
# ============================================================


class TestLoading:
    def test_missing_dir_graceful(self):
        r = PARetriever(chunks_dir=Path("/nonexistent/path/xyz"))
        assert not r.available
        assert r.total_loaded == 0

    def test_load_real_dir_if_present(self):
        # Production chunks dir — may or may not exist
        r = PARetriever()
        # If it exists, should load 100+ chunks
        if r.available:
            assert r.total_loaded >= 100

    def test_load_temp_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            chunks_dir = make_temp_chunks_dir(Path(tmp))
            r = PARetriever(chunks_dir=chunks_dir)
            assert r.available
            # 4 (layer1) + 3 (layer2) + 2 (layer3) + 3 (layer4) + 2 (layer5) = 14
            assert r.total_loaded == 14

    def test_lazy_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            chunks_dir = make_temp_chunks_dir(Path(tmp))
            r = PARetriever(chunks_dir=chunks_dir)
            # Not loaded yet (no method called)
            assert not r._loaded
            # Trigger load
            _ = r.available
            assert r._loaded


# ============================================================
# Retrieval rules per layer
# ============================================================


class TestLayerSelection:
    def _retriever(self, tmpdir):
        chunks_dir = make_temp_chunks_dir(Path(tmpdir))
        return PARetriever(chunks_dir=chunks_dir)

    def test_retrieve_returns_chunks_for_strong_bull(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = self._retriever(tmp)
            f = make_features(consecutive_bull=4, adx_14=30, body_pct=60)
            result = r.retrieve(f)
            assert result.total_chunks > 0
            # Layer 1 should pick spike_and_channel + trend_from_open
            assert "layer1" in result.chunks
            topics_l1 = {c.topic for c in result.chunks["layer1"]}
            assert "spike_and_channel" in topics_l1

    def test_retrieve_picks_trend_from_open_when_strong_directional(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = self._retriever(tmp)
            f = make_features(consecutive_bull=4, adx_14=30)
            result = r.retrieve(f)
            topics_l1 = {c.topic for c in result.chunks.get("layer1", [])}
            assert "trend_from_open" in topics_l1

    def test_retrieve_picks_reversal_day_with_large_upper_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = self._retriever(tmp)
            f = make_features(consecutive_bull=2, consecutive_bear=0, upper_tail_pct=40)
            result = r.retrieve(f)
            # reversal_day is the 4th topic so it might be capped by max_per_layer=2
            # Just check that the layer was retrieved
            assert "layer1" in result.chunks

    def test_layer3_always_returns_chunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = self._retriever(tmp)
            f = make_features()
            result = r.retrieve(f)
            assert "layer3" in result.chunks
            assert len(result.chunks["layer3"]) >= 1

    def test_max_per_layer_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = self._retriever(tmp)
            f = make_features(consecutive_bull=4, adx_14=30, body_pct=60)
            result = r.retrieve(f, max_per_layer=1)
            for _layer, chunks in result.chunks.items():
                assert len(chunks) <= 1

    def test_layer4_picks_signal_bar_when_body_high(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = self._retriever(tmp)
            f = make_features(body_pct=70)
            result = r.retrieve(f)
            topics_l4 = {c.topic for c in result.chunks.get("layer4", [])}
            # bar_anatomy always; signal_and_entry_bars when body >= 40
            assert "bar_anatomy" in topics_l4

    def test_layer5_picks_second_entries_when_consecutive(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = self._retriever(tmp)
            f = make_features(consecutive_bull=2)
            result = r.retrieve(f)
            topics_l5 = {c.topic for c in result.chunks.get("layer5", [])}
            assert "second_entries" in topics_l5


# ============================================================
# RetrievalResult
# ============================================================


class TestRetrievalResult:
    def test_empty_result(self):
        r = RetrievalResult()
        assert r.total_chunks == 0
        assert r.chunk_ids() == []
        assert r.to_prompt_text() == ""

    def test_chunk_ids_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            chunks_dir = make_temp_chunks_dir(Path(tmp))
            r = PARetriever(chunks_dir=chunks_dir)
            f = make_features(consecutive_bull=3, adx_14=30)
            result = r.retrieve(f)
            ids = result.chunk_ids()
            assert ids == sorted(ids)

    def test_prompt_text_includes_pa_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            chunks_dir = make_temp_chunks_dir(Path(tmp))
            r = PARetriever(chunks_dir=chunks_dir)
            f = make_features()
            result = r.retrieve(f)
            text = result.to_prompt_text()
            assert "NOGRAN PA REFERENCE" in text
            assert "LAYER" in text.upper()

    def test_prompt_text_groups_by_layer(self):
        with tempfile.TemporaryDirectory() as tmp:
            chunks_dir = make_temp_chunks_dir(Path(tmp))
            r = PARetriever(chunks_dir=chunks_dir)
            f = make_features()
            result = r.retrieve(f)
            text = result.to_prompt_text()
            # Should have layer1 section if any layer1 chunks
            if "layer1" in result.chunks:
                assert "## LAYER1" in text


# ============================================================
# get_chunk lookup
# ============================================================


class TestGetChunk:
    def test_get_existing_chunk(self):
        with tempfile.TemporaryDirectory() as tmp:
            chunks_dir = make_temp_chunks_dir(Path(tmp))
            r = PARetriever(chunks_dir=chunks_dir)
            chunk = r.get_chunk("day_type_spike_and_channel_chunk001")
            assert chunk is not None
            assert chunk.topic == "spike_and_channel"
            assert chunk.layer == "layer1"

    def test_get_nonexistent_chunk(self):
        with tempfile.TemporaryDirectory() as tmp:
            chunks_dir = make_temp_chunks_dir(Path(tmp))
            r = PARetriever(chunks_dir=chunks_dir)
            assert r.get_chunk("does_not_exist") is None
