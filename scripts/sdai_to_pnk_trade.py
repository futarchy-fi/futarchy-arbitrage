#!/usr/bin/env python3
"""
Minimal on-chain trade: spend 0.01 sDAI to buy PNK on Gnosis.

Notes
- Uses a Uniswap V2-style router (default: Sushi v2 on Gnosis).
- Default path: sDAI -> wxDAI -> WETH -> PNK. This may revert if any pair is missing
  on the chosen router; override via --path if needed.
- Sets minOut to 0 for simplicity. For production, pre-quote and set a real minOut.

Env vars
- RPC_URL (or GNOSIS_RPC_URL)
- PRIVATE_KEY
- ROUTER_ADDRESS (optional; default Sushi v2)

Usage
  python scripts/sdai_to_pnk_trade.py \
    --amount 0.01 \
    --router 0x1b02da8cb0d097eb8d57a175b88c7d8b47997506 \
    --recipient 0xYourAddress
"""

from __future__ import annotations

import os
import argparse
from decimal import Decimal
from typing import List

from dotenv import load_dotenv
from web3 import Web3


# Defaults (Gnosis)
SUSHI_V2_ROUTER = "0x1b02da8cb0d097eb8d57a175b88c7d8b47997506"
SDAI = "0xaf204776c7245bf4147c2612bf6e5972ee483701"
WETH = "0x6A023CCd1ff6F2045C3309768eAd9E68F978f6e1"
WXDAI = "0xe91D153E0b41518A2Ce8Dd3D7944Fa863463a97d"
PNK  = "0x37b60f4E9A31A64cCc0024dce7D0fD07eAA0F7B3"


ERC20_MIN_ABI = [
    {"constant": False, "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}],
     "name": "approve", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
    {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "stateMutability": "view", "type": "function"},
    {"constant": True, "inputs": [{"name": "owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
]

UNIV2_ROUTER_ABI = [
    {
        "name": "swapExactTokensForTokens",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "amountIn", "type": "uint256"},
            {"name": "amountOutMin", "type": "uint256"},
            {"name": "path", "type": "address[]"},
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"},
        ],
        "outputs": [{"name": "amounts", "type": "uint256[]"}],
    },
    {
        "name": "getAmountsOut",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "amountIn", "type": "uint256"},
            {"name": "path", "type": "address[]"},
        ],
        "outputs": [{"name": "amounts", "type": "uint256[]"}],
    },
]


def require_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise SystemExit(f"Missing env var: {name}")
    return v


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="Spend sDAI to buy PNK (Gnosis)")
    parser.add_argument("--amount", default="0.01", help="sDAI amount to spend (ether units). Default 0.01")
    parser.add_argument("--router", default=os.getenv("ROUTER_ADDRESS", SUSHI_V2_ROUTER), help="Uniswap v2 router address")
    parser.add_argument("--recipient", default=None, help="Recipient address (defaults to your EOA)")
    parser.add_argument("--path", nargs="*", default=[SDAI, WXDAI, WETH, PNK], help="Override path addresses (space-separated)")
    parser.add_argument("--slippage", default="0", help="AmountOutMin in ether units (default 0)")
    args = parser.parse_args()

    rpc_url = os.getenv("GNOSIS_RPC_URL") or os.getenv("RPC_URL")
    if not rpc_url:
        raise SystemExit("Set GNOSIS_RPC_URL or RPC_URL in env")
    priv = require_env("PRIVATE_KEY")

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    try:
        from web3.middleware import geth_poa_middleware
        w3.middleware_onion.inject(geth_poa_middleware, layer=0)
    except Exception:
        pass
    if not w3.is_connected():
        raise SystemExit("Failed to connect to RPC")

    acct = w3.eth.account.from_key(priv)
    recipient = Web3.to_checksum_address(args.recipient or acct.address)
    router_addr = Web3.to_checksum_address(args.router)
    path: List[str] = [Web3.to_checksum_address(p) for p in args.path]

    sdai = w3.eth.contract(address=Web3.to_checksum_address(SDAI), abi=ERC20_MIN_ABI)
    router = w3.eth.contract(address=router_addr, abi=UNIV2_ROUTER_ABI)

    amount_in_wei = w3.to_wei(Decimal(str(args.amount)), "ether")
    amount_out_min = w3.to_wei(Decimal(str(args.slippage)), "ether")
    deadline = int(w3.eth.get_block("latest").timestamp) + 1200

    # 1) Approve sDAI to the router for amount_in
    nonce = w3.eth.get_transaction_count(acct.address)
    approve_tx = sdai.functions.approve(router_addr, int(amount_in_wei)).build_transaction({
        "from": acct.address,
        "nonce": nonce,
        "chainId": w3.eth.chain_id,
    })
    # Set minimal EIP-1559 fees
    try:
        latest = w3.eth.get_block("latest")
        base_fee = latest.get("baseFeePerGas")
        tip = 1
        approve_tx.update({"maxFeePerGas": int(base_fee) * 2 + tip, "maxPriorityFeePerGas": tip})
    except Exception:
        approve_tx.update({"gasPrice": int(w3.eth.gas_price) + 1})
    try:
        approve_tx["gas"] = int(w3.eth.estimate_gas(approve_tx) * 1.2)
    except Exception:
        approve_tx["gas"] = 120_000
    signed_approve = acct.sign_transaction(approve_tx)
    raw_approve = getattr(signed_approve, "rawTransaction", None) or getattr(signed_approve, "raw_transaction", None)
    h1 = w3.eth.send_raw_transaction(raw_approve)
    print(f"Approve tx: {h1.hex()}")
    w3.eth.wait_for_transaction_receipt(h1)

    # 2) Swap sDAI -> ... -> PNK
    swap_tx = router.functions.swapExactTokensForTokens(
        int(amount_in_wei),
        int(amount_out_min),
        path,
        recipient,
        int(deadline),
    ).build_transaction({
        "from": acct.address,
        "nonce": nonce + 1,
        "chainId": w3.eth.chain_id,
    })
    try:
        latest = w3.eth.get_block("latest")
        base_fee = latest.get("baseFeePerGas")
        tip = 1
        swap_tx.update({"maxFeePerGas": int(base_fee) * 2 + tip, "maxPriorityFeePerGas": tip})
    except Exception:
        swap_tx.update({"gasPrice": int(w3.eth.gas_price) + 1})
    if "gas" not in swap_tx:
        try:
            gas_est = w3.eth.estimate_gas(swap_tx)
            swap_tx["gas"] = int(gas_est * 1.2)
        except Exception:
            swap_tx["gas"] = 1_000_000

    signed_swap = acct.sign_transaction(swap_tx)
    raw_swap = getattr(signed_swap, "rawTransaction", None) or getattr(signed_swap, "raw_transaction", None)
    h2 = w3.eth.send_raw_transaction(raw_swap)
    print(f"Swap tx: {h2.hex()}")
    rcpt = w3.eth.wait_for_transaction_receipt(h2)
    print(f"Success: {rcpt.status == 1}; Gas used: {rcpt.gasUsed}")


if __name__ == "__main__":
    main()
