import json
import logging
import re
import subprocess

logger = logging.getLogger(__name__)


# Defensive: cap stderr length and strip absolute paths to mitigate info disclosure.
_MAX_STDERR_CHARS = 300
_PATH_PATTERNS = [
    re.compile(r"[A-Za-z]:\\\S+"),       # C:\Users\... -> <path>
    re.compile(r"/home/[^\s/]+/\S+"),    # /home/user/... -> <path>
    re.compile(r"/Users/[^\s/]+/\S+"),   # /Users/user/... -> <path>
]
# Long hex (40+ chars) — potential keys/hashes/sigs. Optional 0x prefix.
_HEX_PATTERN = re.compile(r"(?:0x)?[a-fA-F0-9]{40,}")


def _sanitize_stderr(text: str) -> str:
    """Truncate and scrub paths/secrets from stderr before exposing in error messages."""
    if not text:
        return ""
    cleaned = text.strip()[:_MAX_STDERR_CHARS]
    for pattern in _PATH_PATTERNS:
        cleaned = pattern.sub("<path>", cleaned)
    cleaned = _HEX_PATTERN.sub("<hex>", cleaned)
    return cleaned


class KrakenCLIError(Exception):
    def __init__(self, code: str, message: str, suggestion: str = ""):
        self.code = code
        self.message = message
        self.suggestion = suggestion
        super().__init__(f"KrakenCLI error [{code}]: {message}")


class KrakenCLI:
    """
    Wrapper for the Kraken CLI.
    Uses subprocess to call the binary and parse JSON output.
    mode: 'paper' for testnet, 'order' for live (never use live in hackathon)
    """

    def __init__(self, mode: str = "paper", use_wsl: bool = False):
        self.mode = mode
        self.use_wsl = use_wsl  # True if running on Windows but kraken is in WSL

    def _run(self, args: list[str]) -> dict:
        if self.use_wsl:
            cmd = ["wsl", "kraken"] + args + ["-o", "json"]
        else:
            cmd = ["kraken"] + args + ["-o", "json"]
        logger.info(f"Kraken CLI: {' '.join(cmd)}")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except FileNotFoundError:
            raise KrakenCLIError("not_found", "kraken CLI binary not found in PATH", "Install: https://github.com/krakenfx/kraken-cli")
        except subprocess.TimeoutExpired:
            raise KrakenCLIError("timeout", "kraken CLI command timed out after 30s")

        if result.returncode != 0:
            try:
                error_data = json.loads(result.stdout) if result.stdout else {}
            except json.JSONDecodeError:
                error_data = {}
            # Sanitize stderr to mitigate info disclosure (paths, hex secrets)
            safe_stderr = _sanitize_stderr(result.stderr) or "Unknown error"
            raise KrakenCLIError(
                code=error_data.get("error", f"exit_{result.returncode}"),
                message=error_data.get("message", safe_stderr),
                suggestion=error_data.get("suggestion", "")
            )

        if not result.stdout.strip():
            return {}
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            # Truncated AND sanitized output for parse errors
            safe_preview = _sanitize_stderr(result.stdout)
            raise KrakenCLIError("parse_error", f"Failed to parse JSON: {safe_preview}")

    # --- Market Data (no API key needed) ---

    def get_ticker(self, pair: str = "BTC/USD") -> dict:
        return self._run(["market", "ticker", pair])

    def get_ohlc(self, pair: str = "BTC/USD", interval: int = 1) -> dict:
        return self._run(["market", "ohlc", pair, "--interval", str(interval)])

    def get_orderbook(self, pair: str = "BTC/USD", depth: int = 10) -> dict:
        return self._run(["market", "book", pair, "--count", str(depth)])

    # --- Paper Trading ---

    def paper_buy(self, pair: str, volume: float, order_type: str = "market") -> dict:
        return self._run([self.mode, "buy", pair, str(volume), "--type", order_type])

    def paper_sell(self, pair: str, volume: float, order_type: str = "market") -> dict:
        return self._run([self.mode, "sell", pair, str(volume), "--type", order_type])

    def paper_buy_limit(self, pair: str, volume: float, price: float) -> dict:
        return self._run([self.mode, "buy", pair, str(volume), "--type", "limit", "--price", str(price)])

    def paper_sell_limit(self, pair: str, volume: float, price: float) -> dict:
        return self._run([self.mode, "sell", pair, str(volume), "--type", "limit", "--price", str(price)])

    def paper_balance(self) -> dict:
        return self._run([self.mode, "balance"])

    def paper_status(self) -> dict:
        """Account summary including positions and PnL."""
        return self._run([self.mode, "status"])

    def paper_orders(self) -> dict:
        """Open orders."""
        return self._run([self.mode, "orders"])

    def paper_history(self) -> dict:
        """Trade history."""
        return self._run([self.mode, "history"])

    def paper_reset(self) -> dict:
        return self._run([self.mode, "reset"])
