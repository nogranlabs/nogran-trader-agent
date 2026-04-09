# Third-Party Code, Models and Services

This project uses the following external code, models and services. Each is
listed with its license and how it is consumed.

## External APIs / services

| Service | What we use it for | License / terms |
|---|---|---|
| **OpenAI API** (GPT-4o, GPT-4o-mini) | Strategy Engine LLM calls (`src/strategy/llm_strategy.py`, `llm_providers/openai_provider.py`) | OpenAI API Terms of Service |
| **Google Gemini API** (gemini-2.5-flash-lite) | Optional alternative LLM provider (`src/strategy/llm_providers/gemini_provider.py`) | Google AI / Gemini API Terms |
| **Kraken Pro CLI** | Execution layer for paper trading (`src/execution/kraken_cli.py`) | https://github.com/krakenfx/kraken-cli (own license) |
| **Kraken WebSocket / REST** | Live BTC/USD market data via `ccxt.pro` (`src/market/`) | Kraken API Terms |
| **Sepolia public RPCs** | ERC-8004 on-chain transactions (`src/compliance/erc8004_onchain.py`) | Free public infrastructure |

## Direct Python dependencies

Pinned in [`requirements.lock`](./requirements.lock); top-level deps in
[`requirements.txt`](./requirements.txt). All are MIT / Apache-2.0 / BSD
compatible:

| Package | License | Purpose |
|---|---|---|
| `ccxt` (>=4.5.46) | MIT | Exchange WebSocket and REST adapter |
| `websockets` (16.0) | BSD-3-Clause | Async WebSocket client |
| `pandas` (3.0.2) | BSD-3-Clause | Backtest data manipulation |
| `pydantic` (>=2.0,<3.0) | MIT | LLM response schema validation (`signal_parser.LLMSignalSchema`) |
| `requests` (2.33.1) | Apache-2.0 | HTTP utility |
| `aiohttp` (3.13.4) | Apache-2.0 | Async HTTP client |
| `python-dotenv` (1.2.2) | BSD-3-Clause | `.env` loader |
| `web3` (>=6.0) | MIT | ERC-8004 on-chain (optional) |
| `eth-account` (>=0.10) | MIT | EIP-712 signing of TradeIntents (optional) |
| `agent0-sdk` (1.7.0) | Apache-2.0 (per upstream) | Optional ERC-8004 discovery layer — used by `src/compliance/agent0_discovery.py` to publish OASF skills/domains. The trading pipeline does NOT depend on it. Install only if you want OASF discoverability. |

## Test / dev dependencies

| Package | License | Purpose |
|---|---|---|
| `pytest` | MIT | Test runner (386 tests) |
| `ruff` | MIT | Linter |
| `detect-secrets` | Apache-2.0 | CI secret-leak guard |

## Dashboard

| Package | License | Purpose |
|---|---|---|
| `streamlit` | Apache-2.0 | Dashboard UI (`dashboard/app.py`) |
| `plotly` | MIT | Charts (equity curve, KB performance) |

## Smart-contract patterns

The ERC-8004 integration follows the [EIP-8004 draft](https://eips.ethereum.org/EIPS/eip-8004)
and uses the **OpenZeppelin** (MIT) reference patterns for EIP-712 typed
signatures and ERC-721 metadata. We do **not** vendor any OpenZeppelin
Solidity contracts in this repo — only the Python signing helpers via
`eth-account`.

## What is NOT bundled

- No copyrighted books, PDFs, or proprietary trading materials.
- No price-action lecture material from any specific author. The "Nogran
  price action" methodology used by the agent is curated in-house, with
  setup probabilities tuned against backtest data.
- The optional `data/chunks/` directory is gitignored. If present locally,
  it is sourced from a separate private dataset repository and does not
  ship with this public repository.

## License

This project is released under the [MIT License](./LICENSE).
