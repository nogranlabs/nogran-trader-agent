import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    """Application configuration loaded from environment variables."""

    # Required env vars
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

    # Debug mode — gates verbose stack traces in logs (default OFF for prod)
    DEBUG: bool = os.getenv("AGENT_DEBUG", "0").lower() in ("1", "true", "yes")

    # Optional env vars (ERC-8004 agent identity)
    ERC8004_PRIVATE_KEY: str = os.getenv("ERC8004_PRIVATE_KEY", "")
    ERC8004_AGENT_URI: str = os.getenv("ERC8004_AGENT_URI", "")

    # Trading pair and timeframes
    # NOTE: Sub-5min timeframes are too noisy for the Nogran price action pipeline.
    # 2026-04-09: bumped exec from 5m to 15m. Reasons:
    #   1. 3x fewer LLM calls (cost ~$14/mo vs ~$43/mo on OpenAI)
    #   2. EMA(20) covers 5h vs 100min → much more structural context per call
    #   3. Less noise → fewer false setups (ATR/overlap/ADX more stable)
    #   4. Higher TFs give better structural reliability on BTC/USD
    # Confirm TF stays 15m (same as exec now — single TF mode); upgrade to 1h later if needed.
    TRADING_PAIR: str = "BTC/USD"
    TIMEFRAME_EXEC: str = "15m"
    TIMEFRAME_CONFIRM: str = "15m"

    # Risk management
    RISK_PER_TRADE: float = 0.01
    INITIAL_CAPITAL: float = 10000.0

    # Decision parameters
    DECISION_THRESHOLD: int = 65
    MAX_TRADES_PER_HOUR: int = 4
    COOLDOWN_CANDLES: int = 2
    # 2026-04-09: bumped from 30 → 16. On 15m exec timeframe that's 4h max hold
    # (was 7.5h). Empirical: in v1.5 2880c backtest 5 of 12 trades expired in
    # full 7.5h without hitting stop or target — targets were ambitious enough
    # that price never reached them. 4h is the realistic intraday ceiling.
    MAX_POSITION_TIME_CANDLES: int = 16
    MIN_REWARD_RISK: float = 1.5
    ATR_STOP_MULTIPLIER: float = 1.5

    # Trading Sessions (UTC hours)
    # BTC/USD adapts Nogran price action methodology to crypto market sessions
    AGGRESSIVE_START: float = 13.5   # 13:30 UTC (NY open 9:30 ET)
    AGGRESSIVE_END: float = 21.0     # 21:00 UTC (NY close 5:00 ET)
    CONSERVATIVE_START: float = 7.0  # 07:00 UTC (London open)
    CONSERVATIVE_END: float = 13.5   # 13:30 UTC (before NY)
    # 21:00-07:00 UTC = OBSERVATION (no trading)

    # Session-specific parameters
    AGGRESSIVE_THRESHOLD: int = 65
    AGGRESSIVE_SIZING_MULT: float = 1.0
    CONSERVATIVE_THRESHOLD: int = 75
    CONSERVATIVE_SIZING_MULT: float = 0.6
    CONSERVATIVE_SETUPS: list = [
        "second_entry_H2", "breakout_pullback",  # only highest quality
    ]

    # Blockchain (Sepolia Testnet — hackathon shared contracts)
    SEPOLIA_RPC: str = os.getenv("SEPOLIA_RPC", "https://rpc.sepolia.org")
    CHAIN_ID: int = 11155111
    # Hackathon shared contract addresses (Sepolia)
    AGENT_REGISTRY: str = "0x97b07dDc405B0c28B17559aFFE63BdB3632d0ca3"
    HACKATHON_VAULT: str = "0x0E7CD8ef9743FEcf94f9103033a044caBD45fC90"
    RISK_ROUTER: str = "0xd6A6952545FF6E6E6681c2d15C59f9EB8F40FdBC"
    REPUTATION_REGISTRY: str = "0x423a9904e39537a9997fbaF0f220d79D7d545763"
    VALIDATION_REGISTRY: str = "0x92bF63E5C7Ac6980f237a7164Ab413BE226187F1"
