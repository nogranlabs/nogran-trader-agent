"""
ERC-8004 on-chain integration — Hackathon Shared Contracts (Sepolia).

Contracts:
  AgentRegistry:      0x97b07dDc405B0c28B17559aFFE63BdB3632d0ca3
  HackathonVault:     0x0E7CD8ef9743FEcf94f9103033a044caBD45fC90
  RiskRouter:         0xd6A6952545FF6E6E6681c2d15C59f9EB8F40FdBC
  ReputationRegistry: 0x423a9904e39537a9997fbaF0f220d79D7d545763
  ValidationRegistry: 0x92bF63E5C7Ac6980f237a7164Ab413BE226187F1

Network: Sepolia Testnet (Chain ID: 11155111)
"""

import json
import logging
import time
from pathlib import Path

from eth_account import Account
from web3 import Web3

logger = logging.getLogger(__name__)

# --- Contract Addresses (Sepolia) ---
CHAIN_ID = 11155111
SEPOLIA_RPC = "https://rpc.sepolia.org"

ADDRESSES = {
    "agent_registry":      "0x97b07dDc405B0c28B17559aFFE63BdB3632d0ca3",
    "hackathon_vault":     "0x0E7CD8ef9743FEcf94f9103033a044caBD45fC90",
    "risk_router":         "0xd6A6952545FF6E6E6681c2d15C59f9EB8F40FdBC",
    "reputation_registry": "0x423a9904e39537a9997fbaF0f220d79D7d545763",
    "validation_registry": "0x92bF63E5C7Ac6980f237a7164Ab413BE226187F1",
}

ABIS_DIR = Path(__file__).parent / "abis"


class ERC8004Hackathon:
    """
    Full integration with the hackathon's 5 shared contracts on Sepolia.

    Flow:
      1. register_agent()        → AgentRegistry → get agentId
      2. claim_allocation()      → HackathonVault → 0.05 ETH sandbox capital
      3. submit_trade_intent()   → RiskRouter → on-chain trade validation
      4. post_checkpoint()       → ValidationRegistry → decision attestation
      5. submit_feedback()       → ReputationRegistry → reputation score
    """

    def __init__(self, private_key: str, rpc_url: str = SEPOLIA_RPC):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.account = Account.from_key(private_key)
        self.agent_id: int | None = None

        # Load contracts
        self.agent_registry = self._load_contract("agent_registry")
        self.vault = self._load_contract("hackathon_vault")
        self.router = self._load_contract("risk_router")
        self.reputation = self._load_contract("reputation_registry")
        self.validation = self._load_contract("validation_registry")

    def _load_contract(self, name: str):
        abi_path = ABIS_DIR / f"{name}.json"
        if not abi_path.exists():
            logger.warning(f"ABI not found: {abi_path}")
            return None
        with open(abi_path) as f:
            abi = json.load(f)
        address = Web3.to_checksum_address(ADDRESSES[name])
        return self.w3.eth.contract(address=address, abi=abi)

    def _send_tx(self, fn, gas: int = 300000, wait_timeout: int = 300):
        # Use 'pending' nonce so we don't collide with our own queued txs in mempool
        nonce = self.w3.eth.get_transaction_count(self.account.address, "pending")
        # Bump gas price 20% above network to outbid stuck pendings
        gas_price = int(self.w3.eth.gas_price * 1.2)
        tx = fn.build_transaction({
            "from": self.account.address,
            "nonce": nonce,
            "gas": gas,
            "gasPrice": gas_price,
            "chainId": CHAIN_ID,
        })
        signed = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        # Sepolia public RPCs can be slow — wait up to 5 minutes
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=wait_timeout)
        return receipt

    @property
    def address(self) -> str:
        return self.account.address

    @property
    def is_connected(self) -> bool:
        try:
            return self.w3.is_connected()
        except Exception:
            return False

    # =========================================================
    # STEP 1: Register Agent
    # =========================================================

    def register_agent(
        self,
        agent_wallet: str | None = None,
        name: str = "nogran.trader.agent",
        description: str = "Autonomous BTC/USD trading agent with Price Action RAG, Decision Scoring, and Risk Engine",
        capabilities: list[str] | None = None,
        agent_uri: str = "",
    ) -> int:
        """Register agent on AgentRegistry. Returns agentId."""
        if self.agent_registry is None:
            raise RuntimeError("AgentRegistry ABI not loaded")

        wallet = agent_wallet or self.account.address
        caps = capabilities or ["trading", "risk_management", "price_action_analysis"]

        logger.info(f"Registering agent: name={name}, wallet={wallet}")

        receipt = self._send_tx(
            self.agent_registry.functions.register(
                Web3.to_checksum_address(wallet),
                name,
                description,
                caps,
                agent_uri,
            ),
            gas=1_000_000,
        )

        if receipt.status != 1:
            raise RuntimeError(
                f"Registration tx reverted (status=0). tx={receipt.transactionHash.hex()} "
                f"gas_used={receipt.gasUsed}. Possiveis causas: nome/descricao muito longos, "
                f"agent ja registrado, ou validacao do contrato."
            )

        # Extract agentId from AgentRegistered event (best-effort)
        try:
            logs = self.agent_registry.events.AgentRegistered().process_receipt(receipt)
            if logs:
                self.agent_id = logs[0]["args"]["agentId"]
                logger.info(f"Agent registered! agentId={self.agent_id}, tx={receipt.transactionHash.hex()}")
                return self.agent_id
        except Exception as e:
            logger.warning(f"Could not parse AgentRegistered event ({e}), falling back to totalAgents()")

        # Fallback: derive from totalAgents() (assumes ours is the latest)
        try:
            total = self.agent_registry.functions.totalAgents().call()
            # Search latest 5 ids in case there are concurrent registrations
            for i in range(total, max(0, total - 5), -1):
                try:
                    agent = self.agent_registry.functions.getAgent(i).call()
                    owner = agent[0]
                    if owner.lower() == self.account.address.lower():
                        self.agent_id = i
                        logger.info(f"Agent registered (derived id={i}), tx={receipt.transactionHash.hex()}")
                        return i
                except Exception:
                    continue
        except Exception:
            pass

        raise RuntimeError(
            f"Registration tx succeeded (status=1) but no AgentRegistered event found "
            f"and totalAgents() fallback failed. tx={receipt.transactionHash.hex()}"
        )

    # =========================================================
    # STEP 2: Claim Allocation
    # =========================================================

    def claim_allocation(self) -> dict:
        """Claim 0.05 ETH sandbox capital from HackathonVault."""
        if self.vault is None:
            raise RuntimeError("HackathonVault ABI not loaded")
        if self.agent_id is None:
            raise RuntimeError("Agent not registered")

        # Check if already claimed
        claimed = self.vault.functions.hasClaimed(self.agent_id).call()
        if claimed:
            balance = self.vault.functions.getBalance(self.agent_id).call()
            logger.info(f"Already claimed. Balance: {Web3.from_wei(balance, 'ether')} ETH")
            return {"already_claimed": True, "balance_wei": balance}

        receipt = self._send_tx(
            self.vault.functions.claimAllocation(self.agent_id),
            gas=150000,
        )

        balance = self.vault.functions.getBalance(self.agent_id).call()
        logger.info(f"Allocation claimed! Balance: {Web3.from_wei(balance, 'ether')} ETH, tx={receipt.transactionHash.hex()}")
        return {"claimed": True, "balance_wei": balance, "tx": receipt.transactionHash.hex()}

    # =========================================================
    # STEP 3: Submit Trade Intent
    # =========================================================

    def submit_trade_intent(
        self,
        pair: str,
        action: str,
        amount_usd: float,
        max_slippage_bps: int = 100,
        deadline_seconds: int = 300,
    ) -> dict:
        """
        Submit trade intent to RiskRouter with EIP-712 signature.
        amount_usd: USD amount (e.g. 50.0 for $50)
        Returns {approved, reason, tx_hash}
        """
        if self.router is None:
            raise RuntimeError("RiskRouter ABI not loaded")
        if self.agent_id is None:
            raise RuntimeError("Agent not registered")

        # Get current nonce
        nonce = self.router.functions.getIntentNonce(self.agent_id).call()
        deadline = int(time.time()) + deadline_seconds
        amount_scaled = int(amount_usd * 100)  # USD * 100

        # Build intent struct
        intent = (
            self.agent_id,
            Web3.to_checksum_address(self.account.address),
            pair,
            action,
            amount_scaled,
            max_slippage_bps,
            nonce,
            deadline,
        )

        # Sign with EIP-712
        signature = self._sign_trade_intent(
            self.agent_id, pair, action, amount_scaled, max_slippage_bps, nonce, deadline
        )

        # Submit
        receipt = self._send_tx(
            self.router.functions.submitTradeIntent(intent, signature),
            gas=250000,
        )

        tx_hash_str = receipt.transactionHash.hex()

        # Status check (cheaper + reliable than event parsing with mismatched ABI)
        if receipt.status != 1:
            logger.warning(f"Trade tx reverted: {tx_hash_str}")
            return {"approved": False, "reason": "reverted", "tx": tx_hash_str}

        # Try to parse events for approval/rejection — best effort, ABI may mismatch.
        # On parse error, fall back to topic-based detection.
        try:
            approved_logs = self.router.events.TradeApproved().process_receipt(receipt)
            rejected_logs = self.router.events.TradeRejected().process_receipt(receipt)
            if approved_logs:
                logger.info(f"Trade APPROVED: {action} {pair} ${amount_usd}, tx={tx_hash_str}")
                return {"approved": True, "reason": "approved", "tx": tx_hash_str}
            if rejected_logs:
                try:
                    reason = rejected_logs[0]["args"]["reason"]
                except Exception:
                    reason = "rejected"
                logger.warning(f"Trade REJECTED: {reason}")
                return {"approved": False, "reason": reason, "tx": tx_hash_str}
        except Exception as e:
            logger.debug(f"Event parsing failed (ABI mismatch?), checking topics: {e}")

        # Topic-based fallback: check raw log topics
        TOPIC_APPROVED = "0x" + Web3.keccak(text="TradeApproved(uint256,bytes32,uint256)").hex().lstrip("0x")
        TOPIC_REJECTED = "0x" + Web3.keccak(text="TradeRejected(uint256,bytes32,string)").hex().lstrip("0x")
        for log in receipt.logs:
            if not log.topics:
                continue
            t0 = log.topics[0].hex()
            if not t0.startswith("0x"):
                t0 = "0x" + t0
            if t0 == TOPIC_APPROVED:
                logger.info(f"Trade APPROVED (topic match): {tx_hash_str}")
                return {"approved": True, "reason": "approved", "tx": tx_hash_str}
            if t0 == TOPIC_REJECTED:
                logger.warning(f"Trade REJECTED (topic match): {tx_hash_str}")
                return {"approved": False, "reason": "rejected", "tx": tx_hash_str}

        logger.warning(f"Tx succeeded but no Trade event found: {tx_hash_str}")
        return {"approved": False, "reason": "unknown", "tx": tx_hash_str}

    def simulate_trade_intent(
        self, pair: str, action: str, amount_usd: float, max_slippage_bps: int = 100,
    ) -> dict:
        """Dry-run: check if trade would be approved (no gas, view call)."""
        if self.router is None or self.agent_id is None:
            return {"approved": False, "reason": "not initialized"}

        nonce = self.router.functions.getIntentNonce(self.agent_id).call()
        deadline = int(time.time()) + 300
        amount_scaled = int(amount_usd * 100)

        intent = (
            self.agent_id,
            Web3.to_checksum_address(self.account.address),
            pair, action, amount_scaled, max_slippage_bps, nonce, deadline,
        )

        approved, reason = self.router.functions.simulateIntent(intent).call()
        return {"approved": approved, "reason": reason}

    # EIP-712 type hash for TradeIntent struct (must match contract exactly)
    _TRADE_INTENT_TYPE_STR = (
        "TradeIntent(uint256 agentId,address agentWallet,string pair,string action,"
        "uint256 amountUsdScaled,uint256 maxSlippageBps,uint256 nonce,uint256 deadline)"
    )
    _DOMAIN_TYPE_STR = (
        "EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
    )

    def _sign_trade_intent(
        self, agent_id, pair, action, amount_scaled, max_slippage_bps, nonce, deadline
    ) -> bytes:
        """Sign TradeIntent with EIP-712 (manual hash construction).

        We bypass eth_account.encode_typed_data because it has had subtle
        compatibility issues with strict Solidity verifiers. Manual encoding
        is verified to match the contract's verification logic for the
        hackathon RiskRouter (TYPEHASH validated against deployed contract).
        """
        from eth_abi import encode as abi_encode
        from eth_utils import keccak as eth_keccak

        # Compute typehashes
        type_hash = eth_keccak(text=self._TRADE_INTENT_TYPE_STR)
        domain_type_hash = eth_keccak(text=self._DOMAIN_TYPE_STR)

        # Encode struct: strings replaced by their keccak hashes per EIP-712 spec
        struct_hash = eth_keccak(abi_encode(
            ["bytes32", "uint256", "address", "bytes32", "bytes32",
             "uint256", "uint256", "uint256", "uint256"],
            [
                type_hash,
                agent_id,
                Web3.to_checksum_address(self.account.address),
                eth_keccak(text=pair),
                eth_keccak(text=action),
                amount_scaled,
                max_slippage_bps,
                nonce,
                deadline,
            ],
        ))

        # Domain separator
        domain_sep = eth_keccak(abi_encode(
            ["bytes32", "bytes32", "bytes32", "uint256", "address"],
            [
                domain_type_hash,
                eth_keccak(text="RiskRouter"),
                eth_keccak(text="1"),
                CHAIN_ID,
                Web3.to_checksum_address(ADDRESSES["risk_router"]),
            ],
        ))

        # Final EIP-712 digest: keccak256("\x19\x01" || domainSeparator || structHash)
        digest = eth_keccak(b"\x19\x01" + domain_sep + struct_hash)

        # Sign the digest directly using eth_account so v is in {27, 28}
        # (eth_keys returns v in {0,1}; OpenZeppelin's ECDSA expects {27,28}).
        signed = self.account.unsafe_sign_hash(digest)
        return signed.signature

    # =========================================================
    # STEP 4: Post Checkpoint (Validation)
    # =========================================================

    def post_checkpoint(
        self,
        decision_score: float,
        action: str,
        pair: str,
        reasoning_summary: str,
    ) -> dict | None:
        """Post decision checkpoint to ValidationRegistry."""
        if self.validation is None or self.agent_id is None:
            return None

        # Build checkpoint hash from decision data
        checkpoint_data = f"{self.agent_id}:{action}:{pair}:{decision_score}:{int(time.time())}"
        checkpoint_hash = Web3.keccak(text=checkpoint_data)

        # Score: map decision_score (0-100) to uint8 (0-100)
        score = min(100, max(0, int(decision_score)))

        notes = f"Action={action} Pair={pair} Score={decision_score:.1f} Reasoning={reasoning_summary[:100]}"

        try:
            receipt = self._send_tx(
                self.validation.functions.postEIP712Attestation(
                    self.agent_id, checkpoint_hash, score, notes
                ),
                gas=150000,
            )
            logger.info(f"Checkpoint posted: score={score}, tx={receipt.transactionHash.hex()}")
            return {"tx": receipt.transactionHash.hex(), "score": score}
        except Exception as e:
            logger.error(f"Failed to post checkpoint: {e}")
            return None

    # =========================================================
    # STEP 5: Submit Reputation Feedback
    # =========================================================

    def submit_feedback(
        self,
        score: int,
        trade_id: str = "",
        comment: str = "",
        feedback_type: int = 0,  # 0=TRADE_EXECUTION
    ) -> dict | None:
        """Submit reputation feedback. Score: 1-100."""
        if self.reputation is None or self.agent_id is None:
            return None

        outcome_ref = Web3.keccak(text=trade_id) if trade_id else b'\x00' * 32
        score = min(100, max(1, score))

        try:
            receipt = self._send_tx(
                self.reputation.functions.submitFeedback(
                    self.agent_id, score, outcome_ref, comment, feedback_type
                ),
                gas=150000,
            )
            logger.info(f"Feedback submitted: score={score}, tx={receipt.transactionHash.hex()}")
            return {"tx": receipt.transactionHash.hex(), "score": score}
        except Exception as e:
            logger.error(f"Failed to submit feedback: {e}")
            return None

    def get_reputation_score(self) -> int:
        """Get agent's average reputation score (0-100)."""
        if self.reputation is None or self.agent_id is None:
            return 0
        try:
            return self.reputation.functions.getAverageScore(self.agent_id).call()
        except Exception as e:
            logger.error(f"Failed to get reputation: {e}")
            return 0

    def get_validation_score(self) -> int:
        """Get agent's average validation score (0-100)."""
        if self.validation is None or self.agent_id is None:
            return 0
        try:
            return self.validation.functions.getAverageValidationScore(self.agent_id).call()
        except Exception as e:
            logger.error(f"Failed to get validation score: {e}")
            return 0
