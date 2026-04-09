"""
Agent0 SDK discovery layer — optional enrichment of the on-chain agent.

This module is INDEPENDENT of the trading pipeline. It uses the official
Agent0 SDK (https://sdk.ag0.xyz/) to declare OASF skills, domains, and
MCP/A2A endpoints for the agent already registered on-chain by
`src/compliance/erc8004_onchain.py`.

Why a separate module:
- The Agent0 SDK is registration/discovery/reputation focused. It does
  NOT cover TradeIntent EIP-712 signing, RiskRouter approvals, or
  ValidationRegistry checkpoints — those are the core of our trading
  pipeline and live in `erc8004_onchain.py`.
- We use the SDK only to make the agent discoverable through OASF
  taxonomy (financial_analysis, algorithmic_trading, etc.) and to publish
  rich metadata via IPFS — without touching the trading code.
- Optional dep: the SDK is commented out in `requirements.txt` and this
  module is only imported when explicitly called.

Usage:
    # After init_erc8004() has registered the agent
    from compliance.agent0_discovery import publish_discovery_metadata
    publish_discovery_metadata(
        agent_id=erc.agent_id,
        chain_id=11155111,
        rpc_url=Config.SEPOLIA_RPC,
        signer_key=Config.ERC8004_PRIVATE_KEY,
    )
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# OASF taxonomy categories that describe what nogran.trader.agent does.
# Reference: https://sdk.ag0.xyz/ (Agent0 SDK validates these against the
# OASF v0.5 schema with 136 skills and 204 domains).
NOGRAN_SKILLS = [
    "financial_analysis/market_analysis",
    "financial_analysis/risk_management",
    "decision_making/automated_decision_making",
]
NOGRAN_DOMAINS = [
    "decentralized_finance",
    "financial_services",
]


def publish_discovery_metadata(
    agent_id: int,
    chain_id: int,
    rpc_url: str,
    signer_key: str,
    pinata_jwt: Optional[str] = None,
    mcp_endpoint: Optional[str] = None,
    a2a_endpoint: Optional[str] = None,
) -> dict:
    """Enrich the on-chain agent with OASF skills, domains and endpoints.

    Returns a dict describing what was published, or {"error": "..."} on
    failure. Never raises — discovery is best-effort.

    Requires `pip install agent0-sdk==1.7.0`. If the SDK is not installed,
    returns {"error": "agent0-sdk not installed"}.
    """
    try:
        from agent0_sdk import SDK  # type: ignore
    except ImportError:
        logger.warning(
            "Agent0 SDK not installed — skipping discovery metadata. "
            "Install with: pip install agent0-sdk==1.7.0"
        )
        return {"error": "agent0-sdk not installed"}

    if not signer_key:
        return {"error": "signer_key (ERC8004_PRIVATE_KEY) not provided"}
    if not agent_id:
        return {"error": "agent_id not provided — register on-chain first"}

    try:
        sdk_kwargs = {
            "chainId": chain_id,
            "rpcUrl": rpc_url,
            "signer": signer_key,
        }
        if pinata_jwt:
            sdk_kwargs["ipfs"] = "pinata"
            sdk_kwargs["pinataJwt"] = pinata_jwt

        sdk = SDK(**sdk_kwargs)
        agent = sdk.loadAgent(agent_id)

        for skill in NOGRAN_SKILLS:
            try:
                agent.addSkill(skill, validate_oasf=True)
            except Exception as e:
                logger.warning(f"Skipped skill {skill!r}: {e}")

        for domain in NOGRAN_DOMAINS:
            try:
                agent.addDomain(domain)
            except Exception as e:
                logger.warning(f"Skipped domain {domain!r}: {e}")

        if mcp_endpoint:
            agent.setMCP(mcp_endpoint)
        if a2a_endpoint:
            agent.setA2A(a2a_endpoint)

        logger.info(
            f"Agent0 SDK: enriched agent_id={agent_id} with "
            f"{len(NOGRAN_SKILLS)} skills and {len(NOGRAN_DOMAINS)} domains"
        )
        return {
            "agent_id": agent_id,
            "skills": list(NOGRAN_SKILLS),
            "domains": list(NOGRAN_DOMAINS),
            "mcp_endpoint": mcp_endpoint,
            "a2a_endpoint": a2a_endpoint,
        }
    except Exception as e:
        logger.error(f"Agent0 SDK discovery enrichment failed: {e}")
        return {"error": str(e)}
