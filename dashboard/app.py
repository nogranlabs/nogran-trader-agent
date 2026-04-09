"""
nogran.trader.agent — Dashboard
Autonomous BTC/USD Trading Agent with Decision Scoring System
"""

import json
import math
import os
import random
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from markupsafe import escape as html_escape  # XSS defense for unsafe_allow_html blocks with dynamic data

# --- Page config (must be first st call) ---
st.set_page_config(
    page_title="nogran.trader.agent",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Constants ---
# DECISIONS_LOG_DIR is resolved + validated to mitigate path traversal via env var
# (docs/tech-debt.md MEDIO item).
_default_log_dir = Path(__file__).resolve().parent.parent / "logs" / "decisions"
_raw_log_dir = os.environ.get("DECISIONS_LOG_DIR", str(_default_log_dir))
try:
    _resolved_log_dir = Path(_raw_log_dir).expanduser().resolve(strict=False)
    # Reject paths that resolve outside the user's home or the project repo —
    # cheap mitigation against `..` traversal or absolute path injection.
    _project_root = Path(__file__).resolve().parent.parent
    _user_home = Path.home().resolve()
    if not (
        _resolved_log_dir == _project_root / "logs" / "decisions"
        or _project_root in _resolved_log_dir.parents
        or _user_home in _resolved_log_dir.parents
    ):
        # Fallback to default — never honor a suspicious path
        _resolved_log_dir = _default_log_dir.resolve()
    LOG_DIR = str(_resolved_log_dir)
except (OSError, ValueError):
    LOG_DIR = str(_default_log_dir.resolve())
GREEN = "#1DB954"
RED = "#E74C3C"
YELLOW = "#F39C12"
BLUE = "#3498db"
PURPLE = "#9b59b6"
AGENT_ADDRESS = "0x97b07dDc405B0c28B17559aFFE63BdB3632d0ca3"  # AgentRegistry (Sepolia)
AGENT_ID = "nogran.trader.agent"
GITHUB_URL = "https://github.com/nogran/nogran.trader.agent"
EXPLORER_URL = "https://sepolia.etherscan.io/address/"

# --- Custom CSS ---
st.markdown("""
<style>
[data-testid="stMetric"] {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
    border: 1px solid rgba(29,185,84,0.25);
    border-radius: 12px;
    padding: 16px 20px;
}
[data-testid="stMetricValue"] { font-size: 2rem !important; font-weight: 700 !important; }
[data-testid="stMetricLabel"] { font-size: 0.85rem !important; text-transform: uppercase; letter-spacing: 1px; opacity: 0.8; }
button[data-baseweb="tab"] { font-size: 1rem !important; font-weight: 600 !important; }
.badge-go { display:inline-block; background:linear-gradient(135deg,#1DB954,#17a74a); color:#fff; font-weight:700; padding:6px 20px; border-radius:20px; font-size:1rem; }
.badge-nogo { display:inline-block; background:linear-gradient(135deg,#E74C3C,#c0392b); color:#fff; font-weight:700; padding:6px 20px; border-radius:20px; font-size:1rem; }
.score-big { font-size:4.5rem; font-weight:800; line-height:1; background:linear-gradient(135deg,#1DB954,#a8e063); -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
.score-big-red { font-size:4.5rem; font-weight:800; line-height:1; background:linear-gradient(135deg,#E74C3C,#f5af19); -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
.pipeline-card { background:linear-gradient(135deg,#1a1a2e,#16213e); border:1px solid rgba(29,185,84,0.2); border-radius:12px; padding:18px; margin-bottom:8px; }
.pipeline-card h4 { margin:0 0 6px 0; color:#1DB954; }
.pipeline-card p { margin:0; font-size:0.88rem; opacity:0.85; }
.check-item { padding:6px 0; border-bottom:1px solid rgba(255,255,255,0.06); font-size:0.92rem; }
.demo-banner { background:linear-gradient(90deg,#F39C12,#E74C3C); color:#fff; text-align:center; padding:10px; border-radius:8px; font-weight:700; margin-bottom:16px; }
.pitch-box { background:linear-gradient(135deg,#0f3443,rgba(52,232,158,0.06)); border-left:4px solid #1DB954; padding:16px; border-radius:0 8px 8px 0; margin-top:12px; font-style:italic; line-height:1.6; }
.erc-card { background:linear-gradient(135deg,#1a1a2e,#0a3d62); border:1px solid rgba(52,152,219,0.25); border-radius:12px; padding:20px; margin-bottom:12px; }
.sig-preview { font-family:'Courier New',monospace; font-size:0.78rem; color:#1DB954; background:#0d0d0d; padding:8px 12px; border-radius:6px; word-break:break-all; }
</style>
""", unsafe_allow_html=True)


# ============================================================
# SAMPLE DATA
# ============================================================

def generate_sample_candles(n: int = 120) -> pd.DataFrame:
    """Generate realistic BTC 1m candles for the chart."""
    rng = random.Random(99)
    ts = datetime(2026, 4, 1, 9, 0, 0)
    price = 67000.0
    rows = []
    for _ in range(n):
        o = price
        move = rng.gauss(0, 40)
        c = o + move
        h = max(o, c) + rng.uniform(5, 50)
        l = min(o, c) - rng.uniform(5, 50)
        vol = rng.uniform(0.5, 8.0)
        rows.append({"time": ts, "open": round(o, 1), "high": round(h, 1), "low": round(l, 1), "close": round(c, 1), "volume": round(vol, 3)})
        price = c + rng.gauss(0, 10)
        ts += timedelta(minutes=1)
    return pd.DataFrame(rows)


# Mapping PT -> EN for real backend data
TRANSLATE = {
    "COMPRA": "BUY", "VENDA": "SELL", "AGUARDAR": "WAIT",
    "SEMPRE_COMPRADO": "ALWAYS_LONG", "SEMPRE_VENDIDO": "ALWAYS_SHORT", "NEUTRO": "NEUTRAL",
    "APROVADO": "APPROVED", "REPROVADO": "REJECTED",
    "ALTA": "BULLISH", "BAIXA": "BEARISH",
}

def translate(val: str) -> str:
    return TRANSLATE.get(val, val)


def generate_sample_data(n: int = 30) -> list[dict]:
    rng = random.Random(42)
    base_price = 67000.0
    decisions = []
    ts = datetime(2026, 4, 1, 9, 30, 0)
    setups = ["second_entry_H2", "breakout_pullback", "H2_ema", "ii_breakout", "shaved_bar", "micro_double_bottom"]
    day_types = ["trend_from_open", "spike_and_channel", "trending_trading_range", "reversal_day", "indefinido"]
    regimes = ["TRENDING", "RANGING", "TRANSITIONING"]
    cumulative_pnl = 0.0

    for _i in range(n):
        ts += timedelta(minutes=rng.randint(15, 90))
        price = base_price + rng.uniform(-800, 800)
        stop_dist = rng.uniform(80, 200)
        rr = rng.uniform(1.5, 3.5)

        should_execute = rng.random() < 0.50
        if should_execute:
            mq = rng.randint(55, 100)
            strat = rng.randint(50, 95)
            ai = rng.randint(45, 90)
            risk = rng.randint(55, 100)
            action = rng.choice(["BUY", "SELL"])
            hard_veto = False
        else:
            mq = rng.randint(15, 75)
            strat = rng.randint(10, 70)
            ai = rng.randint(20, 65)
            risk = rng.randint(15, 80)
            action = rng.choice(["BUY", "SELL", "WAIT"])
            hard_veto = rng.random() < 0.15

        total = round(mq * 0.20 + strat * 0.35 + ai * 0.20 + risk * 0.25, 1)
        go = total >= 65 and not hard_veto and action != "WAIT"
        executed = go

        pnl = None
        win = None
        if executed:
            win = rng.random() < 0.55
            pnl = round(rng.uniform(20, 300), 2) if win else round(-rng.uniform(30, 180), 2)
            cumulative_pnl += pnl

        veto_reason = ""
        if hard_veto:
            veto_reason = rng.choice(["Drawdown circuit breaker", "Max daily trades", "Sharpe < -1.0"])
        elif not go:
            veto_reason = f"Score {total} < threshold 65" if total < 65 else "WAIT signal"

        entry = price
        sl = entry - stop_dist if action == "BUY" else entry + stop_dist
        tp = entry + stop_dist * rr if action == "BUY" else entry - stop_dist * rr
        sig_hash = f"0x{rng.getrandbits(256):064x}"

        dec = {
            "timestamp": ts.isoformat(),
            "executed": executed,
            "mq_score": mq,
            "regime": rng.choice(regimes),
            "decision_score": {
                "total": total, "go": go, "hard_veto": hard_veto, "veto_reason": veto_reason,
                "threshold": 65,
                "breakdown": {
                    "market_quality": {"score": mq, "weight": 0.20, "contribution": round(mq * 0.20, 1)},
                    "strategy": {"score": strat, "weight": 0.35, "contribution": round(strat * 0.35, 1)},
                    "ai_overlay": {"score": ai, "weight": 0.20, "contribution": round(ai * 0.20, 1)},
                    "risk": {"score": risk, "weight": 0.25, "contribution": round(risk * 0.25, 1)},
                },
            },
            "signal": {
                "action": action, "confidence": rng.randint(40, 95),
                "day_type": rng.choice(day_types), "always_in": rng.choice(["ALWAYS_LONG", "ALWAYS_SHORT", "NEUTRAL"]),
                "setup": rng.choice(setups), "signal_bar_quality": rng.choice(["APPROVED", "REJECTED"]),
                "entry_price": round(entry, 2), "stop_loss": round(sl, 2), "take_profit": round(tp, 2),
                "decisive_layer": rng.randint(1, 5),
                "reasoning": rng.choice([
                    "Second entry H2 in confirmed bull trend",
                    "Pullback to EMA in strong bull trend",
                    "Failed L2 reversal — trend continuation expected",
                    "Inside-inside pattern at support level",
                    "No clear setup — discipline over action",
                    "Spike and channel third push — reversal expected",
                ]),
            },
            "risk": {
                "approved": executed, "position_size": round(rng.uniform(0.001, 0.01), 5),
                "current_drawdown": round(rng.uniform(0, 8), 2),
                "drawdown_band": rng.choice(["NORMAL", "DEFENSIVE", "MINIMUM"]),
                "sharpe_rolling": round(rng.uniform(-0.5, 2.5), 2),
                "risk_score": risk, "reward_risk_ratio": round(rr, 2),
            },
            "erc8004_signature": sig_hash if executed else "",
            "fact_preview": f"Candle 1m #{rng.randint(1,60)} closed {'BULLISH' if rng.random()>0.5 else 'BEARISH'}. C=${round(price,1)}",
        }

        # G.2++ Sample KB enrichment (60% match rate, 15% alarm rate)
        sample_setup = dec["signal"]["setup"]
        sample_action = dec["signal"]["action"]
        kb_setup_map = {
            ("second_entry_H2", "BUY"):  ("high_2_pullback_ma_bull", 60, "trading-ranges", 25, 469),
            ("second_entry_H2", "SELL"): ("low_2_pullback_ma_bear", 60, "trading-ranges", 25, 469),
            ("breakout_pullback", "BUY"):  ("breakout_pullback_bull_flag", 60, "trading-ranges", 25, 469),
            ("breakout_pullback", "SELL"): ("breakout_pullback_bear_flag", 60, "trading-ranges", 25, 469),
            ("H2_ema", "BUY"):  ("limit_quiet_bull_flag_at_ma", 60, "trading-ranges", 25, 471),
            ("H2_ema", "SELL"): ("limit_quiet_bear_flag_at_ma", 60, "trading-ranges", 25, 471),
            ("ii_breakout", "BUY"):  ("tr_breakout_setup", 60, "trading-ranges", 1, 95),
            ("ii_breakout", "SELL"): ("tr_breakout_setup", 60, "trading-ranges", 1, 95),
        }
        kb_data = kb_setup_map.get((sample_setup, sample_action))
        if kb_data:
            kb_id, kb_pct, kb_book, kb_ch, kb_pg = kb_data
            LLM = strat
            blend = int(round(LLM * 0.6 + kb_pct * 0.4))
            dec["kb_match"] = {
                "setup_id": kb_id,
                "name_pt": kb_id.replace("_", " ").title(),
                "probability_pct": kb_pct,
                "probability_confidence": "explicit",
                "min_reward_risk": 1.5,
                "book_refs": [{
                    "book": kb_book, "chapter_num": kb_ch,
                    "chapter_title": "Mathematics of Trading",
                    "page_pdf": kb_pg,
                }],
                "llm_score": LLM,
                "blended_score": blend,
            }
            # Trigger sample alarm in ~15% of matches
            gap = LLM - kb_pct
            if abs(gap) >= 25:
                dec["hallucination_alarm"] = {
                    "llm_score": LLM,
                    "pa_probability": kb_pct,
                    "gap": gap,
                    "direction": "llm_too_optimistic" if gap > 0 else "llm_too_pessimistic",
                    "setup_id": kb_id,
                    "severity": "critical" if abs(gap) >= 40 else "warning",
                }

        if executed:
            dec["execution"] = {"order_id": f"KRK-{rng.randint(100000,999999)}", "fill_price": round(entry + rng.uniform(-5, 5), 2), "timestamp": ts.isoformat()}
            dec["pnl"] = pnl
            dec["win"] = win
        decisions.append(dec)
    return decisions


# ============================================================
# DATA LOADING
# ============================================================

@st.cache_data(ttl=30)
def load_decisions() -> tuple[list[dict], bool]:
    decisions = []
    log_path = Path(LOG_DIR)
    if log_path.exists():
        for f in sorted(log_path.glob("*.jsonl")):
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    try:
                        decisions.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    if decisions:
        return decisions, False
    return generate_sample_data(), True


def load_thought_streams() -> list[dict]:
    """Load all thoughts-<date>.jsonl files and return them as a flat list."""
    log_dir = Path(LOG_DIR)
    if not log_dir.exists():
        return []
    streams = []
    for file in sorted(log_dir.glob("thoughts-*.jsonl")):
        try:
            with open(file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            streams.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except OSError:
            continue
    return streams


def decisions_to_df(decisions: list[dict]) -> pd.DataFrame:
    rows = []
    for d in decisions:
        ds = d.get("decision_score", {})
        sig = d.get("signal", {})
        rsk = d.get("risk", {})
        bd = ds.get("breakdown", {})

        # PA KB enrichment (G.2++)
        kb = d.get("kb_match") or {}
        alarm = d.get("hallucination_alarm") or {}
        kb_book_refs = kb.get("book_refs", [])
        kb_first_ref = kb_book_refs[0] if kb_book_refs else {}
        kb_citation = ""
        if kb_first_ref:
            kb_citation = (
                f"{kb_first_ref.get('book', '')} ch{kb_first_ref.get('chapter_num', '')} "
                f"p{kb_first_ref.get('page_pdf', '')}"
            )

        rows.append({
            # utc=True normalizes mixed tz-naive (legacy) and tz-aware (sim) timestamps
            "timestamp": pd.to_datetime(d.get("timestamp"), utc=True, errors="coerce"),
            "total_score": ds.get("total", 0),
            "go": ds.get("go", False),
            "hard_veto": ds.get("hard_veto", False),
            "veto_reason": ds.get("veto_reason", ""),
            "executed": d.get("executed", False),
            "action": translate(sig.get("action", "")),
            "setup": sig.get("setup", ""),
            "confidence": sig.get("confidence", 0),
            "entry_price": sig.get("entry_price", 0),
            "stop_loss": sig.get("stop_loss", 0),
            "take_profit": sig.get("take_profit", 0),
            "reasoning": sig.get("reasoning", ""),
            "day_type": sig.get("day_type", ""),
            "always_in": sig.get("always_in", ""),
            "regime": d.get("regime", ""),
            "mq_score": bd.get("market_quality", {}).get("score", 0),
            "strat_score": bd.get("strategy", {}).get("score", 0),
            "ai_score": bd.get("ai_overlay", {}).get("score", 0),
            "risk_score": bd.get("risk", {}).get("score", 0),
            "position_size": rsk.get("position_size", 0),
            "current_drawdown": rsk.get("current_drawdown", 0),
            "sharpe_rolling": rsk.get("sharpe_rolling", 0),
            "reward_risk_ratio": rsk.get("reward_risk_ratio", 0),
            "pnl": d.get("pnl"),
            "win": d.get("win"),
            "erc8004_signature": d.get("erc8004_signature", ""),
            "fact_preview": d.get("fact_preview", ""),
            # G.2++ KB fields
            "kb_setup_id": kb.get("setup_id", ""),
            "kb_probability_pct": kb.get("probability_pct"),
            "kb_llm_score": kb.get("llm_score"),
            "kb_blended_score": kb.get("blended_score"),
            "kb_citation": kb_citation,
            "kb_notes_pt": kb.get("name_pt", ""),
            "hallucination_severity": alarm.get("severity", ""),
            "hallucination_gap": alarm.get("gap"),
            "hallucination_direction": alarm.get("direction", ""),
            "rr_warning": d.get("rr_warning", ""),
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df.sort_values("timestamp", inplace=True)
        df.reset_index(drop=True, inplace=True)
    return df


def score_color(s):
    if s >= 65:
        return GREEN
    if s >= 40:
        return YELLOW
    return RED


def fmt_currency(val):
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "$0.00"
    return f"${val:,.2f}" if val >= 0 else f"-${abs(val):,.2f}"


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    st.markdown("### 🤖 nogran.trader.agent v3")
    st.caption("Autonomous BTC/USD Trading Agent")
    st.divider()
    st.markdown(
        '<div class="pitch-box">"The most disciplined agent in the hackathon. '
        "It doesn't win by trading more &mdash; "
        'it wins by knowing when <b>NOT</b> to trade."</div>',
        unsafe_allow_html=True,
    )
    st.divider()

    # --- Risk Profile Controls ---
    st.markdown("#### ⚙️ Risk Profile")

    risk_profile = st.select_slider(
        "Profile",
        options=["Conservative", "Moderate", "Aggressive"],
        value="Moderate",
    )

    # Map profile to defaults
    profile_defaults = {
        "Conservative": {"risk": 0.5, "threshold": 75, "max_trades": 2, "min_rr": 2.0, "atr_mult": 2.0},
        "Moderate":     {"risk": 1.0, "threshold": 65, "max_trades": 4, "min_rr": 1.5, "atr_mult": 1.5},
        "Aggressive":   {"risk": 2.0, "threshold": 55, "max_trades": 6, "min_rr": 1.5, "atr_mult": 1.2},
    }
    defaults = profile_defaults[risk_profile]

    risk_per_trade = st.slider("Risk per trade (%)", 0.5, 3.0, defaults["risk"], 0.1)
    decision_threshold = st.slider("Decision Score threshold", 50, 85, defaults["threshold"], 1)
    max_trades_hour = st.slider("Max trades / hour", 1, 8, defaults["max_trades"], 1)
    min_rr = st.slider("Min Reward/Risk ratio", 1.0, 3.5, defaults["min_rr"], 0.1)
    atr_stop_mult = st.slider("ATR Stop multiplier", 1.0, 3.0, defaults["atr_mult"], 0.1)

    # Save to session state (backend can read these)
    st.session_state["risk_per_trade"] = risk_per_trade / 100
    st.session_state["decision_threshold"] = decision_threshold
    st.session_state["max_trades_hour"] = max_trades_hour
    st.session_state["min_rr"] = min_rr
    st.session_state["atr_stop_mult"] = atr_stop_mult

    # Export as JSON for backend consumption
    risk_config = {
        "profile": risk_profile,
        "risk_per_trade": risk_per_trade / 100,
        "decision_threshold": decision_threshold,
        "max_trades_per_hour": max_trades_hour,
        "min_reward_risk": min_rr,
        "atr_stop_multiplier": atr_stop_mult,
    }
    st.divider()
    with st.expander("📋 Export Config JSON"):
        st.code(json.dumps(risk_config, indent=2), language="json")

    # Session mode indicator
    st.divider()
    from datetime import timezone
    _now = datetime.now(timezone.utc)
    _hour = _now.hour + _now.minute / 60.0
    _weekend = _now.weekday() >= 5
    if _weekend:
        _session = "CONSERVATIVE" if 7.0 <= _hour < 21.0 else "OBSERVATION"
    else:
        if 13.5 <= _hour < 21.0:
            _session = "AGGRESSIVE"
        elif 7.0 <= _hour < 13.5:
            _session = "CONSERVATIVE"
        else:
            _session = "OBSERVATION"
    _sess_colors = {"AGGRESSIVE": "#1DB954", "CONSERVATIVE": "#F39C12", "OBSERVATION": "#E74C3C"}
    st.markdown(f"**Session:** <span style='color:{_sess_colors[_session]};font-weight:700;'>{_session}</span>", unsafe_allow_html=True)
    _sess_desc = {"AGGRESSIVE": "NY Open — all setups", "CONSERVATIVE": "London / Weekend — best setups only", "OBSERVATION": "Off-hours — no trading"}
    st.caption(_sess_desc[_session])

    st.divider()
    st.markdown(f"[GitHub Repository]({GITHUB_URL})")
    st.markdown(f"[Architecture Docs]({GITHUB_URL}/blob/main/ARCHITECTURE.md)")
    st.divider()
    st.caption("ERC-8004 compliant · Kraken CLI · Nogran PA RAG")
    if st.button("🔄 Refresh Data"):
        st.cache_data.clear()
        st.rerun()


# ============================================================
# LOAD DATA
# ============================================================

decisions_raw, demo_mode = load_decisions()
df = decisions_to_df(decisions_raw)

if demo_mode:
    st.markdown('<div class="demo-banner">🚧 DEMO MODE — No live logs. Showing sample data.</div>', unsafe_allow_html=True)

executed_df = df[df["executed"]].copy()
vetoed_df = df[~df["executed"]].copy()

total_trades = len(executed_df)
wins = int(executed_df["win"].sum()) if total_trades > 0 and "win" in executed_df.columns else 0
win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
total_pnl = float(executed_df["pnl"].sum()) if total_trades > 0 else 0.0
sharpe = float(executed_df["sharpe_rolling"].iloc[-1]) if total_trades > 0 else 0.0


# ============================================================
# TABS
# ============================================================

tab_live, tab_score, tab_perf, tab_review, tab_thinking, tab_backtest, tab_pipe, tab_erc = st.tabs(
    ["🔴 Live", "🎯 Decision Score", "📈 Performance", "🔍 Trade Review", "🧠 Thinking", "📊 Backtest", "🔧 Pipeline", "🔗 ERC-8004"]
)

# ==================== TAB 1: LIVE ====================
with tab_live:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Trades", total_trades)
    c2.metric("Win Rate", f"{win_rate:.1f}%")
    c3.metric("PnL ($)", fmt_currency(total_pnl))
    c4.metric("Sharpe Ratio", f"{sharpe:.2f}")

    # G.2++ KB enrichment KPIs (Nogran PA knowledge base + hallucination detector)
    if not df.empty and "kb_setup_id" in df.columns:
        kb_matches = (df["kb_setup_id"] != "").sum()
        kb_match_rate = (kb_matches / max(len(df), 1)) * 100
        alarms = (df["hallucination_severity"] != "").sum()
        critical_alarms = (df["hallucination_severity"] == "critical").sum()

        k1, k2, k3, k4 = st.columns(4)
        k1.metric(
            "KB Match Rate",
            f"{kb_match_rate:.0f}%",
            help="% das decisoes onde o setup do LLM bateu com a KB Nogran PA (62 setups)",
        )
        k2.metric(
            "KB Hits",
            f"{kb_matches}/{len(df)}",
            help="Total de matches absolutos",
        )
        k3.metric(
            "Hallucination Alarms",
            int(alarms),
            help="LLM e Nogran PA divergiram >=25 pts (warning) ou >=40 pts (critical)",
        )
        k4.metric(
            "Critical Alarms",
            int(critical_alarms),
            delta=f"-{critical_alarms}" if critical_alarms else None,
            delta_color="inverse",
            help="Gap >=40 pts entre LLM e Nogran PA — possivel alucinacao grave",
        )

    st.markdown("---")

    if not df.empty:
        latest = df.iloc[-1]
        col_score, col_chart = st.columns([1, 2])

        with col_score:
            st.markdown("#### Latest Decision")
            sv = latest["total_score"]
            css = "score-big" if sv >= 65 else "score-big-red"
            badge = "badge-go" if sv >= 65 else "badge-nogo"
            badge_txt = "GO" if sv >= 65 else "NO-GO"
            st.markdown(
                f'<div style="text-align:center;margin:16px 0;">'
                f'<span class="{css}">{sv}</span>'
                f'<span style="font-size:1.5rem;opacity:0.5;"> / 100</span><br>'
                f'<span class="{badge}" style="margin-top:12px;">{badge_txt}</span></div>',
                unsafe_allow_html=True,
            )
            st.markdown(f"**Action:** {latest['action']}  \n**Setup:** {latest['setup']}")
            st.markdown(f"**Regime:** {latest['regime']}  \n**Day type:** {latest['day_type']}")

            # G.2++ PA KB match + hallucination alarm
            # NOTE: kb_id and kb_cite come from JSONL — rendered via native st.markdown
            # without unsafe_allow_html to eliminate XSS surface.
            kb_id = latest.get("kb_setup_id", "") if isinstance(latest, pd.Series) else ""
            if kb_id:
                kb_pct = latest.get("kb_probability_pct")
                kb_llm = latest.get("kb_llm_score")
                kb_blend = latest.get("kb_blended_score")
                kb_cite = latest.get("kb_citation", "")
                # Native markdown — special chars in kb_id/kb_cite cannot inject HTML
                st.markdown(
                    f"**📚 PA KB:** `{kb_id}` ({kb_pct}%)  \n"
                    f"LLM={kb_llm} → blended={kb_blend}"
                )
                st.caption(f"cite: {kb_cite}")
            else:
                st.markdown("**📚 PA KB:** _no match_")

            severity = latest.get("hallucination_severity", "") if isinstance(latest, pd.Series) else ""
            if severity:
                gap = latest.get("hallucination_gap")
                direction = latest.get("hallucination_direction", "")
                if severity == "critical":
                    st.error(
                        f"🚨 **HALLUCINATION ALARM (critical)** — gap={gap:+d}, {direction}"
                    )
                else:
                    st.warning(
                        f"⚠️ Hallucination warning — gap={gap:+d}, {direction}"
                    )

            rr_warn = latest.get("rr_warning", "") if isinstance(latest, pd.Series) else ""
            if rr_warn:
                st.caption(f"📐 {rr_warn}")

            st.info(f"💬 {latest['reasoning']}")

        with col_chart:
            st.markdown("#### Score Breakdown")
            components = ["Market Quality", "Strategy", "AI Overlay", "Risk"]
            scores = [latest["mq_score"], latest["strat_score"], latest["ai_score"], latest["risk_score"]]
            colors = [score_color(s) for s in scores]

            fig = go.Figure(go.Bar(
                y=components, x=scores, orientation="h",
                marker_color=colors,
                text=[f"{s}/100" for s in scores], textposition="inside",
                textfont=dict(size=14, color="white"),
            ))
            fig.add_vline(x=65, line_dash="dash", line_color="white", opacity=0.4, annotation_text="Threshold")
            fig.update_layout(
                xaxis=dict(range=[0, 100], title="Score"), yaxis=dict(autorange="reversed"),
                height=260, margin=dict(l=0, r=20, t=10, b=30),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="white"),
            )
            st.plotly_chart(fig)

    # --- Candlestick Chart with Trade Markers ---
    st.markdown("---")
    st.markdown("#### Price Action & Trade Entries")

    candles_df = generate_sample_candles(120) if demo_mode else generate_sample_candles(120)  # TODO: replace with real candle data

    fig_candle = go.Figure()

    # Candlestick
    fig_candle.add_trace(go.Candlestick(
        x=candles_df["time"], open=candles_df["open"], high=candles_df["high"],
        low=candles_df["low"], close=candles_df["close"],
        increasing_line_color=GREEN, decreasing_line_color=RED,
        increasing_fillcolor=GREEN, decreasing_fillcolor=RED,
        name="BTC/USD 1m",
    ))

    # BUY markers (green triangle up)
    buys = executed_df[executed_df["action"] == "BUY"]
    if not buys.empty:
        fig_candle.add_trace(go.Scatter(
            x=buys["timestamp"], y=buys["entry_price"],
            mode="markers", name="BUY",
            marker=dict(symbol="triangle-up", size=14, color=GREEN, line=dict(width=1, color="white")),
        ))

    # SELL markers (red triangle down)
    sells = executed_df[executed_df["action"] == "SELL"]
    if not sells.empty:
        fig_candle.add_trace(go.Scatter(
            x=sells["timestamp"], y=sells["entry_price"],
            mode="markers", name="SELL",
            marker=dict(symbol="triangle-down", size=14, color=RED, line=dict(width=1, color="white")),
        ))

    # Vetoed signals (gray X, smaller)
    if not vetoed_df.empty:
        vetoed_with_price = vetoed_df[vetoed_df["entry_price"] > 0]
        if not vetoed_with_price.empty:
            fig_candle.add_trace(go.Scatter(
                x=vetoed_with_price["timestamp"], y=vetoed_with_price["entry_price"],
                mode="markers", name="VETOED",
                marker=dict(symbol="x", size=8, color="gray", opacity=0.5),
            ))

    fig_candle.update_layout(
        height=420,
        xaxis_rangeslider_visible=False,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="white"),
        margin=dict(l=0, r=0, t=10, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
        yaxis=dict(title="BTC/USD", gridcolor="rgba(255,255,255,0.05)"),
        xaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
    )
    st.plotly_chart(fig_candle)

    st.markdown("---")
    st.markdown("#### Recent Decisions")
    last_10 = df.tail(10).iloc[::-1].copy()
    show = last_10[["timestamp", "action", "total_score", "setup", "executed", "pnl"]].copy()
    show.columns = ["Time", "Action", "Score", "Setup", "Executed", "PnL"]
    show["Time"] = show["Time"].dt.strftime("%H:%M:%S")
    show["PnL"] = show["PnL"].apply(lambda x: fmt_currency(x) if pd.notna(x) else "--")
    show["Executed"] = show["Executed"].map({True: "✅", False: "❌"})
    st.dataframe(show, hide_index=True, column_config={"Score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d")})


# ==================== TAB 2: DECISION SCORE ====================
with tab_score:
    st.markdown("#### The Decision Scoring System")
    st.markdown(
        "Four independent engines evaluate every opportunity: "
        "**Market Quality** (20%), **Strategy** (35%), **AI Overlay** (20%), **Risk** (25%). "
        "Only when the composite score exceeds **65/100** does the agent act."
    )
    st.markdown("")

    st.markdown("##### Scores Over Time")
    fig_scatter = px.scatter(
        df, x="timestamp", y="total_score", color="executed",
        color_discrete_map={True: GREEN, False: RED},
        labels={"total_score": "Decision Score", "timestamp": "Time", "executed": "Executed"},
        hover_data=["action", "setup", "regime"], opacity=0.85,
    )
    fig_scatter.add_hline(y=65, line_dash="dash", line_color=YELLOW, opacity=0.6, annotation_text="GO threshold")
    fig_scatter.update_layout(
        height=350, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="white"), margin=dict(l=0, r=0, t=10, b=0),
    )
    fig_scatter.update_traces(marker=dict(size=10, line=dict(width=1, color="white")))
    st.plotly_chart(fig_scatter)

    col_hist, col_radar = st.columns(2)

    with col_hist:
        st.markdown("##### Score Distribution")
        fig_hist = px.histogram(df, x="total_score", nbins=20, color_discrete_sequence=[GREEN], labels={"total_score": "Decision Score"})
        fig_hist.add_vline(x=65, line_dash="dash", line_color=YELLOW, opacity=0.6)
        fig_hist.update_layout(height=300, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="white"), showlegend=False, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig_hist)

    with col_radar:
        st.markdown("##### Average Sub-Scores")
        cats = ["Market Quality", "Strategy", "AI Overlay", "Risk"]
        avgs = [df["mq_score"].mean(), df["strat_score"].mean(), df["ai_score"].mean(), df["risk_score"].mean()]
        fig_radar = go.Figure()
        fig_radar.add_trace(go.Scatterpolar(
            r=avgs + [avgs[0]], theta=cats + [cats[0]],
            fill="toself", fillcolor="rgba(29,185,84,0.2)", line=dict(color=GREEN, width=2), marker=dict(size=8), name="Average",
        ))
        fig_radar.add_trace(go.Scatterpolar(
            r=[65, 65, 65, 65, 65], theta=cats + [cats[0]],
            line=dict(color=YELLOW, width=1, dash="dash"), name="Threshold", fill=None,
        ))
        fig_radar.update_layout(
            polar=dict(
                radialaxis=dict(visible=True, range=[0, 100], gridcolor="rgba(255,255,255,0.1)"),
                bgcolor="rgba(0,0,0,0)",
                angularaxis=dict(gridcolor="rgba(255,255,255,0.1)"),
            ),
            height=300, paper_bgcolor="rgba(0,0,0,0)", font=dict(color="white"),
            margin=dict(l=40, r=40, t=10, b=10), showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=-0.15, xanchor="center", x=0.5),
        )
        st.plotly_chart(fig_radar)

    st.markdown("##### Vetoed Decisions")
    if not vetoed_df.empty:
        veto_show = vetoed_df[["timestamp", "action", "total_score", "setup", "veto_reason", "reasoning"]].copy()
        veto_show.columns = ["Time", "Action", "Score", "Setup", "Veto Reason", "Reasoning"]
        veto_show["Time"] = veto_show["Time"].dt.strftime("%Y-%m-%d %H:%M")
        st.dataframe(veto_show, hide_index=True)
    else:
        st.info("No vetoed trades yet.")


# ==================== TAB 3: PERFORMANCE ====================
with tab_perf:
    ex = executed_df.dropna(subset=["pnl"]).copy() if not executed_df.empty else pd.DataFrame()

    if ex.empty:
        st.warning("No executed trades with PnL data yet.")
    else:
        ex["cum_pnl"] = ex["pnl"].cumsum()

        st.markdown("#### Equity Curve")
        fig_eq = go.Figure(go.Scatter(
            x=ex["timestamp"], y=ex["cum_pnl"], mode="lines+markers",
            line=dict(color=GREEN, width=3), marker=dict(size=6),
            fill="tozeroy", fillcolor="rgba(29,185,84,0.1)", name="Cumulative PnL",
        ))
        fig_eq.update_layout(yaxis_title="Cumulative PnL ($)", height=320, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="white"), margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig_eq)

        col_dd, col_wr = st.columns(2)

        with col_dd:
            st.markdown("#### Drawdown")
            peak = ex["cum_pnl"].cummax()
            dd = ex["cum_pnl"] - peak
            fig_dd = go.Figure(go.Scatter(
                x=ex["timestamp"], y=dd, mode="lines", fill="tozeroy",
                fillcolor="rgba(231,76,60,0.25)", line=dict(color=RED, width=2),
            ))
            fig_dd.update_layout(yaxis_title="Drawdown ($)", height=250, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="white"), margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig_dd)

        with col_wr:
            st.markdown("#### Rolling Win Rate (10 trades)")
            if len(ex) >= 2:
                window = min(10, len(ex))
                ex["rolling_wr"] = ex["win"].astype(float).rolling(window, min_periods=1).mean() * 100
                fig_wr = go.Figure(go.Scatter(
                    x=ex["timestamp"], y=ex["rolling_wr"], mode="lines+markers",
                    line=dict(color=BLUE, width=2), marker=dict(size=5),
                ))
                fig_wr.add_hline(y=50, line_dash="dash", line_color=YELLOW, opacity=0.5)
                fig_wr.update_layout(yaxis_title="Win Rate %", yaxis=dict(range=[0, 100]), height=250, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="white"), margin=dict(l=0, r=0, t=10, b=0))
                st.plotly_chart(fig_wr)
            else:
                st.info("Need at least 2 trades.")

        st.markdown("#### Trade Distribution")
        wins_n = int(ex["win"].sum())
        losses_n = len(ex) - wins_n
        fig_wl = go.Figure(go.Bar(
            x=["Wins", "Losses"], y=[wins_n, losses_n], marker_color=[GREEN, RED],
            text=[wins_n, losses_n], textposition="outside", textfont=dict(size=16, color="white"),
        ))
        fig_wl.update_layout(height=250, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="white"), margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig_wl)

        st.markdown("#### Key Metrics")
        wins_pnl = ex.loc[ex["win"] == True, "pnl"]
        losses_pnl = ex.loc[ex["win"] == False, "pnl"]
        avg_win = float(wins_pnl.mean()) if len(wins_pnl) > 0 else 0
        avg_loss = float(abs(losses_pnl.mean())) if len(losses_pnl) > 0 else 0
        gross_win = float(wins_pnl.sum()) if len(wins_pnl) > 0 else 0
        gross_loss = float(abs(losses_pnl.sum())) if len(losses_pnl) > 0 else 1
        pf = gross_win / gross_loss if gross_loss > 0 else 0
        expect = float(ex["pnl"].mean()) if len(ex) > 0 else 0
        max_dd = float(dd.min()) if len(dd) > 0 else 0
        max_cl = 0
        cl = 0
        for w in ex["win"]:
            if not w:
                cl += 1
                max_cl = max(max_cl, cl)
            else:
                cl = 0

        m1, m2, m3, m4, m5, m6 = st.columns(6)
        m1.metric("Profit Factor", f"{pf:.2f}")
        m2.metric("Expectancy", fmt_currency(expect))
        m3.metric("Max Drawdown", fmt_currency(max_dd))
        m4.metric("Avg Win", fmt_currency(avg_win))
        m5.metric("Avg Loss", fmt_currency(-avg_loss))
        m6.metric("Max Consec. Losses", max_cl)


# ==================== TAB 4: TRADE REVIEW ====================
with tab_review:
    st.markdown("#### Trade Review & Analysis")
    st.markdown("Filter and analyze individual decisions. Contest the agent's reasoning.")
    st.markdown("")

    # Filters
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        date_filter = st.date_input("Date", value=None)
    with col_f2:
        action_filter = st.multiselect("Action", ["BUY", "SELL", "WAIT"], default=["BUY", "SELL", "WAIT"])
    with col_f3:
        score_range = st.slider("Score Range", 0, 100, (0, 100))

    # Apply filters
    filtered = df.copy()
    if date_filter:
        filtered = filtered[filtered["timestamp"].dt.date == date_filter]
    if action_filter:
        filtered = filtered[filtered["action"].isin(action_filter)]
    filtered = filtered[
        (filtered["total_score"] >= score_range[0]) & (filtered["total_score"] <= score_range[1])
    ]

    # Summary stats for filtered set
    f_executed = filtered[filtered["executed"]]
    f_wins = int(f_executed["win"].sum()) if len(f_executed) > 0 else 0
    f_total = len(f_executed)
    f_wr = (f_wins / f_total * 100) if f_total > 0 else 0

    sc1, sc2, sc3, sc4 = st.columns(4)
    sc1.metric("Filtered Decisions", len(filtered))
    sc2.metric("Executed", f_total)
    sc3.metric("Win Rate", f"{f_wr:.0f}%")
    if f_total > 0:
        avg_win_score = f_executed.loc[f_executed["win"] == True, "total_score"].mean() if f_wins > 0 else 0
        avg_loss_score = f_executed.loc[f_executed["win"] == False, "total_score"].mean() if f_total > f_wins else 0
        sc4.metric("Avg Score (Win vs Loss)", f"{avg_win_score:.0f} vs {avg_loss_score:.0f}")
    else:
        sc4.metric("Avg Score (Win vs Loss)", "--")

    st.markdown("---")

    # Decision table with expandable details
    if filtered.empty:
        st.info("No decisions match the filters.")
    else:
        for _idx, row in filtered.iloc[::-1].iterrows():
            ts_str = row["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
            exec_icon = "✅" if row["executed"] else "❌"
            pnl_str = fmt_currency(row["pnl"]) if pd.notna(row.get("pnl")) else "--"
            score_val = row["total_score"]

            # Color the score
            if score_val >= 65:
                score_html = f'<span style="color:{GREEN};font-weight:700;">{score_val:.0f}</span>'
            elif score_val >= 40:
                score_html = f'<span style="color:{YELLOW};font-weight:700;">{score_val:.0f}</span>'
            else:
                score_html = f'<span style="color:{RED};font-weight:700;">{score_val:.0f}</span>'

            action_color = GREEN if row["action"] == "BUY" else RED if row["action"] == "SELL" else YELLOW

            with st.expander(f"{ts_str}  |  {exec_icon}  **{row['action']}**  |  Score: {score_val:.0f}  |  {row['setup']}  |  PnL: {pnl_str}"):
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**Decision Breakdown:**")
                    st.markdown(f"- Market Quality: **{row['mq_score']}**/100")
                    st.markdown(f"- Strategy: **{row['strat_score']}**/100")
                    st.markdown(f"- AI Overlay: **{row['ai_score']}**/100")
                    st.markdown(f"- Risk: **{row['risk_score']}**/100")
                    st.markdown(f"- **Total: {score_val:.1f}**/100")
                    if row["veto_reason"]:
                        st.error(f"Veto: {row['veto_reason']}")
                with c2:
                    st.markdown("**Trade Details:**")
                    st.markdown(f"- Setup: {row['setup']}")
                    st.markdown(f"- Day Type: {row['day_type']}")
                    st.markdown(f"- Regime: {row['regime']}")
                    st.markdown(f"- Entry: ${row['entry_price']:,.2f}")
                    st.markdown(f"- Stop: ${row['stop_loss']:,.2f}")
                    st.markdown(f"- Target: ${row['take_profit']:,.2f}")
                    st.markdown(f"- R/R: {row['reward_risk_ratio']:.1f}")

                st.markdown("**Reasoning:**")
                st.info(row["reasoning"])

                if row.get("fact_preview"):
                    st.markdown("**Market Fact (sent to LLM):**")
                    st.code(row["fact_preview"], language=None)


# ==================== TAB 5: THINKING ====================
with tab_thinking:
    st.markdown("#### 🧠 Agent Thought Stream")
    st.markdown(
        "O que o agente *pensa* a cada candle. Cada passo do pipeline emite "
        "uma narrativa estilo Nogran PA. Quando um estagio contradiz outro, "
        "o agente **muda de ideia** (revisao). Veja o pipeline completo de "
        "raciocinio, do feature engine ao decision scorer."
    )

    streams = load_thought_streams()

    if not streams:
        st.info(
            "Nenhum thought stream disponivel ainda. "
            "Rode `python scripts/simulate_market.py` para gerar uma auditoria sintetica, "
            "ou inicie o agente em modo live."
        )
    else:
        # KPIs
        total_streams = len(streams)
        with_revisions = sum(1 for s in streams if s.get("revision_count", 0) > 0)
        with_alarms = sum(1 for s in streams if s.get("has_alarm"))
        with_vetoes = sum(1 for s in streams if s.get("has_veto"))
        total_thoughts = sum(s.get("thought_count", 0) for s in streams)

        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Streams", total_streams)
        k2.metric("Total Thoughts", total_thoughts)
        k3.metric("Mind Changes", with_revisions, help="Streams onde o agente revisou uma hipotese")
        k4.metric("Alarms", with_alarms, help="Streams com hallucination alarm")
        k5.metric("Vetoes", with_vetoes, help="Streams com hard veto (pre-filter ou risk)")

        st.markdown("---")

        # Filter controls
        f1, f2, f3 = st.columns([2, 2, 1])
        with f1:
            filter_type = st.selectbox(
                "Filtrar por",
                ["Todos", "Com mudanca de ideia", "Com alarme", "Com veto", "GO clean"],
            )
        with f2:
            sort_order = st.selectbox("Ordem", ["Mais recentes", "Por candle index", "Mais revisoes"])
        with f3:
            limit = st.number_input("Mostrar", min_value=1, max_value=50, value=10, step=1)

        filtered = streams
        if filter_type == "Com mudanca de ideia":
            filtered = [s for s in streams if s.get("revision_count", 0) > 0]
        elif filter_type == "Com alarme":
            filtered = [s for s in streams if s.get("has_alarm")]
        elif filter_type == "Com veto":
            filtered = [s for s in streams if s.get("has_veto")]
        elif filter_type == "GO clean":
            filtered = [
                s for s in streams
                if s.get("revision_count", 0) == 0 and not s.get("has_veto") and not s.get("has_alarm")
            ]

        if sort_order == "Mais recentes":
            filtered = list(reversed(filtered))
        elif sort_order == "Por candle index":
            filtered = sorted(filtered, key=lambda s: s.get("candle_index", 0))
        elif sort_order == "Mais revisoes":
            filtered = sorted(filtered, key=lambda s: -s.get("revision_count", 0))

        st.caption(f"Mostrando {min(limit, len(filtered))} de {len(filtered)} streams")
        st.markdown("---")

        # Stage badges colors
        STAGE_BADGES = {
            "feature": ("📊", "#3498db"),
            "pre_filter": ("🚦", "#9b59b6"),
            "strategy": ("🧠", "#1DB954"),
            "kb_lookup": ("📚", "#16a085"),
            "ai_overlay": ("🤖", "#e67e22"),
            "risk": ("🛡️", "#E74C3C"),
            "decision": ("🎯", "#F39C12"),
            "execution": ("⚡", "#2c3e50"),
            "meta": ("📋", "#7f8c8d"),
        }
        TYPE_ICONS = {
            "observation": "•",
            "hypothesis": "💭",
            "revision": "🔄",
            "veto": "⛔",
            "decision": "✅",
            "alarm": "🚨",
        }

        for s in filtered[:limit]:
            ci = s.get("candle_index", "?")
            n_th = s.get("thought_count", 0)
            n_rev = s.get("revision_count", 0)
            badges = []
            if s.get("has_alarm"):
                badges.append("🚨 alarm")
            if s.get("has_veto"):
                badges.append("⛔ veto")
            if n_rev > 0:
                badges.append(f"🔄 {n_rev} revisao(oes)")
            badge_str = " · ".join(badges) if badges else "✅ clean"

            with st.expander(f"Candle #{ci}  ·  {n_th} thoughts  ·  {badge_str}"):
                # Build a thought map for revision lookups
                tmap = {t["id"]: t for t in s.get("thoughts", [])}

                for t in s.get("thoughts", []):
                    stage = t.get("stage", "?")
                    icon, color = STAGE_BADGES.get(stage, ("?", "#999"))
                    type_icon = TYPE_ICONS.get(t.get("type", ""), "•")
                    text = t.get("text_pt", "")
                    concepts = t.get("concepts", [])
                    confidence = t.get("confidence", 50)

                    # Revision link
                    revision_note = ""
                    if t.get("revision_of"):
                        original = tmap.get(t["revision_of"])
                        if original:
                            orig_short = (original.get("text_pt", "") or "")[:60]
                            revision_note = f"_revisa: \"{html_escape(orig_short)}...\"_"

                    # Render row
                    st.markdown(
                        f"{icon} `{stage:>10}` {type_icon} **{html_escape(text)}**"
                    )
                    extras = []
                    if concepts:
                        concept_tags = " ".join(
                            f"`{html_escape(c)}`" for c in concepts[:5]
                        )
                        extras.append(f"📚 {concept_tags}")
                    extras.append(f"conf {confidence}%")
                    if revision_note:
                        extras.append(revision_note)
                    st.caption(" · ".join(extras))


# ==================== TAB 6: PIPELINE ====================
with tab_pipe:
    st.markdown("#### The 5-Stage Decision Pipeline")
    st.markdown("Every decision flows through 5 stages. Each can veto. No overrides.")
    st.markdown("")

    stages = [
        ("📊", "1. PERCEPTION", "Kraken WebSocket OHLCV. EMA(20), ATR(14), ADX(14). Mathematical facts only.", BLUE),
        ("🧠", "2. RAG TOP-DOWN", "5-layer Nogran PA analysis: Day Type → Macro → Structure → Micro → Setup.", PURPLE),
        ("🎯", "3. DECISION SCORE", "4-component weighted score. MQ 20% + Strategy 35% + AI 20% + Risk 25%. Threshold: 65.", GREEN),
        ("🛡️", "4. RISK ENGINE", "Independent. Position sizing, drawdown bands, circuit breakers. Can override any GO.", "#e67e22"),
        ("⚡", "5. EXECUTION", "ERC-8004 signing → Kraken CLI. OCO orders. Fill verification.", RED),
    ]

    cols = st.columns(5)
    for col, (icon, name, desc, color) in zip(cols, stages, strict=True):
        with col:
            st.markdown(
                f'<div class="pipeline-card" style="border-color:{color}40;">'
                f'<div style="font-size:2rem;text-align:center;">{icon}</div>'
                f'<h4 style="color:{color};text-align:center;font-size:0.82rem;">{name}</h4>'
                f'<p>{desc}</p></div>',
                unsafe_allow_html=True,
            )

    st.markdown("---")
    st.markdown("#### 7 Layers Against Hallucination")

    layers = [
        ("Mathematical Facts Only", "OHLCV computed by Python. LLM never sees raw data."),
        ("RAG Top-Down (not Bottom-Up)", "Macro context determines micro meaning. Never the reverse."),
        ("5 Isolated pgvector Tables", "Chunks from different layers cannot contaminate each other."),
        ("Temperature 0.1", "Minimal LLM creativity. Consistency over novelty."),
        ("JSON Validator + R/R Gate", "Malformed output or R/R < 1.5 = forced WAIT."),
        ("AI Overlay Post-LLM", "Python verifies coherence with real market data."),
        ("Decision Score < 65 = Veto", "Insufficient quality never passes. No exceptions."),
    ]
    for i, (title, desc) in enumerate(layers, 1):
        st.markdown(f'<div class="check-item">✅ <b>Layer {i}: {title}</b><br><span style="opacity:0.7;font-size:0.85rem;margin-left:28px;">{desc}</span></div>', unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("#### The Pitch")
    st.markdown(
        "> **nogran.trader.agent** combines Nogran PA' Price Action with a 4-component Decision Scoring System, "
        "an independent Risk Engine, and ERC-8004 on-chain trust. "
        "It knows exactly when to trade — and when **not** to."
    )


# ==================== TAB: BACKTEST ====================
with tab_backtest:
    st.markdown("#### 📊 Backtest Results — Hackathon Ranking Metrics")
    st.markdown(
        "Backtests sao gerados por `python scripts/backtest.py`. "
        "Cada run cria `logs/backtest/<run_id>/` com `summary.json`, `trades.jsonl`, `equity.csv`."
    )

    # Discover available runs
    BT_BASE = Path(__file__).resolve().parents[1] / "logs" / "backtest"
    bt_runs = sorted([p for p in BT_BASE.iterdir() if p.is_dir() and (p / "summary.json").exists()],
                     reverse=True) if BT_BASE.exists() else []

    if not bt_runs:
        st.info(
            "Nenhum backtest run encontrado em `logs/backtest/`.\n\n"
            "Rode: `python scripts/backtest.py --source ccxt --exchange binance "
            "--symbol BTC/USDT --timeframe 5m --days 30`"
        )
    else:
        run_labels = [p.name for p in bt_runs]
        sel = st.selectbox(
            "Selecione um run:",
            options=run_labels,
            index=0,
            help=f"Total: {len(bt_runs)} runs disponiveis",
        )
        sel_dir = bt_runs[run_labels.index(sel)]

        # Load summary
        with open(sel_dir / "summary.json", encoding="utf-8") as f:
            bt_summary = json.load(f)

        # Load trades
        bt_trades = []
        trades_path = sel_dir / "trades.jsonl"
        if trades_path.exists():
            with open(trades_path, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        bt_trades.append(json.loads(line))

        # Load equity curve
        equity_df = None
        equity_path = sel_dir / "equity.csv"
        if equity_path.exists():
            equity_df = pd.read_csv(equity_path)
            equity_df["dt"] = pd.to_datetime(equity_df["timestamp"], unit="ms")

        # Top KPI cards
        m = bt_summary.get("metrics", {})
        pnl_block = m.get("pnl", {})
        risk_block = m.get("risk", {})
        trades_block = m.get("trades", {})
        baseline_block = m.get("baseline", {})
        meta_block = m.get("meta", {})

        st.markdown("##### Key Metrics")
        k1, k2, k3, k4 = st.columns(4)
        pnl_pct_disp = pnl_block.get("total_pnl_pct", 0) * 100
        k1.metric(
            "Net PnL",
            f"${pnl_block.get('total_pnl', 0):,.2f}",
            f"{pnl_pct_disp:+.2f}%",
            delta_color="normal" if pnl_pct_disp >= 0 else "inverse",
        )
        sharpe_v = risk_block.get("sharpe_ratio", 0)
        k2.metric(
            "Sharpe (ann.)",
            f"{sharpe_v:.2f}",
            help="Annualized Sharpe ratio. > 1 = good, > 2 = excellent, < 0 = losing",
        )
        k3.metric(
            "Max Drawdown",
            f"{risk_block.get('max_drawdown_pct', 0):.2f}%",
            help="Peak-to-trough max equity drawdown",
        )
        k4.metric(
            "Win Rate",
            f"{trades_block.get('win_rate', 0)*100:.1f}%",
            f"{trades_block.get('num_wins', 0)}W / {trades_block.get('num_losses', 0)}L",
        )

        k5, k6, k7, k8 = st.columns(4)
        pf = trades_block.get("profit_factor", 0)
        pf_str = "∞" if pf == float("inf") or pf > 1e6 else f"{pf:.2f}"
        k5.metric("Profit Factor", pf_str, help="Total wins / total losses. > 1 = profitable")
        cal = risk_block.get("calmar_ratio", 0)
        cal_str = "∞" if cal == float("inf") or cal > 1e6 else f"{cal:.2f}"
        k6.metric("Calmar Ratio", cal_str, help="CAGR / MaxDD. > 1 = good")
        k7.metric("Sortino", f"{risk_block.get('sortino_ratio', 0):.2f}",
                  help="Downside-only Sharpe variant")
        k8.metric("# Trades", f"{trades_block.get('num_trades', 0)}",
                  help=f"Period: {meta_block.get('period_days', 0):.1f} days, "
                       f"{meta_block.get('bars_processed', 0)} bars")

        # Buy-and-hold comparison
        st.markdown("##### Strategy vs Buy-and-Hold")
        a1, a2, a3 = st.columns(3)
        bh_pct = baseline_block.get("buy_hold_pnl_pct", 0) * 100
        alpha_pct = baseline_block.get("alpha_vs_buy_hold", 0) * 100
        a1.metric("Strategy PnL", f"{pnl_pct_disp:+.2f}%")
        a2.metric("Buy-and-Hold PnL", f"{bh_pct:+.2f}%")
        a3.metric(
            "Alpha vs B&H",
            f"{alpha_pct:+.2f}%",
            delta_color="normal" if alpha_pct >= 0 else "inverse",
        )

        # Equity curve plot
        if equity_df is not None and len(equity_df) > 1:
            st.markdown("##### Equity Curve")
            initial = pnl_block.get("initial_capital", 10000)
            first_close = bt_summary.get("config", {}).get("first_close", None)
            # Build buy-and-hold curve from equity_df timestamps
            # We don't have the underlying close prices here, so approximate via baseline pct
            bh_final = initial * (1 + baseline_block.get("buy_hold_pnl_pct", 0))
            bh_curve = [initial + (bh_final - initial) * (i / max(len(equity_df) - 1, 1))
                        for i in range(len(equity_df))]

            fig_eq = go.Figure()
            fig_eq.add_trace(go.Scatter(
                x=equity_df["dt"], y=equity_df["equity"],
                mode="lines", name="Strategy",
                line=dict(color=BLUE, width=2),
            ))
            fig_eq.add_trace(go.Scatter(
                x=equity_df["dt"], y=bh_curve,
                mode="lines", name="Buy-and-Hold (linear)",
                line=dict(color=YELLOW, width=1, dash="dash"),
            ))
            # Initial capital reference line
            fig_eq.add_hline(y=initial, line_dash="dot", line_color="gray",
                             annotation_text="Initial", annotation_position="bottom right")
            fig_eq.update_layout(
                height=380,
                margin=dict(l=10, r=10, t=10, b=10),
                xaxis_title="Time",
                yaxis_title="Equity ($)",
                legend=dict(orientation="h", y=1.1),
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_eq, use_container_width=True)

            # Drawdown overlay
            st.markdown("##### Drawdown")
            fig_dd = go.Figure()
            fig_dd.add_trace(go.Scatter(
                x=equity_df["dt"], y=-equity_df["drawdown"] * 100,
                mode="lines", name="Drawdown",
                fill="tozeroy",
                line=dict(color=RED, width=1),
                fillcolor="rgba(255,99,71,0.25)",
            ))
            fig_dd.update_layout(
                height=200,
                margin=dict(l=10, r=10, t=10, b=10),
                xaxis_title="Time",
                yaxis_title="Drawdown (%)",
                showlegend=False,
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_dd, use_container_width=True)

        # Trades scatter
        if bt_trades:
            st.markdown("##### Trades — colored by KB match + alarm")
            trades_df = pd.DataFrame(bt_trades)
            trades_df["entry_dt"] = pd.to_datetime(trades_df["entry_time"], unit="ms")

            # Color by hallucination_severity (None=blue, warning=yellow, critical=red)
            def _color(row):
                sev = row.get("hallucination_severity")
                if sev == "critical":
                    return RED
                if sev == "warning":
                    return YELLOW
                if row.get("kb_match_id"):
                    return BLUE
                return "#888888"

            trades_df["color"] = trades_df.apply(_color, axis=1)

            fig_tr = go.Figure()
            fig_tr.add_trace(go.Scatter(
                x=trades_df["entry_dt"],
                y=trades_df["pnl"],
                mode="markers",
                marker=dict(
                    size=8,
                    color=trades_df["color"],
                    line=dict(width=0.5, color="white"),
                ),
                text=trades_df.apply(
                    lambda r: f"{r['side'].upper()} | {r.get('kb_match_id', 'no_match')} | "
                              f"exit={r['exit_reason']} | RR={r.get('rr_realized', 0):.2f}",
                    axis=1
                ),
                hovertemplate="%{text}<br>PnL: $%{y:.2f}<extra></extra>",
                name="Trades",
            ))
            fig_tr.add_hline(y=0, line_dash="dot", line_color="gray")
            fig_tr.update_layout(
                height=320,
                margin=dict(l=10, r=10, t=10, b=10),
                xaxis_title="Entry Time",
                yaxis_title="PnL ($)",
                showlegend=False,
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_tr, use_container_width=True)

            # Aggregate by setup (KB match)
            st.markdown("##### KB Setup Performance (Hallucination × PnL)")
            if "kb_match_id" in trades_df.columns:
                setup_stats = trades_df.groupby(
                    trades_df["kb_match_id"].fillna("no_match")
                ).agg(
                    n=("pnl", "size"),
                    win_rate=("pnl", lambda s: (s > 0).mean()),
                    total_pnl=("pnl", "sum"),
                    avg_pnl=("pnl", "mean"),
                ).reset_index().sort_values("n", ascending=False)
                setup_stats["win_rate"] = (setup_stats["win_rate"] * 100).round(1)
                setup_stats["total_pnl"] = setup_stats["total_pnl"].round(2)
                setup_stats["avg_pnl"] = setup_stats["avg_pnl"].round(2)
                st.dataframe(setup_stats, use_container_width=True, hide_index=True)

        # Tuning + config used
        st.markdown("##### Tuning Used")
        tn = bt_summary.get("tuning", {})
        cfg = bt_summary.get("config", {})
        c1, c2 = st.columns(2)
        c1.json(tn)
        c2.json(cfg)

        # Validation post status (if exists)
        vp_path = sel_dir / "validation_post.json"
        if vp_path.exists():
            with open(vp_path, encoding="utf-8") as f:
                vp = json.load(f)
            st.markdown("##### Validation Post")
            score = vp.get("score", "?")
            tx = vp.get("tx", None)
            dry = vp.get("dry_run", False)
            badge = "🟡 DRY-RUN" if dry else "🟢 ON-CHAIN"
            st.markdown(f"**Status:** {badge}  ·  **Score:** `{score}/100`")
            if tx:
                st.markdown(f"**Tx hash:** `{tx}`  [View on Sepolia Explorer ↗](https://sepolia.etherscan.io/tx/{tx})")
            br = vp.get("breakdown", {})
            if br:
                bcols = st.columns(3)
                bcols[0].metric("PnL component", f"{br.get('pnl_component', 0):.0f}/100")
                bcols[1].metric("Quality component", f"{br.get('quality_component', 0):.0f}/100")
                bcols[2].metric("Risk discipline", f"{br.get('risk_component', 0):.0f}/100")


# ==================== TAB 6: ERC-8004 ====================
with tab_erc:
    st.markdown("#### ERC-8004 — On-Chain Agent Identity & Trust")
    st.markdown("Every trade intent is cryptographically signed before execution.")
    st.markdown("")

    col_id, col_stats = st.columns([2, 1])
    with col_id:
        st.markdown(
            '<div class="erc-card">'
            "<h4 style='color:#3498db;margin:0 0 12px 0;'>🆔 Agent Identity</h4>"
            f"<b>Name:</b> {AGENT_ID}<br>"
            f"<b>Standard:</b> ERC-8004<br>"
            f"<b>Network:</b> Sepolia (Chain ID: 11155111)<br>"
            f"<b>Address:</b> <code>{AGENT_ADDRESS}</code><br>"
            f'<a href="{EXPLORER_URL}{AGENT_ADDRESS}" target="_blank" style="color:#3498db;">View on Explorer ↗</a>'
            "</div>",
            unsafe_allow_html=True,
        )
    with col_stats:
        signed_n = len(df[df["erc8004_signature"] != ""])
        exec_signed = len(df[(df["erc8004_signature"] != "") & df["executed"]])
        st.markdown(
            '<div class="erc-card">'
            "<h4 style='color:#3498db;margin:0 0 12px 0;'>📊 Stats</h4>"
            f'<div style="font-size:2.5rem;font-weight:800;color:{GREEN};">{signed_n}</div>'
            f"<div>Signed Intents</div>"
            f'<div style="margin-top:8px;font-size:1.5rem;font-weight:700;color:{BLUE};">{exec_signed}</div>'
            f"<div>Executed</div></div>",
            unsafe_allow_html=True,
        )

    st.markdown("#### Recent Signed Intents")
    signed_df = df[df["erc8004_signature"] != ""].tail(5).iloc[::-1]
    if signed_df.empty:
        st.info("No signed intents yet.")
    else:
        for _, row in signed_df.iterrows():
            # Escape any string that originates from JSONL (defense-in-depth XSS)
            sig = row["erc8004_signature"]
            sig_short = f"{sig[:18]}...{sig[-12:]}" if len(sig) > 30 else sig
            sig_short_safe = html_escape(sig_short)
            action_safe = html_escape(str(row["action"]))
            icon = "✅" if row["executed"] else "❌"
            ac = GREEN if row["action"] == "BUY" else RED if row["action"] == "SELL" else YELLOW
            ts_str = row["timestamp"].strftime("%Y-%m-%d %H:%M:%S")  # strftime output is ASCII-safe
            st.markdown(
                f'<div class="erc-card" style="padding:14px;">'
                f'<span style="color:{ac};font-weight:700;">{action_safe}</span> '
                f'{icon} <span style="opacity:0.6;font-size:0.85rem;">{ts_str}</span> '
                f'· Score: <b>{row["total_score"]}</b> · Entry: ${row["entry_price"]:,.2f}'
                f'<div class="sig-preview" style="margin-top:8px;">🔒 {sig_short_safe}</div></div>',
                unsafe_allow_html=True,
            )

    st.markdown("---")
    st.markdown(
        "**How it works:** Before execution, the agent signs a `TradeIntent` (EIP-712) containing "
        "action, price, size, and Decision Score. This creates a verifiable chain of autonomous decisions."
    )

# --- Footer ---
st.markdown("---")
st.markdown('<div style="text-align:center;opacity:0.4;font-size:0.8rem;">nogran.trader.agent v3 · AI Trading Agent Hackathon · Built with discipline, not hype</div>', unsafe_allow_html=True)
