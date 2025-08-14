# SPDX-License-Identifier: MIT
"""
7702 executor & normal-tx helpers for Balancer swapExactIn, wired to the
deployed FutarchyArbExecutorV4 at 0xb74a98b75B4efde911Bb95F7a2A0E7Bc3376e15B.

Capabilities:
  • Build a 7702 bundle: single call to FutarchyArbExecutorV4.runTrade(b).
  • Send normal tx either to runTrade (contract path) or directly to the router.
  • Load the full Futarchy ABI from FUTARCHY_EXECUTOR_ABI_JSON (recommended),
    else fall back to a minimal ABI that covers runTrade + TradeExecuted.

Environment variables:
  • FUTARCHY_EXECUTOR_ADDRESS  (optional; default is the deployed address below)
  • FUTARCHY_EXECUTOR_ABI_JSON (optional; path to JSON containing {"abi": [...]})
  • BALANCER_ROUTER_ADDRESS    (required unless provided at construction)
"""

from __future__ import annotations

import os
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, TypedDict

from web3 import Web3
from eth_typing import ChecksumAddress

# ---- Robust import of your Balancer helper ----------------------------------
# Prefer package import; fall back to top-level if project isn't packaged yet.
try:
    from src.trades.balancer_swap import (  # noqa
        COMPANY_TOKEN,
        SDAI,
        BUFFER_POOL,
        FINAL_POOL,
        BALANCER_ROUTER_ABI,
        MAX_DEADLINE,
        _get_router,
        build_sell_gno_to_sdai_swap_tx,
        build_buy_gno_to_sdai_swap_tx,
    )
except Exception:
    from trades.balancer_swap import (  # type: ignore  # noqa
        COMPANY_TOKEN,
        SDAI,
        BUFFER_POOL,
        FINAL_POOL,
        BALANCER_ROUTER_ABI,
        MAX_DEADLINE,
        _get_router,
        build_sell_gno_to_sdai_swap_tx,
        build_buy_gno_to_sdai_swap_tx,
    )

logger = logging.getLogger(__name__)

# ---- Deployed FutarchyArbExecutorV4 -----------------------------------------
ARB_EXECUTOR_ADDRESS_DEFAULT = "0xb74a98b75B4efde911Bb95F7a2A0E7Bc3376e15B"
BALANCER_VAULT_ADDRESS_DEFAULT = "0xba1333333333a1ba1108e8412f11850a5c319ba9"  # Gnosis Balancer V3 Vault

# ---- Minimal ABI (fallback) --------------------------------------------------
# Use full ABI via FUTARCHY_EXECUTOR_ABI_JSON when possible.
FUTARCHY_MIN_ABI: List[Dict[str, Any]] = [
    {
        "type": "function",
        "stateMutability": "nonpayable",
        "name": "runTrade",
        "inputs": [{
            "name": "b",
            "type": "tuple",
            "components": [
                {"name": "targets",      "type": "address[10]"},
                {"name": "calldatas",    "type": "bytes[10]"},
                {"name": "count",        "type": "uint256"},
                {"name": "tokenIn",      "type": "address"},
                {"name": "tokenOut",     "type": "address"},
                {"name": "spender",      "type": "address"},
                {"name": "amountIn",     "type": "uint256"},
                {"name": "minOut",       "type": "uint256"},
                {"name": "patchIndex",   "type": "uint8"},
                {"name": "amountOffset", "type": "uint256"},
                {"name": "minOutOffset", "type": "uint256"},
                {"name": "slippageBps",  "type": "uint16"},
            ],
        }],
        "outputs": [{"name": "out", "type": "uint256"}],
    },
    {
        "type": "event",
        "name": "TradeExecuted",
        "inputs": [
            {"indexed": True,  "name": "tokenIn",  "type": "address"},
            {"indexed": True,  "name": "tokenOut", "type": "address"},
            {"indexed": False, "name": "amountIn", "type": "uint256"},
            {"indexed": False, "name": "amountOut","type": "uint256"},
        ],
        "anonymous": False,
    },
    {
        "type": "function",
        "name": "runner",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "address"}],
    }
]

PATCH_NONE: int = 255
UINT256_MAX: int = (1 << 256) - 1


def _load_futarchy_abi(explicit_abi: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """
    Prefer an explicit ABI passed by the caller, else load from FUTARCHY_EXECUTOR_ABI_JSON,
    else use the minimal ABI fallback.
    The JSON file may be either {"abi":[...]} or just [...].
    """
    if explicit_abi:
        return explicit_abi
    p = os.getenv("FUTARCHY_EXECUTOR_ABI_JSON")
    if p:
        try:
            with open(p, "r") as f:
                obj = json.load(f)
            return obj["abi"] if isinstance(obj, dict) and "abi" in obj else obj
        except Exception as e:
            logger.warning("Failed to load ABI from %s: %s. Falling back to minimal ABI.", p, e)
    return FUTARCHY_MIN_ABI


@dataclass
class Call:
    """Generic call item for a 7702 bundle."""
    to: ChecksumAddress
    data: str
    value: int = 0

    def as_dict(self) -> Dict[str, Any]:
        # Adapt this shape to your 7702 bundler if it expects different keys.
        return {"to": self.to, "data": self.data, "value": self.value}


class Execute10BatchDict(TypedDict):
    targets: List[ChecksumAddress]
    calldatas: List[bytes]  # Changed from List[str] to List[bytes]
    count: int
    tokenIn: ChecksumAddress
    tokenOut: ChecksumAddress
    spender: ChecksumAddress
    amountIn: int
    minOut: int
    patchIndex: int
    amountOffset: int
    minOutOffset: int
    slippageBps: int


class Tx7702Executor:
    """
    Orchestrates Balancer swapExactIn calls via FutarchyArbExecutorV4.runTrade (7702 or normal),
    or directly against the Balancer BatchRouter.
    """

    def __init__(
        self,
        w3: Web3,
        arb_executor_addr: Optional[str] = None,
        router_addr: Optional[str] = None,
        vault_addr: Optional[str] = None,
        *,
        arb_abi: Optional[List[Dict[str, Any]]] = None,
        deadline: int = MAX_DEADLINE,
        weth_is_eth: bool = False,
        user_data: bytes = b"",
    ) -> None:
        self.w3 = w3
        self.deadline = int(deadline)
        self.weth_is_eth = bool(weth_is_eth)
        self.user_data = user_data

        arb_addr = arb_executor_addr or os.getenv("FUTARCHY_EXECUTOR_ADDRESS") or ARB_EXECUTOR_ADDRESS_DEFAULT
        self.arb = w3.eth.contract(
            address=w3.to_checksum_address(arb_addr),
            abi=_load_futarchy_abi(arb_abi),
        )
        self.router = _get_router(w3, router_addr)
        self.vault = self._resolve_vault_address(vault_addr)
    
    def _resolve_vault_address(self, vault_addr: Optional[str]) -> ChecksumAddress:
        """Resolve Balancer Vault address from explicit param, env var, or default."""
        # Try explicit parameter or environment variable first
        candidate = vault_addr or os.getenv("BALANCER_VAULT_ADDRESS")
        if candidate:
            return self.w3.to_checksum_address(candidate)
        
        # Try to discover from router if it exposes vault() or getVault()
        for fn_name in ("vault", "getVault"):
            try:
                vault_abi = [{
                    "type": "function",
                    "name": fn_name,
                    "inputs": [],
                    "outputs": [{"type": "address"}],
                    "stateMutability": "view"
                }]
                temp_contract = self.w3.eth.contract(address=self.router.address, abi=vault_abi)
                vault_address = temp_contract.functions[fn_name]().call()
                if int(vault_address, 16) != 0:
                    logger.info(f"Discovered Vault address from router.{fn_name}(): {vault_address}")
                    return self.w3.to_checksum_address(vault_address)
            except Exception:
                pass
        
        # Fall back to known default
        logger.info(f"Using default Vault address: {BALANCER_VAULT_ADDRESS_DEFAULT}")
        return self.w3.to_checksum_address(BALANCER_VAULT_ADDRESS_DEFAULT)

    # ------------------------- router calldata encoding -----------------------

    def _encode_router_swap_sell(self, amount_in_wei: int, min_amount_out_wei: int) -> str:
        """Encode swapExactIn for selling Company token for sDAI."""
        steps = [
            (BUFFER_POOL, BUFFER_POOL, True),  # COMPANY -> buffer
            (FINAL_POOL, SDAI, False),         # buffer  -> sDAI
        ]
        path = (COMPANY_TOKEN, steps, int(amount_in_wei), int(min_amount_out_wei))
        
        # Build function call and extract data
        function = self.router.functions.swapExactIn(
            [path], self.deadline, self.weth_is_eth, self.user_data
        )
        return function._encode_transaction_data()

    def _encode_router_swap_buy(self, amount_in_wei: int, min_amount_out_wei: int) -> str:
        """Encode swapExactIn for buying Company token with sDAI."""
        steps = [
            (FINAL_POOL, BUFFER_POOL, False),  # sDAI   -> buffer
            (BUFFER_POOL, COMPANY_TOKEN, True) # buffer -> COMPANY
        ]
        path = (SDAI, steps, int(amount_in_wei), int(min_amount_out_wei))
        
        # Build function call and extract data
        function = self.router.functions.swapExactIn(
            [path], self.deadline, self.weth_is_eth, self.user_data
        )
        return function._encode_transaction_data()

    # ------------------------- Execute10 batch builders ------------------------

    def _build_execute10_batch(
        self,
        swap_data: str,
        token_in: str,
        token_out: str,
        amount_in_wei: int,
        min_out_wei: int,
    ) -> Execute10BatchDict:
        zero = self.w3.to_checksum_address("0x" + "00" * 20)
        targets = [self.router.address] + [zero] * 9
        
        # Convert hex string to bytes and use empty bytes for other slots
        # This ensures proper ABI encoding for the bytes[] array
        calldatas = [bytes.fromhex(swap_data.replace("0x", ""))] + [b""] * 9
        
        return {
            "targets": targets,
            "calldatas": calldatas,
            "count": 1,
            "tokenIn": self.w3.to_checksum_address(token_in),
            "tokenOut": self.w3.to_checksum_address(token_out),
            "spender": self.vault,  # Vault must be the spender in Balancer V3, not the router
            "amountIn": int(amount_in_wei),
            "minOut": int(min_out_wei),
            "patchIndex": PATCH_NONE,
            "amountOffset": 0,
            "minOutOffset": UINT256_MAX,
            "slippageBps": 0,
        }

    def _build_runtrade_call(self, batch: Execute10BatchDict) -> Call:
        # Convert TypedDict to tuple format expected by the ABI
        batch_tuple = (
            batch["targets"],
            batch["calldatas"],
            batch["count"],
            batch["tokenIn"],
            batch["tokenOut"],
            batch["spender"],
            batch["amountIn"],
            batch["minOut"],
            batch["patchIndex"],
            batch["amountOffset"],
            batch["minOutOffset"],
            batch["slippageBps"],
        )
        data = self.arb.functions.runTrade(batch_tuple)._encode_transaction_data()
        return Call(to=self.arb.address, data=data, value=0)

    # ------------------------------ 7702 bundles -------------------------------

    def build_7702_bundle_sell(self, amount_in_wei: int, min_amount_out_wei: int) -> List[Call]:
        swap = self._encode_router_swap_sell(amount_in_wei, min_amount_out_wei)
        b = self._build_execute10_batch(swap, COMPANY_TOKEN, SDAI, amount_in_wei, min_amount_out_wei)
        return [self._build_runtrade_call(b)]

    def build_7702_bundle_buy(self, amount_in_wei: int, min_amount_out_wei: int) -> List[Call]:
        swap = self._encode_router_swap_buy(amount_in_wei, min_amount_out_wei)
        b = self._build_execute10_batch(swap, SDAI, COMPANY_TOKEN, amount_in_wei, min_amount_out_wei)
        return [self._build_runtrade_call(b)]

    # --------------------------- normal tx: runTrade ---------------------------

    def fetch_runner(self) -> Optional[str]:
        try:
            return self.arb.functions.runner().call()
        except Exception:
            return None

    def send_run_trade_sell(
        self,
        sender: str,
        private_key: str,
        amount_in_wei: int,
        min_amount_out_wei: int,
        *,
        must_be_runner: bool = True,
        gas: Optional[int] = None,
        gas_price_wei: Optional[int] = None,
        nonce: Optional[int] = None,
        chain_id: Optional[int] = None,
    ) -> str:
        if must_be_runner:
            r = self.fetch_runner()
            if r is not None and self.w3.to_checksum_address(sender) != self.w3.to_checksum_address(r):
                raise PermissionError(f"sender {sender} != runner {r}")
        swap = self._encode_router_swap_sell(amount_in_wei, min_amount_out_wei)
        b = self._build_execute10_batch(swap, COMPANY_TOKEN, SDAI, amount_in_wei, min_amount_out_wei)
        return self._send_run_trade(sender, private_key, b, gas, gas_price_wei, nonce, chain_id)

    def send_run_trade_buy(
        self,
        sender: str,
        private_key: str,
        amount_in_wei: int,
        min_amount_out_wei: int,
        *,
        must_be_runner: bool = True,
        gas: Optional[int] = None,
        gas_price_wei: Optional[int] = None,
        nonce: Optional[int] = None,
        chain_id: Optional[int] = None,
    ) -> str:
        if must_be_runner:
            r = self.fetch_runner()
            if r is not None and self.w3.to_checksum_address(sender) != self.w3.to_checksum_address(r):
                raise PermissionError(f"sender {sender} != runner {r}")
        swap = self._encode_router_swap_buy(amount_in_wei, min_amount_out_wei)
        b = self._build_execute10_batch(swap, SDAI, COMPANY_TOKEN, amount_in_wei, min_amount_out_wei)
        return self._send_run_trade(sender, private_key, b, gas, gas_price_wei, nonce, chain_id)

    def _send_run_trade(
        self,
        sender: str,
        private_key: str,
        batch: Execute10BatchDict,
        gas: Optional[int],
        gas_price_wei: Optional[int],
        nonce: Optional[int],
        chain_id: Optional[int],
    ) -> str:
        # Convert TypedDict to tuple format expected by the ABI
        batch_tuple = (
            batch["targets"],
            batch["calldatas"],
            batch["count"],
            batch["tokenIn"],
            batch["tokenOut"],
            batch["spender"],
            batch["amountIn"],
            batch["minOut"],
            batch["patchIndex"],
            batch["amountOffset"],
            batch["minOutOffset"],
            batch["slippageBps"],
        )
        # Get current gas price and add a small buffer for priority fee
        current_gas_price = self.w3.eth.gas_price
        # Ensure minimum gas price of 1 gwei if network returns very low value
        min_gas_price = self.w3.to_wei(1, 'gwei')
        effective_gas_price = max(current_gas_price, min_gas_price)
        
        tx = self.arb.functions.runTrade(batch_tuple).build_transaction({
            "from": self.w3.to_checksum_address(sender),
            "nonce": self.w3.eth.get_transaction_count(self.w3.to_checksum_address(sender)) if nonce is None else nonce,
            "gas": gas if gas is not None else 800_000,
            "gasPrice": gas_price_wei if gas_price_wei is not None else effective_gas_price,
            **({"chainId": chain_id} if chain_id is not None else {}),
        })
        signed = self.w3.eth.account.sign_transaction(tx, private_key)
        h = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        return h.hex()

    # ------------------------ normal tx: direct router -------------------------

    def send_direct_router_sell(
        self,
        sender: str,
        private_key: str,
        amount_in_wei: int,
        min_amount_out_wei: int,
        *,
        gas: Optional[int] = None,
        gas_price_wei: Optional[int] = None,
        nonce: Optional[int] = None,
        chain_id: Optional[int] = None,
    ) -> str:
        tx = build_sell_gno_to_sdai_swap_tx(self.w3, amount_in_wei, min_amount_out_wei, sender)
        if gas is not None:          tx["gas"] = gas
        
        # Ensure proper gas price
        if gas_price_wei is not None: 
            tx["gasPrice"] = gas_price_wei
        elif "gasPrice" not in tx or tx["gasPrice"] < self.w3.to_wei(1, 'gwei'):
            tx["gasPrice"] = max(self.w3.eth.gas_price, self.w3.to_wei(1, 'gwei'))
            
        if nonce is not None:        tx["nonce"] = nonce
        if chain_id is not None:     tx["chainId"] = chain_id
        signed = self.w3.eth.account.sign_transaction(tx, private_key)
        h = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        return h.hex()

    def send_direct_router_buy(
        self,
        sender: str,
        private_key: str,
        amount_in_wei: int,
        min_amount_out_wei: int,
        *,
        gas: Optional[int] = None,
        gas_price_wei: Optional[int] = None,
        nonce: Optional[int] = None,
        chain_id: Optional[int] = None,
    ) -> str:
        tx = build_buy_gno_to_sdai_swap_tx(self.w3, amount_in_wei, min_amount_out_wei, sender)
        if gas is not None:          tx["gas"] = gas
        if gas_price_wei is not None: tx["gasPrice"] = gas_price_wei
        if nonce is not None:        tx["nonce"] = nonce
        if chain_id is not None:     tx["chainId"] = chain_id
        signed = self.w3.eth.account.sign_transaction(tx, private_key)
        h = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        return h.hex()

    # ------------------------------- utilities --------------------------------
    
    def preflight_balancer_spend_check(self, token_addr: str) -> Dict[str, int]:
        """Check token balance and allowances before attempting a trade."""
        token_abi = [
            {
                "type": "function",
                "name": "balanceOf",
                "inputs": [{"type": "address", "name": "account"}],
                "outputs": [{"type": "uint256"}],
                "stateMutability": "view"
            },
            {
                "type": "function",
                "name": "allowance",
                "inputs": [
                    {"type": "address", "name": "owner"},
                    {"type": "address", "name": "spender"}
                ],
                "outputs": [{"type": "uint256"}],
                "stateMutability": "view"
            }
        ]
        token = self.w3.eth.contract(address=self.w3.to_checksum_address(token_addr), abi=token_abi)
        owner = self.arb.address
        
        return {
            "balance": token.functions.balanceOf(owner).call(),
            "allowance_to_vault": token.functions.allowance(owner, self.vault).call(),
            "allowance_to_router": token.functions.allowance(owner, self.router.address).call(),
            "vault_address": self.vault,
            "router_address": self.router.address,
        }

    def decode_trade_executed(self, receipt) -> Optional[Tuple[int, int]]:
        """Return (amountIn, amountOut) from the first TradeExecuted event, if present."""
        try:
            evts = self.arb.events.TradeExecuted().process_receipt(receipt)
            if not evts:
                return None
            e0 = evts[0]["args"]
            return int(e0["amountIn"]), int(e0["amountOut"])
        except Exception:
            return None